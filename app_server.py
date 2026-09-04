#!/usr/bin/env python3
"""Local read-only dashboard for the sector momentum radar.

The server deliberately has no broker integration. It exposes the latest
generated snapshot, a local user-portfolio file, and explanatory analysis
details to the browser UI.
"""

from __future__ import annotations

import argparse
import datetime as dt
import itertools
import json
import math
import os
import re
import time
from getpass import getpass
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from src.metric_explanations import acquisition_analysis, display_metric_name, metric_reading, personalized_metric_reading
from src.momentum_tool import news_request_count
from src.paper_trading import paper_coverage
from src.horizon_signals import build_horizon_views
from src.action_commentary import action_commentary, commentary_entries, commentary_markdown
from src.auth import (
    SESSION_COOKIE,
    SESSION_TTL_SECONDS,
    auth_disabled,
    configured_username,
    create_session,
    delete_session,
    login_allowed,
    parse_cookie,
    record_failed_login,
    session_for,
    setup_required,
    verify_credentials,
)


ROOT = Path(__file__).resolve().parent
OUTPUT_DIR = ROOT / "outputs"
UI_DIR = ROOT / "ui"
CONFIG_PATH = ROOT / "config.json"
PORTFOLIO_PATH = ROOT / "data" / "user_portfolio.json"
PORTFOLIO_TARGETS_PATH = ROOT / "data" / "portfolio_targets.json"
JOURNAL_PATH = ROOT / "data" / "decision_journal.json"
CATALOG_PATH = ROOT / "data" / "asset_catalog.json"
IMPORTED_CATALOG_PATH = ROOT / "data" / "portfolio_import_2026-08-06.json"
ON_DEMAND_DIR = ROOT / "data" / "on_demand"
SIGNAL_HISTORY_PATH = OUTPUT_DIR / "signal-history.jsonl"
PAPER_STATUS_PATH = OUTPUT_DIR / "paper-week-100k_status.json"
PAPER_REPORT_PATH = OUTPUT_DIR / "paper-week-100k-report.md"
PAPER_TRADES_PATH = OUTPUT_DIR / "paper-week-100k_trades.csv"
PAPER_LADDER_STATUS_PATH = OUTPUT_DIR / "paper-ladder-v1_status.json"
PAPER_LADDER_REPORT_PATH = OUTPUT_DIR / "paper-ladder-v1-report.md"
PAPER_LADDER_TRADES_PATH = OUTPUT_DIR / "paper-ladder-v1_trades.csv"
PAPER_MATRIX_STATUS_PATH = OUTPUT_DIR / "paper-matrix-v2_status.json"
PAPER_MATRIX_REPORT_PATH = OUTPUT_DIR / "paper-matrix-v2-report.md"
PAPER_MATRIX_TRADES_PATH = OUTPUT_DIR / "paper-matrix-v2_trades.csv"
AUTOMATION_STATUS_PATH = OUTPUT_DIR / "automation-status.json"
AUTOMATION_HISTORY_PATH = OUTPUT_DIR / "automation-history.jsonl"
LIVE_VALIDATION_PATH = OUTPUT_DIR / "live-validation.json"
SYMBOL_RE = re.compile(r"^[A-Z0-9][A-Z0-9._-]{0,19}$")


def sensitivity_report_path() -> Path:
    return OUTPUT_DIR / "sensitivity-report.md"


def sensitivity_report_metadata() -> dict[str, Any]:
    """Expose the local sensitivity diagnostic without running it or using the network."""
    report_path = sensitivity_report_path()
    payload = read_json(OUTPUT_DIR / "sensitivity.json", {})
    if not report_path.is_file():
        return {"available": False, "url": "/api/sensitivity-report"}
    return {
        "available": True,
        "url": "/api/sensitivity-report",
        "scenario_count": int(number(payload.get("scenario_count"), 0)) if isinstance(payload, dict) else 0,
        "generated_at": str(payload.get("generated_at", "")) if isinstance(payload, dict) else "",
        "mode": str(payload.get("mode", "demo")) if isinstance(payload, dict) else "demo",
    }


def live_validation_snapshot() -> dict[str, Any]:
    """Expose the last explicit live-provider validation without contacting APIs."""
    payload = read_json(LIVE_VALIDATION_PATH, {})
    if not isinstance(payload, dict) or not payload:
        return {"available": False, "path": str(LIVE_VALIDATION_PATH)}
    critical = payload.get("critical_failures", []) if isinstance(payload.get("critical_failures", []), list) else []
    context = payload.get("context_failures", []) if isinstance(payload.get("context_failures", []), list) else []
    return {
        "available": True,
        "passed": bool(payload.get("passed")),
        "generated_at": str(payload.get("generated_at", "")),
        "rows": int(number(payload.get("rows"), 0)),
        "critical_failures": len(critical),
        "context_failures": len(context),
        "allow_missing_context": bool(payload.get("allow_missing_context")),
        "path": str(LIVE_VALIDATION_PATH),
    }


def live_validation_markdown() -> tuple[str, str]:
    """Build a local, secret-free report from the last validation artifact."""
    validation = live_validation_snapshot()
    lines = ["# Validação live do Radar", ""]
    if not validation.get("available"):
        lines.extend(["Ainda não existe uma validação live guardada em `outputs/live-validation.json`.", ""])
        return "radar-validacao-live.md", "\n".join(lines)
    status = "PASSOU" if validation.get("passed") else "FALHOU"
    lines.extend([
        f"**Estado:** {status}",
        f"**Gerada em:** {validation.get('generated_at') or 'sem data'}",
        f"**Linhas recolhidas:** {validation.get('rows', 0)}",
        f"**Falhas críticas:** {validation.get('critical_failures', 0)}",
        f"**Falhas de contexto:** {validation.get('context_failures', 0)}",
        "",
        "> Este documento descreve a última validação explícita das fontes configuradas. Não gera ordens nem substitui a confirmação de frescura, cobertura e termos dos providers.",
        "",
    ])
    payload = read_json(LIVE_VALIDATION_PATH, {})
    for label, key in (("Falhas críticas", "critical_failures"), ("Falhas de contexto", "context_failures")):
        rows = payload.get(key, []) if isinstance(payload, dict) and isinstance(payload.get(key, []), list) else []
        if not rows:
            continue
        lines.extend([f"## {label}", "", "| Símbolo | Estado | Mensagem |", "|---|---|---|"])
        for row in rows:
            if not isinstance(row, dict):
                continue
            message = str(row.get("message", "")).replace("|", "/").replace("\n", " ")
            lines.append(f"| {row.get('symbol', '')} | {row.get('status', '')} | {message} |")
        lines.append("")
    return "radar-validacao-live.md", "\n".join(lines)


def read_json(path: Path, fallback: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        return fallback


def automation_history_snapshot(limit: int = 12) -> dict[str, Any]:
    """Read terminal automation runs without contacting providers."""
    try:
        lines = AUTOMATION_HISTORY_PATH.read_text(encoding="utf-8").splitlines()[-max(1, limit):]
    except (FileNotFoundError, OSError):
        lines = []
    runs: list[dict[str, Any]] = []
    for line in lines:
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(item, dict) or str(item.get("state", "")).lower() == "running":
            continue
        runs.append({
            "run_id": str(item.get("run_id", item.get("started_at", ""))),
            "state": str(item.get("state", "")),
            "started_at": str(item.get("started_at", "")),
            "completed_at": str(item.get("completed_at", "")),
            "mode": str(item.get("mode", "")),
            "paper": bool(item.get("paper")),
            "price_provider": str(item.get("price_provider", "")),
            "universe_profile": str(item.get("universe_profile", "")),
            "exit_code": int(number(item.get("exit_code"), 0)),
            "error": str(item.get("error", "")),
        })
    if not runs:
        current = read_json(AUTOMATION_STATUS_PATH, {})
        if isinstance(current, dict) and str(current.get("state", "")).lower() in {"completed", "failed"}:
            runs = [{
                "run_id": str(current.get("run_id", current.get("started_at", ""))),
                "state": str(current.get("state", "")),
                "started_at": str(current.get("started_at", "")),
                "completed_at": str(current.get("completed_at", "")),
                "mode": str(current.get("mode", "")),
                "paper": bool(current.get("paper")),
                "price_provider": str(current.get("price_provider", "")),
                "universe_profile": str(current.get("universe_profile", "")),
                "exit_code": int(number(current.get("exit_code"), 0)),
                "error": str(current.get("error", "")),
                "migrated_from_status": True,
            }]
    failed = sum(1 for item in runs if item.get("state", "").lower() == "failed")
    return {
        "available": bool(runs),
        "runs": list(reversed(runs)),
        "recorded_runs": len(runs),
        "failed_runs": failed,
        "completed_runs": sum(1 for item in runs if item.get("state", "").lower() == "completed"),
    }


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def load_signal_history(limit: int = 500) -> list[dict[str, Any]]:
    """Read the compact local signal ledger without contacting providers."""
    try:
        lines = SIGNAL_HISTORY_PATH.read_text(encoding="utf-8").splitlines()[-max(1, limit):]
    except (FileNotFoundError, OSError):
        return []
    history: list[dict[str, Any]] = []
    for line in lines:
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(item, dict):
            continue
        symbol = str(item.get("symbol", "")).strip().upper()
        if not symbol or not str(item.get("as_of", "")).strip():
            continue
        history.append({
            "symbol": symbol,
            "as_of": str(item.get("as_of", "")),
            "score": number(item.get("score")),
            "confidence": number(item.get("confidence")),
            "action": str(item.get("action", "")),
            "price": number(item.get("price")),
        })
    return history


def compare_snapshots(history: list[dict[str, Any]]) -> dict[str, Any]:
    """Compare the two latest local signal snapshots without provider calls."""
    dates = sorted({str(item.get("as_of", "")) for item in history if str(item.get("as_of", "")).strip()})
    if len(dates) < 2:
        return {"available": False, "message": "Ainda não existem dois snapshots para comparar.", "rows": []}
    previous_date, current_date = dates[-2:]
    previous = {str(item.get("symbol", "")).upper(): item for item in history if str(item.get("as_of")) == previous_date}
    current = {str(item.get("symbol", "")).upper(): item for item in history if str(item.get("as_of")) == current_date}
    rows: list[dict[str, Any]] = []
    for symbol in sorted(set(previous) & set(current)):
        before = previous[symbol]
        after = current[symbol]
        before_score = number(before.get("score"), 0.0)
        after_score = number(after.get("score"), 0.0)
        rows.append({
            "symbol": symbol,
            "score_before": round(before_score, 2),
            "score_after": round(after_score, 2),
            "score_delta": round(after_score - before_score, 2),
            "action_before": str(before.get("action", "")),
            "action_after": str(after.get("action", "")),
            "changed_action": str(before.get("action", "")) != str(after.get("action", "")),
        })
    rows.sort(key=lambda item: abs(number(item.get("score_delta"))), reverse=True)
    deltas = [number(item.get("score_delta")) for item in rows]
    return {
        "available": bool(rows),
        "previous_as_of": previous_date,
        "current_as_of": current_date,
        "symbols_compared": len(rows),
        "action_changes": sum(bool(item.get("changed_action")) for item in rows),
        "average_score_delta": round(sum(deltas) / len(deltas), 2) if deltas else 0.0,
        "rows": rows[:8],
    }


def snapshot_comparison_markdown() -> tuple[str, str]:
    """Build a local comparison report from the signal ledger."""
    comparison = compare_snapshots(load_signal_history())
    lines = ["# Comparação local de snapshots", ""]
    if not comparison.get("available"):
        lines.extend([str(comparison.get("message", "Ainda não há comparação disponível.")), ""])
        return "radar-comparacao-snapshots.md", "\n".join(lines)
    lines.extend([
        f"**Período:** {comparison['previous_as_of']} → {comparison['current_as_of']}  ",
        f"**Símbolos comparados:** {comparison['symbols_compared']}  ",
        f"**Mudanças de ação:** {comparison['action_changes']}  ",
        f"**Variação média do score:** {number(comparison['average_score_delta']):+.2f}",
        "",
        "> Comparação descritiva do ledger local. Não é uma previsão nem uma recomendação de investimento.",
        "",
        "| Símbolo | Score anterior | Score atual | Variação | Ação anterior | Ação atual |",
        "|---|---:|---:|---:|---|---|",
    ])
    for row in comparison.get("rows", []):
        lines.append(f"| {row['symbol']} | {number(row['score_before']):.2f} | {number(row['score_after']):.2f} | {number(row['score_delta']):+.2f} | {row['action_before']} | {row['action_after']} |")
    lines.append("")
    return "radar-comparacao-snapshots.md", "\n".join(lines)


def load_portfolio_targets() -> dict[str, float]:
    """Load user-defined sector targets without accepting arbitrary payloads."""
    raw = read_json(PORTFOLIO_TARGETS_PATH, {})
    raw = raw.get("targets", raw) if isinstance(raw, dict) else {}
    if not isinstance(raw, dict):
        return {}
    targets: dict[str, float] = {}
    for sector, value in raw.items():
        label = str(sector).strip()[:120]
        target = number(value, -1.0)
        if label and 0.0 <= target <= 1.0:
            targets[label] = round(target, 6)
    return targets


def save_portfolio_targets(targets: dict[str, Any]) -> dict[str, float]:
    """Persist only normalized sector percentages; never store credentials."""
    clean: dict[str, float] = {}
    for sector, value in (targets or {}).items():
        label = str(sector).strip()[:120]
        target = number(value, -1.0)
        if label and 0.0 <= target <= 1.0:
            clean[label] = round(target, 6)
    write_json(PORTFOLIO_TARGETS_PATH, {"updated_at": dt.datetime.now(dt.timezone.utc).isoformat(), "targets": clean})
    return clean


def portfolio_sector_drift(sector_exposure: list[dict[str, Any]], targets: dict[str, float], total_value: float) -> list[dict[str, Any]]:
    """Join current sector weights with targets and calculate actionable drift."""
    current = {str(item.get("sector", "Sem setor")): number(item.get("weight")) for item in sector_exposure}
    sectors = list(dict.fromkeys([*current.keys(), *targets.keys()]))
    rows: list[dict[str, Any]] = []
    for sector in sectors:
        actual = current.get(sector, 0.0)
        target = number(targets.get(sector), 0.0) if sector in targets else None
        drift = None if target is None else actual - target
        rows.append({
            "sector": sector,
            "actual": round(actual, 6),
            "target": None if target is None else round(target, 6),
            "drift": None if drift is None else round(drift, 6),
            "value_gap": None if drift is None else round(drift * total_value, 2),
            "status": "sem_meta" if target is None else "acima" if drift > 0.02 else "abaixo" if drift < -0.02 else "alinhado",
        })
    return sorted(rows, key=lambda item: abs(number(item.get("drift"), 0.0)), reverse=True)


def load_journal() -> list[dict[str, Any]]:
    raw = read_json(JOURNAL_PATH, {})
    entries = raw.get("entries", []) if isinstance(raw, dict) else raw if isinstance(raw, list) else []
    clean: list[dict[str, Any]] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        symbol = str(entry.get("symbol", "")).strip().upper()
        note = str(entry.get("note", "")).strip()
        as_of = str(entry.get("as_of", "")).strip()
        if symbol and note and as_of:
            clean.append({"symbol": symbol, "as_of": as_of, "note": note[:2000], "updated_at": str(entry.get("updated_at", ""))})
    return clean


def save_journal_entry(symbol: str, as_of: str, note: str) -> list[dict[str, Any]]:
    wanted = symbol.strip().upper()
    current = [entry for entry in load_journal() if not (entry["symbol"] == wanted and entry["as_of"] == as_of)]
    if note.strip():
        current.append({
            "symbol": wanted,
            "as_of": as_of,
            "note": note.strip()[:2000],
            "updated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        })
    current.sort(key=lambda entry: (entry["symbol"], entry["as_of"]))
    write_json(JOURNAL_PATH, {"entries": current})
    return current


def load_catalog() -> list[dict[str, Any]]:
    """Return configured, public and imported instruments as one searchable shelf."""
    configured = read_json(CONFIG_PATH, {})
    configured_assets = configured.get("universe", []) if isinstance(configured, dict) else []
    base = read_json(CATALOG_PATH, [])
    imported = read_json(IMPORTED_CATALOG_PATH, {})
    imported_assets = imported.get("assets", []) if isinstance(imported, dict) else []
    merged: dict[str, dict[str, Any]] = {}
    for item in [*(configured_assets if isinstance(configured_assets, list) else []), *(base if isinstance(base, list) else []), *(imported_assets if isinstance(imported_assets, list) else [])]:
        if not isinstance(item, dict):
            continue
        symbol = str(item.get("symbol", "")).strip().upper()
        if symbol:
            merged[symbol] = item
    return list(merged.values())


def number(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def provider_quota_bucket(provider: str) -> str:
    return "alpha_vantage" if str(provider).lower() in {"alpha_vantage", "news"} else str(provider).lower()


def daily_budget_rows(config: dict[str, Any], cache_stats: dict[str, Any], calls: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Summarize local daily caps without exposing credentials or request details."""
    network = config.get("network", {}) if isinstance(config.get("network", {}), dict) else {}
    budgets = network.get("daily_call_budgets", {}) if isinstance(network.get("daily_call_budgets", {}), dict) else {}
    counts: dict[str, int] = {}
    for call in calls:
        bucket = provider_quota_bucket(str(call.get("provider", "")))
        if bucket:
            counts[bucket] = counts.get(bucket, 0) + 1
    usage = cache_stats.get("daily_calls", {}) if isinstance(cache_stats.get("daily_calls", {}), dict) else {}
    today = dt.datetime.now(dt.timezone.utc).date().isoformat()
    rows: list[dict[str, Any]] = []
    for bucket, estimated in sorted(counts.items()):
        raw_limit = budgets.get(bucket)
        try:
            limit = None if raw_limit is None or str(raw_limit).strip().lower() in {"", "none", "unlimited"} else max(0, int(raw_limit))
        except (TypeError, ValueError):
            limit = None
        usage_item = usage.get(bucket, {}) if isinstance(usage.get(bucket, {}), dict) else {}
        try:
            used = max(0, int(usage_item.get("calls", 0))) if usage_item.get("date") == today else 0
        except (TypeError, ValueError):
            used = 0
        remaining = None if limit is None else max(0, limit - used)
        rows.append({
            "provider": bucket,
            "estimated_calls": estimated,
            "used_today": used,
            "limit": limit,
            "remaining": remaining,
            "shortfall": max(0, estimated - remaining) if remaining is not None else 0,
        })
    return rows


def daily_budget_snapshot(config: dict[str, Any], cache_stats: dict[str, Any]) -> list[dict[str, Any]]:
    """Return today's local provider budget state for the dashboard."""
    network = config.get("network", {}) if isinstance(config.get("network", {}), dict) else {}
    budgets = network.get("daily_call_budgets", {}) if isinstance(network.get("daily_call_budgets", {}), dict) else {}
    usage = cache_stats.get("daily_calls", {}) if isinstance(cache_stats.get("daily_calls", {}), dict) else {}
    today = dt.datetime.now(dt.timezone.utc).date().isoformat()
    buckets = set(str(key).lower() for key in budgets) | set(str(key).lower() for key in usage)
    rows: list[dict[str, Any]] = []
    for bucket in sorted(item for item in buckets if item):
        raw_limit = budgets.get(bucket)
        try:
            limit = None if raw_limit is None or str(raw_limit).strip().lower() in {"", "none", "unlimited"} else max(0, int(raw_limit))
        except (TypeError, ValueError):
            limit = None
        usage_item = usage.get(bucket, {}) if isinstance(usage.get(bucket, {}), dict) else {}
        try:
            used = max(0, int(usage_item.get("calls", 0))) if usage_item.get("date") == today else 0
        except (TypeError, ValueError):
            used = 0
        remaining = None if limit is None else max(0, limit - used)
        if limit is None:
            status = "sem_limite_local"
        elif remaining <= 0:
            status = "esgotado"
        elif remaining / max(1, limit) <= 0.2:
            status = "atencao"
        else:
            status = "ok"
        rows.append({"provider": bucket, "date": today, "used_today": used, "limit": limit, "remaining": remaining, "status": status})
    return rows


def portfolio_action(model_action: str, has_position: bool) -> str:
    """Translate the generic low-score label into a portfolio-specific action."""
    if model_action == "Reduzir/evitar":
        return "Reduzir/vender" if has_position else "Evitar"
    return model_action


def portfolio_correlation_pairs(positions: list[dict[str, Any]], payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Estimate pairwise return correlation from the latest local history."""
    symbols = sorted({str(item.get("symbol", "")).upper() for item in positions if item.get("symbol")})
    prices: dict[str, dict[str, float]] = {symbol: {} for symbol in symbols}
    for row in payload.get("history", []) if isinstance(payload, dict) else []:
        symbol = str(row.get("symbol", "")).upper()
        if symbol not in prices:
            continue
        close = number(row.get("close"))
        date_value = str(row.get("date", ""))
        if close > 0 and date_value:
            prices[symbol][date_value] = close
    pairs: list[dict[str, Any]] = []
    for left, right in itertools.combinations(symbols, 2):
        common_dates = sorted(set(prices[left]) & set(prices[right]))
        if len(common_dates) < 21:
            continue
        left_returns = [prices[left][date] / prices[left][previous] - 1.0 for previous, date in zip(common_dates, common_dates[1:]) if prices[left][previous] > 0]
        right_returns = [prices[right][date] / prices[right][previous] - 1.0 for previous, date in zip(common_dates, common_dates[1:]) if prices[right][previous] > 0]
        size = min(len(left_returns), len(right_returns))
        if size < 20:
            continue
        left_returns = left_returns[:size]
        right_returns = right_returns[:size]
        left_mean = sum(left_returns) / size
        right_mean = sum(right_returns) / size
        left_var = sum((value - left_mean) ** 2 for value in left_returns)
        right_var = sum((value - right_mean) ** 2 for value in right_returns)
        denominator = math.sqrt(left_var * right_var)
        if denominator <= 0:
            continue
        correlation = sum((left_returns[index] - left_mean) * (right_returns[index] - right_mean) for index in range(size)) / denominator
        if abs(correlation) >= 0.6:
            pairs.append({"left": left, "right": right, "correlation": round(correlation, 3), "observations": size, "approximate": True})
    return sorted(pairs, key=lambda item: abs(item["correlation"]), reverse=True)[:8]


def portfolio_risk_contribution(positions: list[dict[str, Any]], payload: dict[str, Any]) -> dict[str, Any]:
    """Estimate each holding's contribution to portfolio return variability.

    This is a local covariance calculation over common daily observations. It
    is deliberately labelled approximate: it is not a forecast, stress test,
    or look-through analysis of fund constituents.
    """
    symbols = [str(item.get("symbol", "")).upper() for item in positions if item.get("symbol") and number(item.get("weight")) > 0]
    if not symbols:
        return {"rows": [], "observations": 0, "annualized_volatility": None}
    prices: dict[str, dict[str, float]] = {symbol: {} for symbol in symbols}
    for row in payload.get("history", []) if isinstance(payload, dict) else []:
        symbol = str(row.get("symbol", "")).upper()
        close = number(row.get("close"))
        date_value = str(row.get("date", ""))
        if symbol in prices and close > 0 and date_value:
            prices[symbol][date_value] = close
    if any(len(values) < 2 for values in prices.values()):
        return {"rows": [], "observations": 0, "annualized_volatility": None}
    common_dates = sorted(set.intersection(*(set(values) for values in prices.values())))
    if len(common_dates) < 21:
        return {"rows": [], "observations": 0, "annualized_volatility": None}
    returns: dict[str, list[float]] = {symbol: [] for symbol in symbols}
    for previous, current in zip(common_dates, common_dates[1:]):
        if all(prices[symbol][previous] > 0 and prices[symbol][current] > 0 for symbol in symbols):
            for symbol in symbols:
                returns[symbol].append(prices[symbol][current] / prices[symbol][previous] - 1.0)
    observations = min((len(values) for values in returns.values()), default=0)
    if observations < 20:
        return {"rows": [], "observations": observations, "annualized_volatility": None}
    returns = {symbol: values[:observations] for symbol, values in returns.items()}
    weights = {str(item.get("symbol", "")).upper(): number(item.get("weight")) for item in positions}
    weight_total = sum(weights.get(symbol, 0.0) for symbol in symbols)
    if weight_total <= 0:
        return {"rows": [], "observations": observations, "annualized_volatility": None}
    weights = {symbol: weights.get(symbol, 0.0) / weight_total for symbol in symbols}
    means = {symbol: sum(values) / observations for symbol, values in returns.items()}
    portfolio_returns = [sum(weights[symbol] * returns[symbol][index] for symbol in symbols) for index in range(observations)]
    portfolio_mean = sum(portfolio_returns) / observations
    denominator = max(1, observations - 1)
    portfolio_variance = sum((value - portfolio_mean) ** 2 for value in portfolio_returns) / denominator
    if portfolio_variance <= 0:
        return {"rows": [], "observations": observations, "annualized_volatility": 0.0}
    rows: list[dict[str, Any]] = []
    for position in positions:
        symbol = str(position.get("symbol", "")).upper()
        if symbol not in returns:
            continue
        covariance = sum((returns[symbol][index] - means[symbol]) * (portfolio_returns[index] - portfolio_mean) for index in range(observations)) / denominator
        standalone_variance = sum((value - means[symbol]) ** 2 for value in returns[symbol]) / denominator
        contribution = weights[symbol] * covariance / portfolio_variance
        rows.append({
            "symbol": symbol,
            "weight": round(weights[symbol], 6),
            "annualized_volatility": round(math.sqrt(max(0.0, standalone_variance)) * math.sqrt(252), 6),
            "contribution_pct": round(contribution, 6),
            "observations": observations,
            "approximate": True,
        })
    return {
        "rows": sorted(rows, key=lambda item: abs(item["contribution_pct"]), reverse=True),
        "observations": observations,
        "annualized_volatility": round(math.sqrt(portfolio_variance) * math.sqrt(252), 6),
    }


def safe_error_message(value: Any) -> str:
    message = str(value)
    for variable in ("ALPHAVANTAGE_API_KEY", "FRED_API_KEY", "COINMARKETCAP_API_KEY"):
        secret = os.environ.get(variable, "").strip()
        if secret:
            message = message.replace(secret, "<redacted>")
    return re.sub(r"(api\s*key(?:\s+as)?\s+)[A-Za-z0-9_-]{8,}", r"\1<redacted>", message, flags=re.IGNORECASE)


def horizon_views(signal: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    """Translate the same evidence into three decision horizons.

    These are entry-quality lenses, not price targets or return forecasts.
    """
    return build_horizon_views(signal, context)

def age_hours(iso_value: str, now: dt.datetime | None = None) -> float | None:
    if not iso_value:
        return None
    try:
        parsed = dt.datetime.fromisoformat(iso_value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=dt.timezone.utc)
        reference = now or dt.datetime.now(dt.timezone.utc)
        if reference.tzinfo is None:
            reference = reference.replace(tzinfo=dt.timezone.utc)
        return max(0.0, (reference - parsed).total_seconds() / 3600)
    except ValueError:
        return None


def snapshot_freshness(iso_value: str, now: dt.datetime | None = None) -> dict[str, Any]:
    """Classify snapshot age without treating a normal weekend as an API failure."""
    reference = now or dt.datetime.now(dt.timezone.utc)
    if reference.tzinfo is None:
        reference = reference.replace(tzinfo=dt.timezone.utc)
    age = age_hours(iso_value, reference)
    weekend = reference.weekday() >= 5
    threshold = 72.0 if weekend else 36.0
    return {"age_hours": age, "weekend": weekend, "stale": age is not None and age > threshold, "threshold_hours": threshold}


def load_state(include_heavy: bool = True) -> dict[str, Any]:
    payload = read_json(OUTPUT_DIR / "momentum_data.json", {})
    config = read_json(CONFIG_PATH, {})
    catalog = load_catalog()
    portfolio = read_json(PORTFOLIO_PATH, {"updated_at": None, "positions": []})
    paper = read_json(PAPER_STATUS_PATH, {})
    paper_ladder = read_json(PAPER_LADDER_STATUS_PATH, {})
    paper_matrix = read_json(PAPER_MATRIX_STATUS_PATH, {})
    automation = read_json(AUTOMATION_STATUS_PATH, {})
    automation_history = automation_history_snapshot()
    signals = {str(item.get("symbol", "")).upper(): item for item in payload.get("signals", []) if isinstance(item, dict)}
    quality = {str(item.get("symbol", "")).upper(): item for item in payload.get("quality", []) if isinstance(item, dict)}
    on_demand: list[dict[str, Any]] = []
    on_demand_contexts: dict[str, dict[str, Any]] = {}
    if ON_DEMAND_DIR.exists():
        for cache_path in ON_DEMAND_DIR.glob("*.json"):
            cached = read_json(cache_path, {})
            if not isinstance(cached, dict) or not isinstance(cached.get("signal"), dict):
                continue
            symbol = str(cached["signal"].get("symbol", "")).upper()
            if not symbol:
                continue
            signals[symbol] = cached["signal"]
            if isinstance(cached.get("quality"), dict):
                quality[symbol] = cached["quality"]
            if isinstance(cached.get("context"), dict):
                on_demand_contexts[symbol] = cached["context"]
            usage_details = cached.get("usage_details", {}) if isinstance(cached.get("usage_details", {}), dict) else {}
            safe_usage = {key: usage_details.get(key) for key in ("provider", "ttl_seconds", "context_ttl_seconds", "cache_age_seconds", "context_reused") if key in usage_details}
            on_demand.append({"symbol": symbol, "fetched_at": cached.get("fetched_at"), "cached": cached.get("cached", False), "usage_details": safe_usage})
    runtime_config = payload.get("config", {}) if isinstance(payload.get("config", {}), dict) else config
    runtime_universe = runtime_config.get("universe", config.get("universe", [])) if isinstance(runtime_config, dict) else config.get("universe", [])
    universe = [item for item in runtime_universe if isinstance(item, dict)]
    catalog = [item for item in catalog if isinstance(item, dict)] or []
    catalog_symbols = {str(item.get("symbol", "")).upper() for item in catalog}
    catalog.extend(item for item in universe if str(item.get("symbol", "")).upper() not in catalog_symbols)
    universe_by_symbol = {str(item.get("symbol", "")).upper(): item for item in universe}
    catalog_by_symbol = {str(item.get("symbol", "")).upper(): item for item in catalog}

    positions: list[dict[str, Any]] = []
    for raw in portfolio.get("positions", []) if isinstance(portfolio, dict) else []:
        if not isinstance(raw, dict):
            continue
        symbol = str(raw.get("symbol", "")).strip().upper()
        quantity = number(raw.get("quantity"))
        average_cost = number(raw.get("avg_cost"))
        if not symbol or quantity <= 0 or average_cost < 0:
            continue
        signal = signals.get(symbol, {})
        current_price = number(signal.get("price"))
        statement_value_eur = number(raw.get("statement_value_eur"), 0.0)
        native_currency = str(raw.get("currency", payload.get("meta", {}).get("currency", "USD")))
        reference_price = number(raw.get("reference_price"), 0.0)
        native_market_value = quantity * current_price if current_price > 0 else 0.0
        implied_eur_rate = None
        valuation_source = ""
        valuation_approximate = False
        if statement_value_eur > 0 and quantity > 0 and reference_price > 0:
            implied_eur_rate = statement_value_eur / (quantity * reference_price)
            market_value = native_market_value * implied_eur_rate if native_market_value > 0 else statement_value_eur
            valuation_source = "câmbio implícito do extrato"
            valuation_approximate = native_currency != "EUR" or current_price > 0
        elif statement_value_eur > 0:
            market_value = statement_value_eur
            valuation_source = "valor EUR do extrato"
        elif native_currency == "EUR" and native_market_value > 0:
            market_value = native_market_value
            implied_eur_rate = 1.0
            valuation_source = "preço live em EUR"
        else:
            market_value = 0.0
            valuation_source = "sem conversão EUR disponível"
            valuation_approximate = True
        market_value_currency = "EUR"
        invested = quantity * average_cost
        cost_analysis = acquisition_analysis(
            average_cost,
            current_price,
            signal.get("action", ""),
            catalog_by_symbol.get(symbol, {}).get("name", symbol),
            str(raw.get("currency", payload.get("meta", {}).get("currency", "USD"))),
        )
        positions.append({
            "symbol": symbol,
            "quantity": quantity,
            "avg_cost": average_cost,
            "currency": str(raw.get("currency", payload.get("meta", {}).get("currency", "USD"))),
            "market_value_currency": market_value_currency,
            "native_market_value": native_market_value or None,
            "native_market_value_currency": native_currency,
            "implied_eur_rate": round(implied_eur_rate, 8) if implied_eur_rate is not None else None,
            "valuation_source": valuation_source,
            "valuation_approximate": valuation_approximate,
            "broker": str(raw.get("broker", "")),
            "isin": str(raw.get("isin", "")),
            "exchange": str(raw.get("exchange", "")),
            "reference_price": reference_price or None,
            "cost_basis_status": str(raw.get("cost_basis_status", "confirmado_manual")),
            "cost_basis_note": str(raw.get("cost_basis_note", "")),
            "cost_unit": str(raw.get("cost_unit", "")),
            "statement_value_eur": statement_value_eur or None,
            "sector": signal.get("sector") or catalog_by_symbol.get(symbol, {}).get("sector") or universe_by_symbol.get(symbol, {}).get("sector", "Fora do radar"),
            "price": current_price,
            "market_value": market_value,
            "pnl": native_market_value - invested if current_price > 0 else None,
            "pnl_pct": (current_price / average_cost - 1.0) if current_price > 0 and average_cost > 0 else None,
            "acquisition_analysis": cost_analysis,
            "action": signal.get("action", "Sem análise"),
            "score": signal.get("score"),
            "confidence": signal.get("confidence"),
            "data_status": quality.get(symbol, {}).get("status", "Sem dados"),
            "in_radar": symbol in universe_by_symbol,
        })

    total_value = sum(number(item.get("market_value")) for item in positions)
    for item in positions:
        item["weight"] = number(item.get("market_value")) / total_value if total_value else 0.0
    portfolio_currency = "EUR"
    portfolio_valuation_approximate = any(bool(item.get("valuation_approximate")) for item in positions)
    missing_valuation_count = sum(1 for item in positions if number(item.get("market_value")) <= 0)
    sector_values: dict[str, float] = {}
    for item in positions:
        sector = str(item.get("sector") or "Fora do radar")
        sector_values[sector] = sector_values.get(sector, 0.0) + number(item.get("market_value"))
    sector_exposure = [
        {
            "sector": sector,
            "market_value": round(value, 2),
            "weight": round(value / total_value, 6) if total_value else 0.0,
            "currency_basis": portfolio_currency,
            "approximate": portfolio_valuation_approximate,
        }
        for sector, value in sorted(sector_values.items(), key=lambda pair: pair[1], reverse=True)
    ]
    sector_targets = load_portfolio_targets()
    sector_drift = portfolio_sector_drift(sector_exposure, sector_targets, total_value)

    position_symbols = {str(item.get("symbol", "")).upper() for item in positions}
    correlation_pairs = portfolio_correlation_pairs(positions, payload)
    risk_contribution = portfolio_risk_contribution(positions, payload)
    for symbol, signal in signals.items():
        model_action = str(signal.get("action", ""))
        signal["model_action"] = model_action
        signal["action"] = portfolio_action(model_action, symbol in position_symbols)
    for position in positions:
        signal = signals.get(str(position.get("symbol", "")).upper())
        if not signal:
            continue
        position["action"] = signal.get("action", position.get("action", "Sem análise"))
        position["acquisition_analysis"] = acquisition_analysis(
            position.get("avg_cost"),
            signal.get("price"),
            signal.get("action"),
            catalog_by_symbol.get(str(position.get("symbol", "")).upper(), {}).get("name", position.get("symbol", "")),
            position.get("currency", payload.get("meta", {}).get("currency", "USD")),
        )

    meta = payload.get("meta", {}) if isinstance(payload, dict) else {}
    outcomes_payload = payload.get("outcomes", {}) if isinstance(payload, dict) else {}
    if isinstance(outcomes_payload, dict) and not outcomes_payload.get("summary"):
        try:
            from src.momentum_tool import summarize_outcomes

            outcome_horizons = outcomes_payload.get("horizons", config.get("evaluation_horizons", [5, 20]))
            outcomes_payload = {**outcomes_payload, "summary": summarize_outcomes(OUTPUT_DIR / "signal-outcomes.jsonl", str(meta.get("mode", "")), outcome_horizons)}
        except (ImportError, OSError, TypeError, ValueError):
            pass
    cache_stats_payload = payload.get("cache_stats", {}) if isinstance(payload, dict) else {}
    if not cache_stats_payload:
        try:
            from src.momentum_tool import read_cache_stats

            cache_stats_payload = read_cache_stats()
        except (ImportError, OSError, TypeError, ValueError):
            cache_stats_payload = {"version": 1, "namespaces": {}}
    quota_rows = daily_budget_snapshot(config, cache_stats_payload if isinstance(cache_stats_payload, dict) else {})
    live_validation = live_validation_snapshot()
    signal_history = load_signal_history()
    context_payload = payload.get("context", {}) if isinstance(payload, dict) else {}
    for symbol, signal in signals.items():
        signal["horizons"] = horizon_views(signal, on_demand_contexts.get(symbol, context_payload))
    signal_rows = list(signals.values())
    quality_rows = list(quality.values())
    failed_quality = [item for item in quality_rows if str(item.get("status", "")).upper() not in {"OK", "", "FORA_DA_COORTE"}]
    out_of_cohort = [item for item in quality_rows if str(item.get("status", "")).upper() == "FORA_DA_COORTE"]
    fallback_quality = [item for item in quality_rows if item.get("fallback_used")]
    alerts = list(payload.get("alerts", {}).get("events", [])) if isinstance(payload, dict) else []
    artifact_status = payload.get("artifact_status", {}) if isinstance(payload, dict) and isinstance(payload.get("artifact_status", {}), dict) else {}
    supervision: list[dict[str, Any]] = []
    automation_state = str(automation.get("state", "")).lower() if isinstance(automation, dict) else ""
    if automation_state == "failed":
        supervision.append({"level": "danger", "title": "Última automação falhou", "detail": str(automation.get("error") or "A última tarefa terminou com erro; confirma o log e repete a execução." )})
    elif automation_state == "running":
        supervision.append({"level": "warning", "title": "Ronda em execução", "detail": "A recolha local ainda não terminou; aguarda o estado completed antes de interpretar o snapshot."})
    if str(artifact_status.get("report", "")).lower() == "failed":
        supervision.append({"level": "warning", "title": "Relatório não foi atualizado", "detail": str(artifact_status.get("error") or "Os dados centrais foram guardados, mas o relatório falhou. O paper trading e o Excel podem continuar a usar o snapshot válido.")})
    history_failures = int(automation_history.get("failed_runs", 0)) if isinstance(automation_history, dict) else 0
    if history_failures and automation_state == "completed":
        supervision.append({"level": "warning", "title": "Histórico de automação com falhas", "detail": f"O histórico local guarda {history_failures} execução(ões) falhada(s) nas últimas {automation_history.get('recorded_runs', history_failures)}. Confirma se as datas sem snapshot coincidem com essas falhas."})
    freshness = snapshot_freshness(str(meta.get("generated_at", "")))
    generated_age = freshness.get("age_hours")
    if freshness.get("weekend") and generated_age is not None and generated_age > 24:
        supervision.append({"level": "info", "title": "Mercados tradicionais fechados", "detail": f"O snapshot tem {generated_age:.0f} h, mas o limite de fim de semana é 72 h. Cripto pode continuar a negociar; confirma-a separadamente se precisares de uma leitura intradiária."})
    if freshness.get("stale"):
        supervision.append({"level": "warning", "title": "Dados podem estar desatualizados", "detail": f"Última execução há {generated_age:.0f} h. Confirma a tarefa diária antes de agir."})
    if not meta.get("context_available", True):
        supervision.append({"level": "danger", "title": "Contexto incompleto", "detail": "Notícias ou ambiente económico não estão disponíveis; os sinais devem ficar bloqueados."})
    if failed_quality:
        names = ", ".join(str(item.get("symbol", "")) for item in failed_quality[:4])
        suffix = "…" if len(failed_quality) > 4 else ""
        supervision.append({"level": "warning", "title": "Qualidade a verificar", "detail": f"Fontes fora de OK: {names}{suffix}."})
    if fallback_quality:
        details = ", ".join(f"{item.get('symbol', '')} ({item.get('provider_requested', 'provider')} → {item.get('provider_used', item.get('source', 'alternativa'))})" for item in fallback_quality[:4])
        suffix = "…" if len(fallback_quality) > 4 else ""
        supervision.append({"level": "info", "title": "Fallback de provider em uso", "detail": f"Leituras obtidas por alternativa: {details}{suffix}. Confirma a frescura e a cobertura antes de interpretar o sinal."})
    if live_validation.get("available") and not live_validation.get("passed"):
        supervision.append({"level": "danger", "title": "Validação live falhou", "detail": f"A última validação encontrou {live_validation.get('critical_failures', 0)} falhas críticas e {live_validation.get('context_failures', 0)} falhas de contexto. Não trates este snapshot como pronto para decisões reais."})
    cohort_meta = meta.get("cohort", {}) if isinstance(meta, dict) and isinstance(meta.get("cohort", {}), dict) else {}
    if cohort_meta.get("rotated") and out_of_cohort:
        rounds = cohort_meta.get("rotation_rounds") or "várias"
        next_round = cohort_meta.get("next_rotation_index")
        next_date = cohort_meta.get("next_rotation_date")
        next_text = f" Próxima coorte: {int(next_round) + 1}/{rounds} em {next_date}." if next_round is not None and next_date else ""
        supervision.append({"level": "info", "title": "Cobertura em rotação", "detail": f"{len(out_of_cohort)} ativos ainda não foram visitados; a ronda atual cobre {len(cohort_meta.get('active_symbols', []))} ativos e faz parte de {rounds} coortes. Não é uma falha de provider.{next_text}"})
    exhausted_quota = [item for item in quota_rows if item.get("status") == "esgotado"]
    low_quota = [item for item in quota_rows if item.get("status") == "atencao"]
    if exhausted_quota:
        names = ", ".join(str(item.get("provider", "")) for item in exhausted_quota)
        supervision.append({"level": "danger", "title": "Quota local esgotada", "detail": f"O orçamento diário UTC terminou para {names}; análises live ficam bloqueadas antes da rede."})
    elif low_quota:
        detail = ", ".join(f"{item['provider']}: {item['remaining']} restantes" for item in low_quota)
        supervision.append({"level": "warning", "title": "Quota local perto do limite", "detail": f"{detail}. Usa o snapshot/cache antes de recolher live."})
    if total_value and any(number(item.get("weight")) > number(config.get("thresholds", {}).get("max_position_pct", 0.1)) for item in positions):
        supervision.append({"level": "warning", "title": "Concentração elevada", "detail": "Uma posição ultrapassa o limite configurado. Revê o risco antes de aumentar exposição."})
    max_sector_pct = number(config.get("thresholds", {}).get("max_sector_pct", 0.2), 0.2)
    if total_value and any(number(item.get("weight")) > max_sector_pct for item in sector_exposure):
        supervision.append({"level": "warning", "title": "Concentração por setor", "detail": "Um setor ultrapassa o limite configurado. Confirma o risco antes de aumentar exposição."})
    if portfolio_valuation_approximate and sector_exposure:
        supervision.append({"level": "info", "title": "Carteira normalizada para EUR", "detail": "Posições noutras moedas usam o câmbio implícito no extrato. Os pesos são comparáveis, mas continuam aproximados até existir uma taxa cambial atual."})
    target_total = sum(sector_targets.values())
    if sector_targets and abs(target_total - 1.0) > 0.01:
        supervision.append({"level": "info", "title": "Metas de setor incompletas", "detail": f"As metas guardadas somam {target_total:.1%}; os restantes {max(0.0, 1.0 - target_total):.1%} ficam sem meta explícita."})
    large_drifts = [item for item in sector_drift if item.get("drift") is not None and abs(number(item.get("drift"))) > 0.05]
    if large_drifts:
        names = ", ".join(str(item.get("sector", "")) for item in large_drifts[:3])
        supervision.append({"level": "warning", "title": "Desvio face às metas", "detail": f"Há setores mais de 5 pontos percentuais afastados da meta: {names}. O quadro de carteira mostra o desvio; não gera ordens."})
    monitor_settings = config.get("network", {}).get("portfolio_monitor", {}) if isinstance(config.get("network", {}), dict) else {}
    monitor_plan = payload.get("network_plan", {}).get("portfolio_monitor", {}) if isinstance(payload.get("network_plan", {}), dict) else {}
    selected_monitor_symbols = {str(value).upper() for value in monitor_plan.get("selected_symbols", []) if str(value).strip()}
    monitor_limit = int(monitor_settings.get("max_assets_per_run", 10)) if isinstance(monitor_settings, dict) else 10
    latest_by_symbol: dict[str, str] = {}
    for row in payload.get("history", []):
        if isinstance(row, dict):
            symbol = str(row.get("symbol", "")).upper()
            date = str(row.get("date", ""))
            if symbol and date > latest_by_symbol.get(symbol, ""):
                latest_by_symbol[symbol] = date
    signal_date = str(meta.get("as_of", ""))
    for symbol in signals:
        if symbol and signal_date > latest_by_symbol.get(symbol, ""):
            latest_by_symbol[symbol] = signal_date
    core_symbols = {symbol for symbol, item in universe_by_symbol.items() if not item.get("portfolio_monitor_only")}
    preview_candidates = sorted(
        positions,
        key=lambda item: (
            latest_by_symbol.get(str(item.get("symbol", "")).upper(), ""),
            -number(item.get("statement_value_eur"), number(item.get("market_value"), 0.0)),
            str(item.get("symbol", "")).upper(),
        ),
    )
    preview_symbols = [
        str(item.get("symbol", "")).upper()
        for item in preview_candidates
        if str(item.get("symbol", "")).upper() not in core_symbols and str(item.get("symbol", "")).upper() in catalog_by_symbol
    ][:max(0, monitor_limit)]
    position_by_symbol = {str(item.get("symbol", "")).upper(): item for item in positions}
    preview_queue = [
        {
            "symbol": symbol,
            "last_read": latest_by_symbol.get(symbol) or None,
            "reason": f"última leitura {latest_by_symbol[symbol]}" if latest_by_symbol.get(symbol) else "sem leitura local",
            "statement_value_eur": number(position_by_symbol.get(symbol, {}).get("statement_value_eur"), number(position_by_symbol.get(symbol, {}).get("market_value"), 0.0)),
        }
        for symbol in preview_symbols
    ]
    portfolio_monitor = {
        "enabled": bool(monitor_settings.get("enabled", True)) if isinstance(monitor_settings, dict) else True,
        "max_assets_per_run": monitor_limit,
        "reserve_calls": int(monitor_settings.get("reserve_calls", 5)) if isinstance(monitor_settings, dict) else 5,
        "selected_symbols": sorted(selected_monitor_symbols),
        "selected_count": len(selected_monitor_symbols),
        "covered_count": sum(1 for symbol in selected_monitor_symbols if symbol in signals),
        "requested_count": int(monitor_plan.get("requested_count", len(selected_monitor_symbols)) or 0),
        "trimmed_count": int(monitor_plan.get("trimmed_count", 0) or 0),
        "trimmed_symbols": [str(value).upper() for value in monitor_plan.get("trimmed_symbols", []) if str(value).strip()],
        "budget_fitted": bool(monitor_plan.get("budget_fitted", True)),
        "next_symbols": preview_symbols,
        "next_queue": preview_queue,
        "next_count": len(preview_symbols),
        "position_count": len(positions),
        "last_run_as_of": str(meta.get("as_of", "")),
        "last_run_mode": str(meta.get("mode", "")),
    }
    portfolio_monitor["message"] = "Ativa no próximo comando live com monitorização da carteira." if portfolio_monitor["enabled"] and not selected_monitor_symbols else "A ronda live priorizou posições sem leitura ou com dados mais antigos; nenhuma ordem é criada."
    if portfolio_monitor["trimmed_count"]:
        portfolio_monitor["message"] = f"A quota segura reduziu a ronda de {portfolio_monitor['requested_count']} para {portfolio_monitor['selected_count']} posições; {portfolio_monitor['trimmed_count']} ficaram para a próxima fila."
    if portfolio_monitor["enabled"] and not selected_monitor_symbols and positions:
        supervision.append({"level": "info", "title": "Monitorização da carteira preparada", "detail": f"A próxima ronda live seleciona até {portfolio_monitor['max_assets_per_run']} posições sem leitura ou com dados mais antigos e mantém {portfolio_monitor['reserve_calls']} chamadas de reserva. O valor serve apenas de desempate. Esta preparação não recolhe dados nem cria ordens."})
    elif portfolio_monitor["enabled"] and selected_monitor_symbols:
        supervision.append({"level": "info", "title": "Monitorização da carteira ativa", "detail": f"Esta ronda selecionou {len(selected_monitor_symbols)} posições prioritárias; {portfolio_monitor['covered_count']} têm leitura no snapshot. Os ativos monitorizados ficam fora do paper trading."})
        if portfolio_monitor["trimmed_count"]:
            supervision.append({"level": "warning", "title": "Ronda reduzida para preservar quota", "detail": portfolio_monitor["message"]})
    paper_progress = paper.get("review_progress", {}) if isinstance(paper, dict) else {}
    if paper_progress:
        paper_title = "Paper trading pronto para revisão" if paper_progress.get("ready_for_review") else "Paper trading em validação"
        paper_level = "good" if paper_progress.get("ready_for_review") else "info"
        supervision.append({"level": paper_level, "title": paper_title, "detail": str(paper_progress.get("message", "A amostra ainda está a crescer."))})
        coverage = paper_progress.get("coverage", {}) if isinstance(paper_progress.get("coverage", {}), dict) else paper_coverage(paper)
        missing_dates = coverage.get("missing_potential_dates", []) if isinstance(coverage, dict) else []
        if coverage.get("available") and missing_dates:
            shown_dates = ", ".join(str(value) for value in missing_dates[:4])
            suffix = "…" if len(missing_dates) > 4 else ""
            supervision.append({"level": "warning", "title": "Cobertura paper incompleta", "detail": f"Foram observados {coverage.get('observed_snapshots', 0)}/{coverage.get('potential_weekdays', 0)} dias úteis potenciais; sem snapshot: {shown_dates}{suffix}. Feriados ou fechos podem explicar parte das lacunas."})
    entry_review = paper.get("last_entry_review", {}) if isinstance(paper, dict) else {}
    if entry_review:
        entry_count = int(number(entry_review.get("entries_executed", 0), 0))
        blockers = entry_review.get("blockers", []) if isinstance(entry_review.get("blockers", []), list) else []
        near_entries = entry_review.get("near_entry_candidates", []) if isinstance(entry_review.get("near_entry_candidates", []), list) else []
        if entry_review.get("status") == "run_blocked":
            detail = str(blockers[0].get("message", "A recolha foi bloqueada antes da revisão.")) if blockers and isinstance(blockers[0], dict) else "A recolha foi bloqueada antes da revisão."
            supervision.append({"level": "warning", "title": "Paper sem revisão de entradas", "detail": detail})
        elif entry_review.get("status") == "duplicate":
            detail = str(blockers[0].get("message", "A data de mercado ja foi processada; nao houve nova ronda.")) if blockers and isinstance(blockers[0], dict) else "A data de mercado ja foi processada; nao houve nova ronda."
            supervision.append({"level": "info", "title": "Paper sem nova ronda", "detail": detail})
        elif entry_review.get("status") == "processed" and entry_count == 0:
            if near_entries:
                watched = ", ".join(
                    f"{item.get('symbol', '')} ({number(item.get('score')):.1f}; faltam {number(item.get('gap_to_buy')):.1f}; vigiar {', '.join(item.get('watch_factors', []))})"
                    for item in near_entries[:3]
                )
                detail = f"Nenhum sinal confirmou compra; {watched} fica em observação perto do limiar."
            else:
                detail = "Nenhum sinal confirmou compra no universo e snapshot atuais."
            supervision.append({"level": "info", "title": "Paper revisto sem entrada", "detail": detail})
    risk_control = paper.get("last_risk_control", {}) if isinstance(paper, dict) else {}
    if risk_control.get("active"):
        supervision.append({"level": "warning", "title": "Travão de drawdown ativo", "detail": str(risk_control.get("message", "Novas compras paper estão bloqueadas até a carteira recuperar."))})
    elif isinstance(paper, dict) and paper.get("paper_only") and not paper_progress:
        supervision.append({"level": "info", "title": "Paper trading sem progresso", "detail": "Ainda não existe um resumo de amostra. Executa o ledger paper depois de uma recolha válida."})
    ladder_progress = paper_ladder.get("review_progress", {}) if isinstance(paper_ladder, dict) else {}
    if isinstance(paper_ladder, dict) and paper_ladder:
        ladder_review = paper_ladder.get("last_entry_review", {}) if isinstance(paper_ladder.get("last_entry_review", {}), dict) else {}
        ladder_candidates = ladder_review.get("ladder_candidates", []) if isinstance(ladder_review.get("ladder_candidates", []), list) else []
        detail = f"{len(ladder_candidates)} candidato(s) elegível(eis) na última ronda; {int(paper_ladder.get('total_trades', 0) or 0)} operação(ões) no ledger separado."
        supervision.append({"level": "info", "title": "Escada de entradas paper ativa", "detail": detail})
    if isinstance(paper_matrix, dict) and paper_matrix:
        matrix_review = paper_matrix.get("last_entry_review", {}) if isinstance(paper_matrix.get("last_entry_review", {}), dict) else {}
        candidates = matrix_review.get("candidates", []) if isinstance(matrix_review.get("candidates", []), list) else []
        detail = f"{len(candidates)} célula(s) elegível(eis) na última ronda; {int(paper_matrix.get('total_trades', 0) or 0)} operação(ões) no ledger separado."
        supervision.append({"level": "info", "title": "Matriz score × prazo paper ativa", "detail": detail})
    if not positions:
        supervision.append({"level": "info", "title": "Inventário vazio", "detail": "Adiciona posições manualmente para acompanhar a tua carteira."})

    state_context = context_payload
    state_backtest = payload.get("backtest", {}) if isinstance(payload, dict) else {}
    if not include_heavy:
        state_context = {
            key: context_payload.get(key)
            for key in ("news_scores", "macro_score", "news_available", "macro_available")
            if key in context_payload
        }
        if isinstance(state_backtest, dict):
            state_backtest = {key: value for key, value in state_backtest.items() if key != "rows"}

    return {
        "meta": meta,
        "signals": signal_rows,
        "quality": quality_rows,
        "context": state_context,
        "backtest": state_backtest,
        "sector_summary": payload.get("sector_summary", []) if isinstance(payload, dict) else [],
        "universe": universe,
        "catalog": catalog,
        "portfolio": {"updated_at": portfolio.get("updated_at"), "positions": positions, "market_value": total_value, "market_value_currency": portfolio_currency, "valuation_approximate": portfolio_valuation_approximate, "valuation_note": "Valores normalizados para EUR com o câmbio implícito no extrato; posições sem preço live mantêm o valor EUR declarado.", "missing_valuation_count": missing_valuation_count, "sector_exposure": sector_exposure, "sector_exposure_approximate": portfolio_valuation_approximate, "sector_targets": sector_targets, "target_total": round(sum(sector_targets.values()), 6), "sector_drift": sector_drift, "correlation_pairs": correlation_pairs, "risk_contribution": risk_contribution.get("rows", []), "risk_observations": risk_contribution.get("observations", 0), "annualized_volatility": risk_contribution.get("annualized_volatility")},
        "portfolio_monitor": portfolio_monitor,
        "paper": paper,
        "paper_ladder": paper_ladder,
        "paper_matrix": paper_matrix,
        "automation": automation,
        "automation_history": automation_history,
        "artifact_status": artifact_status,
        "thresholds": config.get("thresholds", {}) if isinstance(config, dict) else {},
        "alerts": alerts,
        "signal_history": signal_history,
        "snapshot_comparison": compare_snapshots(signal_history),
        "outcomes": outcomes_payload,
        "cache_stats": cache_stats_payload,
        "network_usage": payload.get("network_usage", {}) if isinstance(payload, dict) else {},
        "network_plan": payload.get("network_plan", {}) if isinstance(payload, dict) else {},
        "quota": {"as_of": dt.datetime.now(dt.timezone.utc).date().isoformat(), "providers": quota_rows},
        "live_validation": live_validation,
        "supervision": supervision,
        "on_demand": on_demand,
        "journal": load_journal(),
        "report_library": report_library_entries(),
        "sensitivity": sensitivity_report_metadata(),
    }


def analyze(symbol: str) -> dict[str, Any] | None:
    state = load_state()
    wanted = symbol.strip().upper()
    for signal in state["signals"]:
        if str(signal.get("symbol", "")).upper() == wanted:
            quality = next((item for item in state["quality"] if str(item.get("symbol", "")).upper() == wanted), {})
            return {
                "signal": signal,
                "quality": quality,
                "context": state["context"],
                "backtest": state["backtest"],
                "meta": state["meta"],
                "note": "Resultado da última execução do radar; pedir uma nova recolha live continua a ser uma ação separada.",
            }
    return None


def live_analysis_plan(symbol: str) -> dict[str, Any]:
    """Describe the local cost and credential requirements before live analysis."""
    wanted = symbol.strip().upper()
    catalog = load_catalog()
    catalog_item = next((item for item in catalog if isinstance(item, dict) and str(item.get("symbol", "")).upper() == wanted), None)
    if not catalog_item:
        return {"ok": False, "error": "Ativo não encontrado no catálogo."}
    base_config = read_json(CONFIG_PATH, {})
    cache_config = base_config.get("cache", {}) if isinstance(base_config.get("cache", {}), dict) else {}
    ttl_by_namespace = cache_config.get("ttl_by_namespace", {}) if isinstance(cache_config.get("ttl_by_namespace", {}), dict) else {}
    provider = str(catalog_item.get("provider", "")).lower()
    ttl_seconds = number(ttl_by_namespace.get(provider, cache_config.get("ttl_seconds", 21600)), 21600)
    context_ttl_seconds = max(
        ttl_seconds,
        number(ttl_by_namespace.get("news", ttl_seconds), ttl_seconds),
        number(ttl_by_namespace.get("fred", ttl_seconds), ttl_seconds),
    )
    cached = read_json(ON_DEMAND_DIR / f"{wanted.lower()}.json", {})
    cached_age = age_hours(str(cached.get("fetched_at", ""))) if isinstance(cached, dict) else None
    cache_fresh = bool(isinstance(cached, dict) and cached.get("signal") and cached_age is not None and cached_age * 3600 < ttl_seconds)
    existing_payload = read_json(OUTPUT_DIR / "momentum_data.json", {})
    existing_meta = existing_payload.get("meta", {}) if isinstance(existing_payload, dict) else {}
    existing_context = existing_payload.get("context", {}) if isinstance(existing_payload, dict) else {}
    existing_age = age_hours(str(existing_meta.get("generated_at", "")))
    context_reused = bool(existing_meta.get("context_available", False)) and isinstance(existing_context, dict) and existing_age is not None and existing_age * 3600 < context_ttl_seconds
    cache_stats = read_json(ROOT / "data" / "cache" / "stats.json", {})
    cooldowns = cache_stats.get("cooldowns", {}) if isinstance(cache_stats, dict) else {}
    cooldown_item = cooldowns.get(provider, {}) if isinstance(cooldowns, dict) else {}
    cooldown_remaining = 0
    if isinstance(cooldown_item, dict):
        try:
            cooldown_remaining = max(0, int(dt.datetime.fromisoformat(str(cooldown_item.get("until", ""))).timestamp() - dt.datetime.now(dt.timezone.utc).timestamp()))
        except (TypeError, ValueError, OverflowError):
            cooldown_remaining = 0
    provider_cooldown = {"active": bool(cooldown_remaining), "remaining_seconds": cooldown_remaining, "reason": cooldown_item.get("reason", "") if isinstance(cooldown_item, dict) else ""}

    required: list[str] = []
    if provider == "alpha_vantage":
        required.append("ALPHAVANTAGE_API_KEY")
    if provider == "coinmarketcap":
        required.append("COINMARKETCAP_API_KEY")
    if "ALPHAVANTAGE_API_KEY" not in required:
        required.append("ALPHAVANTAGE_API_KEY")
    if not context_reused and str(base_config.get("macro", {}).get("provider", "")).lower() == "fred":
        required.append("FRED_API_KEY")
    required = list(dict.fromkeys(required))
    missing = [name for name in required if not os.environ.get(name, "").strip()]
    calls = []
    if not cache_fresh:
        calls.extend([{"provider": provider, "resource": "ativo selecionado"}, {"provider": "alpha_vantage", "resource": "benchmark GLOBAL"}])
        if not context_reused:
            news_provider = str(base_config.get("news", {}).get("provider", ""))
            calls.extend({"provider": news_provider, "resource": f"notícias {index + 1}"} for index in range(news_request_count(base_config)))
            calls.append({"provider": str(base_config.get("macro", {}).get("provider", "")), "resource": "ambiente económico"})
    if not cache_fresh and not context_reused:
        macro_provider = str(base_config.get("macro", {}).get("provider", ""))
        macro_series = base_config.get("macro", {}).get("series", []) if isinstance(base_config.get("macro", {}).get("series", []), list) else []
        if macro_provider and macro_series:
            calls = [item for item in calls if not (item.get("provider") == macro_provider and str(item.get("resource", "")).startswith("ambiente"))]
            for series in macro_series:
                series_id = str(series.get("id", "série")) if isinstance(series, dict) else "série"
                calls.append({"provider": macro_provider, "resource": f"macro {series_id}"})
    planned_providers = sorted({str(item.get("provider", "")).lower() for item in calls if str(item.get("provider", "")).strip()})
    provider_cooldowns: list[dict[str, Any]] = []
    for planned_provider in planned_providers:
        bucket = "alpha_vantage" if planned_provider in {"alpha_vantage", "news"} else planned_provider
        item = cooldowns.get(bucket, {}) if isinstance(cooldowns, dict) else {}
        if not isinstance(item, dict):
            continue
        try:
            remaining = max(0, int(dt.datetime.fromisoformat(str(item.get("until", ""))).timestamp() - dt.datetime.now(dt.timezone.utc).timestamp()))
        except (TypeError, ValueError, OverflowError):
            remaining = 0
        if remaining:
            provider_cooldowns.append({"provider": bucket, "remaining_seconds": remaining, "reason": item.get("reason", "")})
    provider_cooldown = {
        "active": bool(provider_cooldowns),
        "remaining_seconds": max((item["remaining_seconds"] for item in provider_cooldowns), default=0),
        "reason": provider_cooldowns[0].get("reason", "") if provider_cooldowns else "",
    }
    budget_rows = daily_budget_rows(base_config, cache_stats if isinstance(cache_stats, dict) else {}, calls)
    budget_blocked = any(item.get("shortfall", 0) > 0 for item in budget_rows)
    budget_message = ""
    if budget_blocked:
        blocked = ", ".join(f"{item['provider']} precisa de mais {item['shortfall']} chamada(s)" for item in budget_rows if item.get("shortfall", 0) > 0)
        budget_message = f"Orçamento diário local insuficiente: {blocked}. Não será feita nenhuma chamada."
    return {
        "ok": True,
        "symbol": wanted,
        "provider": provider,
        "cache": {"status": "fresh" if cache_fresh else "missing_or_stale", "age_seconds": round(cached_age * 3600) if cached_age is not None else None, "ttl_seconds": ttl_seconds},
        "context": {"status": "reused" if context_reused else "will_refresh", "age_seconds": round(existing_age * 3600) if existing_age is not None else None, "ttl_seconds": context_ttl_seconds},
        "provider_cooldown": provider_cooldown,
        "provider_cooldowns": provider_cooldowns,
        "daily_budgets": budget_rows,
        "budget_blocked": budget_blocked,
        "budget_message": budget_message,
        "keys": [{"name": name, "configured": name not in missing} for name in required],
        "missing_keys": missing,
        "estimated_calls": len(calls),
        "calls": calls,
        "message": f"Provider em cooldown local por mais {cooldown_remaining}s após rate limit; aguarda antes de repetir." if cooldown_remaining else ("Cache fresco: nenhuma chamada externa prevista." if cache_fresh else f"Até {len(calls)} chamadas externas previstas; o contexto {'será reutilizado' if context_reused else 'será recolhido'}."),
    }


def collect_live_analysis(symbol: str) -> dict[str, Any]:
    """Spend provider quota only for an explicitly selected catalog asset.

    The radar still fetches GLOBAL plus macro/news context because an isolated
    asset price is not enough for a responsible signal. Results are cached in
    ``data/on_demand`` for the configured cache TTL.
    """
    wanted = symbol.strip().upper()
    catalog = load_catalog()
    catalog_item = next((item for item in catalog if isinstance(item, dict) and str(item.get("symbol", "")).upper() == wanted), None)
    if not catalog_item:
        return {"ok": False, "error": "Ativo não encontrado no catálogo."}
    cache_path = ON_DEMAND_DIR / f"{wanted.lower()}.json"
    cached = read_json(cache_path, {})
    base_config = read_json(CONFIG_PATH, {})
    cache_config = base_config.get("cache", {}) if isinstance(base_config.get("cache", {}), dict) else {}
    ttl_by_namespace = cache_config.get("ttl_by_namespace", {}) if isinstance(cache_config.get("ttl_by_namespace", {}), dict) else {}
    provider = str(catalog_item.get("provider", "")).lower()
    ttl_seconds = number(ttl_by_namespace.get(provider, cache_config.get("ttl_seconds", 21600)), 21600)
    context_ttl_seconds = max(
        ttl_seconds,
        number(ttl_by_namespace.get("news", ttl_seconds), ttl_seconds),
        number(ttl_by_namespace.get("fred", ttl_seconds), ttl_seconds),
    )
    cached_age = age_hours(str(cached.get("fetched_at", "")))
    if isinstance(cached, dict) and cached.get("signal") and cached_age is not None and cached_age * 3600 < ttl_seconds:
        cached["cached"] = True
        cached["usage_details"] = {"provider": provider, "ttl_seconds": ttl_seconds, "cache_age_seconds": round(cached_age * 3600), "context_reused": True}
        cached["usage"] = {"mode": "cache", "message": "Nenhuma chamada nova: foi usado o resultado em cache."}
        return cached

    existing_payload = read_json(OUTPUT_DIR / "momentum_data.json", {})
    existing_meta = existing_payload.get("meta", {}) if isinstance(existing_payload, dict) else {}
    existing_context = existing_payload.get("context", {}) if isinstance(existing_payload, dict) else {}
    existing_age = age_hours(str(existing_meta.get("generated_at", "")))
    reuse_context = bool(existing_meta.get("context_available", False)) and isinstance(existing_context, dict) and existing_age is not None and existing_age * 3600 < context_ttl_seconds

    required = []
    if provider == "alpha_vantage":
        required.append("ALPHAVANTAGE_API_KEY")
    if provider == "coinmarketcap":
        required.append("COINMARKETCAP_API_KEY")
    if "ALPHAVANTAGE_API_KEY" not in required:
        required.append("ALPHAVANTAGE_API_KEY")
    if not reuse_context and str(base_config.get("macro", {}).get("provider", "")).lower() == "fred":
        required.append("FRED_API_KEY")
    missing = [name for name in required if not os.environ.get(name, "").strip()]
    if missing:
        return {"ok": False, "error": f"Para análise live faltam: {', '.join(missing)}. O catálogo continua sem gastar quota."}
    plan = live_analysis_plan(wanted)
    if plan.get("budget_blocked"):
        return {"ok": False, "error": plan.get("budget_message") or "Orçamento diário local insuficiente; não foi feita nenhuma chamada."}

    try:
        from src.momentum_tool import fetch_live_data, guard_signals, latest_signals, load_config, quality_rows

        config = load_config(CONFIG_PATH)
        config["universe"] = [catalog_item]
        config.setdefault("news", {})["query_tickers"] = [str(catalog_item.get("news_ticker") or catalog_item.get("source_id") or wanted)]
        if reuse_context:
            config["news"]["provider"] = ""
            config["macro"]["provider"] = ""
        rows, provider_quality, context = fetch_live_data(config)
        if reuse_context:
            context = existing_context
        if not rows:
            return {"ok": False, "error": "A fonte não devolveu dados para este ativo."}
        signals = latest_signals(rows, config, context)
        benchmark_available = any(row.get("symbol") == "GLOBAL" for row in rows)
        context_available = bool(context.get("news_available")) and bool(context.get("macro_available"))
        signals = guard_signals(signals, "live", benchmark_available, context_available)
        signal = next((item for item in signals if str(item.get("symbol", "")).upper() == wanted), None)
        if not signal:
            return {"ok": False, "error": "A fonte respondeu, mas não foi possível calcular o sinal."}
        latest_date = max(str(row.get("date", "")) for row in rows)
        quality = next((item for item in quality_rows(rows, config, provider_quality) if str(item.get("symbol", "")).upper() == wanted), {})
        signal["horizons"] = horizon_views(signal, context)
        fetched_at = dt.datetime.now(dt.timezone.utc).isoformat()
        result = {
            "ok": True,
            "signal": signal,
            "quality": quality,
            "context": context,
            "meta": {"as_of": latest_date, "generated_at": fetched_at, "mode": "live", "currency": config.get("currency", "USD"), "benchmark_available": benchmark_available, "context_available": context_available},
            "fetched_at": fetched_at,
            "cached": False,
            "usage_details": {"provider": provider, "ttl_seconds": ttl_seconds, "context_ttl_seconds": context_ttl_seconds, "context_reused": reuse_context},
            "usage": {"mode": "on_demand_cached_context" if reuse_context else "on_demand", "message": "Foi recolhido o ativo selecionado; o contexto existente foi reutilizado." if reuse_context else "Foi recolhido o ativo selecionado com benchmark e contexto macro/notícias."},
        }
        write_json(cache_path, result)
        return result
    except Exception as exc:  # noqa: BLE001 - UI must receive a safe actionable error
        return {"ok": False, "error": f"Falha na análise live: {safe_error_message(exc)}"}


def markdown_report(symbol: str) -> tuple[str, str] | None:
    """Build a human-readable report for one catalog asset.

    Reports are snapshots only. They never trigger a provider call or a trade.
    """
    state = load_state()
    wanted = symbol.strip().upper()
    catalog_item = next((item for item in state["catalog"] if str(item.get("symbol", "")).upper() == wanted), None)
    if not catalog_item:
        return None
    signal = next((item for item in state["signals"] if str(item.get("symbol", "")).upper() == wanted), None)
    quality = next((item for item in state["quality"] if str(item.get("symbol", "")).upper() == wanted), None)
    position = next((item for item in state.get("portfolio", {}).get("positions", []) if str(item.get("symbol", "")).upper() == wanted), None)
    journal_note = next((item.get("note", "") for item in state.get("journal", []) if str(item.get("symbol", "")).upper() == wanted and str(item.get("as_of", "")) == str(state.get("meta", {}).get("as_of", ""))), "")
    meta = state.get("meta", {})
    lines = [
        f"# Relatório de {wanted}",
        "",
        f"**Nome:** {catalog_item.get('name', wanted)}  ",
        f"**Tipo:** {catalog_item.get('type', 'Ativo')}  ",
        f"**Setor:** {catalog_item.get('sector', '—')}  ",
        f"**Snapshot:** {meta.get('as_of', '—')} · modo {meta.get('mode', '—')}  ",
        "",
        "> [!warning] Uso responsável",
        "> Este documento organiza informação e não é uma ordem de compra ou venda. Confirma os dados, os custos e o teu risco antes de agir.",
        "",
    ]
    lines.extend([commentary_markdown([(wanted, action_commentary(catalog_item, signal, quality, meta, position))]), ""])
    if journal_note:
        lines.extend(["## Nota pessoal", "", f"> {journal_note}", ""])
    if signal:
        score_value = number(signal.get("score"))
        confidence_value = number(signal.get("confidence"))
        risk_value = number(signal.get("risk_penalty"))
        drawdown_value = number(signal.get("drawdown"))
        score_reading = metric_reading("score", score_value)
        confidence_reading = metric_reading("confidence", confidence_value)
        risk_reading = metric_reading("risk_penalty", risk_value)
        drawdown_reading = metric_reading("drawdown", drawdown_value)
        asset_outcomes = state.get("outcomes", {}).get("summary", {}).get("by_symbol", {}).get(wanted, {})
        lines.extend([
            "## Leitura do radar",
            "",
            f"- **Ação do modelo:** {signal.get('action', 'Sem ação')}",
            f"- **Pontuação:** {score_value:.1f}/100 - {score_reading['level']} ({score_reading['band']}). {score_reading['meaning']}",
            f"- **Confiança:** {confidence_value:.1f}/100 - {confidence_reading['level']} ({confidence_reading['band']}). {confidence_reading['meaning']}",
            f"- **Preço no snapshot:** {number(signal.get('price')):.6g} {meta.get('currency', 'USD')}",
            f"- **Risco penalizado:** {risk_value:.1f}/30 - {risk_reading['level']} ({risk_reading['band']}). {risk_reading['meaning']}",
            f"- **Drawdown:** {drawdown_value:.1%} - {drawdown_reading['level']} ({drawdown_reading['band']}). {drawdown_reading['meaning']}",
            "",
            f"**Explicação:** {signal.get('notes', 'O radar não deixou uma explicação adicional.')}",
            "",
        ])
        horizon_payload = signal.get("horizons", {})
        if isinstance(horizon_payload, dict) and any(isinstance(horizon_payload.get(key), dict) for key in ("short", "medium", "long")):
            lines.extend([
                "## Horizontes de decisão",
                "",
                "| Prazo | Ação | Score | Foco |",
                "|---|---|---:|---|",
            ])
            for key in ("short", "medium", "long"):
                horizon = horizon_payload.get(key, {})
                if not isinstance(horizon, dict):
                    continue
                lines.append(f"| {horizon.get('label', key)} | {horizon.get('action', 'Sem leitura')} | {number(horizon.get('score')):.1f} | {horizon.get('focus', 'contexto indisponível')} |")
            lines.append("")
        lines.extend([
            "### Fatores",
            "",
            "| Fator | Valor | Leitura para este ativo |",
            "|---|---:|---|",
        ])
        for key in ("momentum", "relative_strength", "trend", "breadth", "volume", "news", "macro"):
            value = number(signal.get(key))
            reading = personalized_metric_reading(key, value, catalog_item, signal, state.get("context", {}))
            lines.append(f"| {reading['display_name']} | {value:.1f}/100 | **{reading['level']}** ({reading['band']}): {reading['personalized_meaning']} {reading['action']} |")
        if asset_outcomes:
            lines.extend([
                "",
                "## Evidência histórica deste ativo",
                "",
                "Esta tabela resume apenas os outcomes fechados anteriormente para este símbolo no mesmo modo; descreve o passado e não prevê o próximo movimento.",
                "",
                "| Janela | Registos | Retorno positivo | Média | Mediana |",
                "|---:|---:|---:|---:|---:|",
            ])
            for horizon, outcome in asset_outcomes.items():
                positive = "—" if outcome.get("positive_rate") is None else f"{outcome['positive_rate']:.1%}"
                average = "—" if outcome.get("average_return") is None else f"{outcome['average_return']:.2%}"
                median = "—" if outcome.get("median_return") is None else f"{outcome['median_return']:.2%}"
                lines.append(f"| {horizon} observações | {outcome.get('records', 0)} | {positive} | {average} | {median} |")
        lines.extend(["", "## O que isto significa para a tua compra", ""])
        if position:
            cost = position.get("acquisition_analysis", acquisition_analysis(position.get("avg_cost"), signal.get("price"), signal.get("action"), catalog_item.get("name", wanted), position.get("currency", "")))
            if cost.get("available"):
                lines.extend([
                    f"- **Preço médio de compra:** {number(position.get('avg_cost')):.6g} {position.get('currency', meta.get('currency', 'USD'))}",
                    f"- **Variação por unidade:** {number(cost.get('pnl_pct')):.1%} ({cost.get('level')}; faixa {cost.get('band')})",
                    f"- **Leitura:** {cost.get('meaning')}",
                    f"- **Como cruzar com o radar:** {cost.get('action')}",
                ])
            else:
                lines.append(f"- **Preço de compra:** {cost.get('meaning')} {cost.get('action')}")
        else:
            lines.append("Este ativo não está no teu inventário; por isso não há preço de aquisição para comparar.")
    else:
        lines.extend([
            "## Estado da análise",
            "",
            "**Sem dados no snapshot atual.** Este ativo existe no catálogo, mas ainda não está no universo configurado ou não respondeu na última recolha.",
            "",
            "Não agir com base neste relatório. Adiciona o ativo à configuração, valida a fonte e executa uma nova recolha live antes de interpretar sinais.",
        ])
    lines.extend([
        "",
        "## Guia de leitura",
        "",
        "Esta é a legenda dos números do radar. Uma pontuação alta junta sinais favoráveis; não é uma probabilidade de lucro.",
        "",
        "| Parâmetro | Em linguagem simples |",
        "|---|---|",
        "| Pontuação / score | Nota de 0 a 100 que combina os fatores. Mostra alinhamento de sinais, não garante retorno. |",
        "| Confiança | Consistência entre os fatores e quantidade de histórico disponível. Não elimina surpresas. |",
        "| Risco penalizado | Penalização de 0 a 30 por instabilidade e quedas. Quanto maior, mais cautela pede. |",
        "| Drawdown | Queda desde o último pico. 20% significa estar 20% abaixo do máximo recente. |",
        "| Momentum | Impulso recente do preço e se o movimento está a ganhar ou perder força. |",
        "| Comparação com o mercado | Compara o ativo com um grupo de referência; subir menos do que esse grupo ainda é ficar para trás. |",
        "| Direção do preço | Mostra se o preço está a construir uma direção consistente; não prevê o próximo preço. |",
        "| Atividade de negociação | Compara a quantidade negociada com o normal do próprio ativo. Volume alto pode ser interesse ou vendas nervosas; sozinho não distingue os dois. |",
        "| Clima das notícias | Resume se as notícias recentes ligadas ao ativo são negativas, neutras ou positivas. Uma manchete não prevê o futuro. |",
        "| Ambiente económico | Resume se o contexto de inflação, juros e moeda ajuda ou dificulta este tipo de ativo. |",
        "| Mercado de comparação | Referência usada para perceber se este ativo está melhor ou pior do que o mercado. |",
        "| CAGR / Sharpe | Medidas do backtest histórico: crescimento anual equivalente e retorno face à variação. Não são previsão. |",
        "",
        "## Contexto e qualidade",
        "",
        f"- Mercado de comparação disponível: {'sim' if meta.get('benchmark_available') else 'não'}",
        f"- Notícias e ambiente económico disponíveis: {'sim' if meta.get('context_available') else 'não'}",
        f"- Pontuação do ambiente económico: {number(state.get('context', {}).get('macro_score', meta.get('macro_score', 50))):.1f}/100",
        f"- Qualidade de {wanted}: {quality.get('status', 'Sem dados') if quality else 'Sem dados'}",
    ])
    recent_alerts = [item for item in state.get("alerts", []) if str(item.get("symbol", "")).upper() == wanted]
    if recent_alerts:
        lines.extend(["", "## Mudanças desde a leitura anterior", ""])
        for event in recent_alerts[:5]:
            transition = f"{event.get('from_action', '—')} → {event.get('to_action', '—')}"
            reason = event.get("reason") or "mudança registada no snapshot"
            lines.append(f"- **{transition}:** {reason}")
    else:
        lines.extend(["", "## Mudanças desde a leitura anterior", "", "Não há uma transição registada para este ativo no snapshot atual."])
    if quality and quality.get("message"):
        lines.append(f"- Nota da fonte: {quality.get('message')}")
    lines.extend([
        "",
        "## Nota técnica",
        "",
        "O relatório usa apenas o último snapshot local. Exportar este ficheiro não atualiza APIs, não altera o inventário e não envia ordens.",
        "",
        "Fontes configuradas: Alpha Vantage, CoinMarketCap e FRED.",
    ])
    return f"radar-{wanted.lower()}-relatorio.md", "\n".join(lines) + "\n"


def portfolio_report_highlights(state: dict[str, Any]) -> tuple[float, list[dict[str, Any]], list[dict[str, Any]]]:
    """Return only sector and portfolio highlights at the configured score threshold."""
    thresholds = state.get("thresholds", {}) if isinstance(state.get("thresholds", {}), dict) else {}
    threshold = max(0.0, min(100.0, number(thresholds.get("buy_score"), 80.0)))
    portfolio = state.get("portfolio", {}) if isinstance(state.get("portfolio", {}), dict) else {}
    positions = portfolio.get("positions", []) if isinstance(portfolio.get("positions", []), list) else []
    position_by_sector: dict[str, int] = {}
    standout_positions: list[dict[str, Any]] = []
    for position in positions:
        if not isinstance(position, dict):
            continue
        score_value = position.get("score")
        if score_value is not None and number(score_value, -1.0) >= threshold:
            standout_positions.append(position)
        sector = str(position.get("sector") or "Fora do radar")
        position_by_sector[sector] = position_by_sector.get(sector, 0) + 1

    raw_sectors = state.get("sector_summary", []) if isinstance(state.get("sector_summary", []), list) else []
    standout_sectors: list[dict[str, Any]] = []
    for raw in raw_sectors:
        if not isinstance(raw, dict) or raw.get("average_score") is None:
            continue
        average_score = number(raw.get("average_score"), -1.0)
        if average_score < threshold:
            continue
        item = dict(raw)
        item["portfolio_count"] = position_by_sector.get(str(raw.get("sector") or "Sem setor"), 0)
        standout_sectors.append(item)
    standout_sectors.sort(key=lambda item: number(item.get("average_score")), reverse=True)
    standout_positions.sort(key=lambda item: number(item.get("score")), reverse=True)
    return threshold, standout_sectors, standout_positions


def portfolio_report_highlight_lines(threshold: float, sectors: list[dict[str, Any]], positions: list[dict[str, Any]]) -> list[str]:
    """Format the focused portfolio/sector summary before the detailed tables."""
    lines = [
        "## Foco: carteira e setores em destaque",
        "",
        f"Este resumo destaca apenas setores com score medio >= {threshold:.0f}/100 e posicoes da carteira com score >= {threshold:.0f}/100. O filtro e informativo; nao e uma ordem nem uma garantia.",
        "",
        "### Setores em destaque",
        "",
    ]
    if sectors:
        lines.extend(["| Setor | Score medio | Ativos com leitura | Compras | Na carteira |", "|---|---:|---:|---:|---:|"])
        for item in sectors:
            lines.append(f"| {item.get('sector', 'Sem setor')} | {number(item.get('average_score')):.1f} | {int(number(item.get('signals'), 0))} | {int(number(item.get('buy_signals'), 0))} | {int(number(item.get('portfolio_count'), 0))} |")
    else:
        lines.append(f"Nenhum setor atingiu {threshold:.0f}/100 neste snapshot.")
    lines.extend(["", "### Posicoes da carteira que atingiram o limiar", ""])
    if positions:
        lines.extend(["| Ativo | Setor | Score | Sinal | Peso |", "|---|---|---:|---|---:|"])
        for item in positions:
            lines.append(f"| {item.get('symbol', '-')} | {item.get('sector', 'Fora do radar')} | {number(item.get('score')):.1f} | {item.get('action', 'Sem analise')} | {number(item.get('weight')):.1%} |")
    else:
        lines.append(f"Nenhuma posicao da carteira atingiu {threshold:.0f}/100 neste snapshot.")
    return lines


def portfolio_markdown_report() -> tuple[str, str]:
    """Build a local portfolio report without refreshing any provider."""
    state = load_state()
    portfolio = state.get("portfolio", {})
    positions = portfolio.get("positions", []) if isinstance(portfolio, dict) else []
    meta = state.get("meta", {})
    highlight_threshold, standout_sectors, standout_positions = portfolio_report_highlights(state)
    highlight_lines = portfolio_report_highlight_lines(highlight_threshold, standout_sectors, standout_positions)
    lines = [
        "# Relatório local da carteira",
        "",
        f"**Snapshot:** {meta.get('as_of', '—')} · modo {meta.get('mode', '—')}  ",
        f"**Valor acompanhado:** {portfolio.get('market_value', 0):.2f} {portfolio.get('market_value_currency', meta.get('currency', 'USD'))}  ",
        f"**Posições:** {len(positions)}  ",
        "",
        "> [!warning] Uso responsável",
        "> Este relatório é uma fotografia do inventário local. Não prevê retornos, não substitui a confirmação na corretora e não envia ordens.",
        "",
        *highlight_lines,
        "",
        "## Posições",
        "",
        "| Ativo | Setor | Valor atual | Peso | Resultado vs. compra | Sinal | Qualidade |",
        "|---|---|---:|---:|---:|---|---|",
    ]
    if not positions:
        lines.append("| — | — | — | — | — | inventário vazio | — |")
    else:
        for position in positions:
            pnl = position.get("pnl_pct")
            pnl_text = "—" if pnl is None else f"{number(pnl):.1%}"
            lines.append(f"| {position.get('symbol', '—')} | {position.get('sector', 'Fora do radar')} | {number(position.get('market_value')):.2f} {position.get('market_value_currency', '')} | {number(position.get('weight')):.1%} | {pnl_text} | {position.get('action', 'Sem análise')} | {position.get('data_status', 'Sem dados')} |")
    lines.extend(["", commentary_markdown(commentary_entries(state, portfolio_only=True)), ""])
    lines.extend(["", "## Exposição por setor", "", "| Setor | Valor | Peso |", "|---|---:|---:|"])
    for item in portfolio.get("sector_exposure", []):
        lines.append(f"| {item.get('sector', 'Sem setor')} | {number(item.get('market_value')):.2f} | {number(item.get('weight')):.1%} |")
    if not portfolio.get("sector_exposure"):
        lines.append("| — | — | — |")
    drift_rows = portfolio.get("sector_drift", [])
    lines.extend(["", "## Desvio face às metas", "", "As metas são opcionais e locais; o desvio não gera ordens. Valores positivos significam excesso face à meta.", ""])
    if drift_rows and any(item.get("target") is not None for item in drift_rows):
        lines.extend(["| Setor | Atual | Meta | Desvio | Ajuste indicativo | Estado |", "|---|---:|---:|---:|---:|---|"])
        for item in drift_rows:
            if item.get("target") is None:
                continue
            gap = number(item.get("value_gap"))
            currency = str(portfolio.get("market_value_currency") or meta.get("currency", "USD"))
            gap_text = f"{'reduzir' if gap > 0 else 'aumentar'} {abs(gap):.2f} {currency}"
            if currency == "MIX":
                gap_text = f"{'reduzir' if gap > 0 else 'aumentar'} {abs(gap):.2f} aprox."
            lines.append(f"| {item.get('sector', '—')} | {number(item.get('actual')):.1%} | {number(item.get('target')):.1%} | {number(item.get('drift')):+.1%} | {gap_text} | {item.get('status', '—')} |")
        lines.append(f"\n**Total de metas guardadas:** {number(portfolio.get('target_total')):.1%}.")
    else:
        lines.append("Não há metas de setor guardadas neste computador.")
    risk_rows = portfolio.get("risk_contribution", [])
    lines.extend(["", "## Contribuição para variabilidade", "", "Estimativa local por covariância dos retornos disponíveis. Não é previsão, stress test ou look-through dos componentes de ETFs.", ""])
    if risk_rows:
        lines.extend(["| Ativo | Peso | Contribuição estimada | Observações |", "|---|---:|---:|---:|"])
        for item in risk_rows:
            lines.append(f"| {item.get('symbol', '—')} | {number(item.get('weight')):.1%} | {number(item.get('contribution_pct')):+.1%} | {item.get('observations', 0)} |")
        annualized = portfolio.get("annualized_volatility")
        if annualized is not None:
            lines.append(f"\n**Volatilidade anualizada aproximada:** {number(annualized):.1%}.")
    else:
        lines.append("Ainda não há 20 observações comuns entre as posições para calcular esta estimativa. A ausência de cobertura não é tratada como risco zero.")
    correlations = portfolio.get("correlation_pairs", [])
    lines.extend(["", "## Correlações elevadas", ""])
    if correlations:
        lines.extend(["| Par | Correlação | Observações |", "|---|---:|---:|"])
        for item in correlations:
            lines.append(f"| {item.get('left', '—')} · {item.get('right', '—')} | {number(item.get('correlation')):.2f} | {item.get('observations', 0)} |")
    else:
        lines.append("Não há pares com correlação elevada e cobertura suficiente no snapshot local.")
    monitor = state.get("portfolio_monitor", {}) if isinstance(state.get("portfolio_monitor", {}), dict) else {}
    selected_symbols = [str(value) for value in monitor.get("selected_symbols", []) if str(value)]
    next_symbols = [str(value) for value in monitor.get("next_symbols", []) if str(value)]
    lines.extend([
        "",
        "## Cobertura de monitorização",
        "",
        f"- Posições no inventário: {int(monitor.get('position_count', len(positions)) or 0)}",
        f"- Limite por ronda live: {int(monitor.get('max_assets_per_run', 0) or 0)}",
        f"- Reserva operacional: {int(monitor.get('reserve_calls', 0) or 0)} chamadas",
        f"- Selecionadas no último snapshot: {', '.join(selected_symbols) if selected_symbols else 'nenhuma'}",
        f"- Próxima prioridade local: {', '.join(next_symbols) if next_symbols else 'nenhuma elegível'}",
        "",
        "A fila prioriza posições sem leitura e depois os dados mais antigos; o valor da posição serve apenas de desempate. Esta secção não atualiza providers nem cria ordens.",
        "",
        "## Quota e qualidade",
        "",
        f"- Contexto macro/notícias disponível: {'sim' if meta.get('context_available') else 'não'}",
        f"- Mercado de comparação disponível: {'sim' if meta.get('benchmark_available') else 'não'}",
    ])
    for item in state.get("quota", {}).get("providers", []):
        remaining = "sem limite" if item.get("remaining") is None else str(item.get("remaining"))
        lines.append(f"- {item.get('provider', 'provider')}: {remaining} chamadas restantes hoje")
    network_usage = state.get("network_usage", {}) if isinstance(state.get("network_usage", {}), dict) else {}
    lines.extend(["", "### Última execução", f"- Chamadas externas efetivamente tentadas: {int(network_usage.get('outbound_calls', 0))}"])
    lines.extend(["", "## Nota técnica", "", "Este relatório é gerado a partir do snapshot e dos ficheiros locais do Radar. Exportá-lo não faz chamadas externas, não altera a carteira e não guarda chaves de API."])
    return "radar-carteira-relatorio.md", "\n".join(lines) + "\n"


def portfolio_pdf_report() -> tuple[str, bytes]:
    """Build the focused portfolio PDF from local state without provider calls."""
    from src.pdf_report import build_portfolio_pdf

    state = load_state()
    as_of = str(state.get("meta", {}).get("as_of", "snapshot"))
    return f"radar-carteira-{as_of}.pdf", build_portfolio_pdf(state)


def pdf_report(symbol: str) -> tuple[str, bytes] | None:
    state = load_state()
    wanted = symbol.strip().upper()
    catalog_item = next((item for item in state["catalog"] if str(item.get("symbol", "")).upper() == wanted), None)
    if not catalog_item:
        return None
    signal = next((item for item in state["signals"] if str(item.get("symbol", "")).upper() == wanted), None)
    quality = next((item for item in state["quality"] if str(item.get("symbol", "")).upper() == wanted), {})
    position = next((item for item in state.get("portfolio", {}).get("positions", []) if str(item.get("symbol", "")).upper() == wanted), None)
    journal_note = next((item.get("note", "") for item in state.get("journal", []) if str(item.get("symbol", "")).upper() == wanted and str(item.get("as_of", "")) == str(state.get("meta", {}).get("as_of", ""))), "")
    from src.pdf_report import build_asset_pdf

    asset_outcomes = state.get("outcomes", {}).get("summary", {}).get("by_symbol", {}).get(wanted, {})
    recent_alerts = [item for item in state.get("alerts", []) if str(item.get("symbol", "")).upper() == wanted]
    content = build_asset_pdf(catalog_item, signal, quality, state.get("meta", {}), state.get("context", {}), position=position, journal_note=journal_note, outcome_summary=asset_outcomes, alert_events=recent_alerts)
    return f"radar-{wanted.lower()}-relatorio.pdf", content


def daily_pdf_report() -> tuple[str, bytes] | None:
    """Build the full daily snapshot PDF without refreshing any provider."""
    payload = read_json(OUTPUT_DIR / "momentum_data.json", {})
    if not isinstance(payload, dict) or not payload.get("signals"):
        return None
    from src.pdf_report import build_daily_pdf

    as_of = str(payload.get("meta", {}).get("as_of", "snapshot"))
    return f"radar-diario-{as_of}.pdf", build_daily_pdf(payload)


def report_library_entries() -> list[dict[str, Any]]:
    """List dated local report copies without reading or contacting providers."""
    report_dir = OUTPUT_DIR / "reports"
    if not report_dir.is_dir():
        return []
    entries: list[dict[str, Any]] = []
    for markdown_path in sorted(report_dir.glob("radar-diario-*.md"), reverse=True):
        match = re.fullmatch(r"radar-diario-(\d{4}-\d{2}-\d{2})\.md", markdown_path.name)
        if not match or not markdown_path.is_file():
            continue
        as_of = match.group(1)
        pdf_path = report_dir / f"radar-diario-{as_of}.pdf"
        entries.append({
            "as_of": as_of,
            "markdown": f"/api/report-archive?file={markdown_path.name}",
            "pdf": f"/api/report-archive?file={pdf_path.name}" if pdf_path.is_file() else None,
            "updated_at": dt.datetime.fromtimestamp(markdown_path.stat().st_mtime, dt.timezone.utc).isoformat(),
            "markdown_bytes": markdown_path.stat().st_size,
            "pdf_bytes": pdf_path.stat().st_size if pdf_path.is_file() else 0,
        })
    return entries[:24]


def parse_body(handler: BaseHTTPRequestHandler) -> dict[str, Any]:
    try:
        length = min(int(handler.headers.get("Content-Length", "0")), 1_000_000)
        raw = handler.rfile.read(length)
        value = json.loads(raw.decode("utf-8")) if raw else {}
        return value if isinstance(value, dict) else {}
    except (ValueError, UnicodeDecodeError, json.JSONDecodeError):
        return {}


class DashboardHandler(BaseHTTPRequestHandler):
    server_version = "RadarUI/0.1"

    def _session(self):
        return session_for(parse_cookie(self.headers.get("Cookie")))

    def _client_address(self) -> str:
        return str(self.client_address[0]) if self.client_address else "unknown"

    def send_redirect(self, location: str) -> None:
        self.send_response(HTTPStatus.SEE_OTHER)
        self.send_header("Location", location)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "close")
        self.end_headers()

    def send_login_page(self) -> None:
        page = UI_DIR / "login.html"
        if not page.is_file():
            self.send_error(HTTPStatus.INTERNAL_SERVER_ERROR)
            return
        data = page.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "close")
        self.end_headers()
        self.send_bytes(data)

    def require_auth(self, api: bool = True) -> bool:
        if self._session() is not None:
            return True
        if api:
            self.send_json({"error": "É necessário iniciar sessão.", "authenticated": False}, HTTPStatus.UNAUTHORIZED)
        else:
            next_path = urlparse(self.path).path or "/"
            self.send_redirect(f"/login?next={next_path}")
        return False

    def send_bytes(self, data: bytes) -> None:
        """Write a complete response body in small chunks for Windows clients."""
        # Writing directly to ``connection`` bypasses the stream lifecycle used
        # by BaseHTTPRequestHandler. On Windows that can produce a 200 response
        # followed by a connection reset while the browser is still reading a
        # large JSON body. The handler stream already handles partial writes.
        chunk_size = 16 * 1024
        for offset in range(0, len(data), chunk_size):
            self.wfile.write(data[offset:offset + chunk_size])
            self.wfile.flush()

    def send_json(self, payload: Any, status: HTTPStatus = HTTPStatus.OK) -> None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "same-origin")
        self.send_header("Connection", "close")
        self.end_headers()
        self.send_bytes(data)

    def send_session_cookie(self, token: str, expires: int) -> None:
        secure = "; Secure" if self.headers.get("X-Forwarded-Proto", "").lower() == "https" else ""
        self.send_header(
            "Set-Cookie",
            f"{SESSION_COOKIE}={token}; Path=/; Max-Age={max(0, expires - int(time.time()))}; HttpOnly; SameSite=Lax{secure}",
        )

    def clear_session_cookie(self) -> None:
        self.send_header("Set-Cookie", f"{SESSION_COOKIE}=; Path=/; Max-Age=0; HttpOnly; SameSite=Lax")

    def send_markdown(self, filename: str, content: str) -> None:
        data = content.encode("utf-8")
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/markdown; charset=utf-8")
        self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Connection", "close")
        self.end_headers()
        self.send_bytes(data)

    def send_pdf(self, filename: str, content: bytes) -> None:
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "application/pdf")
        self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
        self.send_header("Content-Length", str(len(content)))
        self.send_header("Connection", "close")
        self.end_headers()
        self.send_bytes(content)

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path == "/healthz":
            self.send_json({"ok": True, "service": "momentum-radar"})
            return
        if parsed.path == "/login":
            if self._session() is not None:
                self.send_redirect("/")
                return
            self.send_login_page()
            return
        if parsed.path == "/login.css":
            candidate = (UI_DIR / "login.css").resolve()
            if not candidate.is_file():
                self.send_error(HTTPStatus.NOT_FOUND)
                return
            data = candidate.read_bytes()
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/css; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.send_bytes(data)
            return
        if parsed.path == "/api/session":
            session = self._session()
            self.send_json({
                "authenticated": session is not None,
                "username": session.username if session else None,
                "setup_required": setup_required(),
                "auth_disabled": auth_disabled(),
            })
            return
        if not self.require_auth(api=parsed.path.startswith("/api/")):
            return
        if parsed.path == "/api/state":
            self.send_json(load_state(include_heavy=False))
            return
        if parsed.path == "/api/live-plan":
            query = parse_qs(parsed.query)
            plan = live_analysis_plan(query.get("symbol", [""])[0])
            self.send_json(plan, HTTPStatus.OK if plan.get("ok") else HTTPStatus.NOT_FOUND)
            return
        if parsed.path == "/api/analyze":
            query = parse_qs(parsed.query)
            result = analyze(query.get("symbol", [""])[0])
            self.send_json(result or {"error": "Ativo sem sinal no snapshot atual."}, HTTPStatus.OK if result else HTTPStatus.NOT_FOUND)
            return
        if parsed.path == "/api/report":
            query = parse_qs(parsed.query)
            symbol = query.get("symbol", [""])[0]
            if query.get("format", ["pdf"])[0].lower() == "pdf":
                report = pdf_report(symbol)
                if not report:
                    self.send_json({"error": "Ativo não encontrado no catálogo."}, HTTPStatus.NOT_FOUND)
                    return
                self.send_pdf(*report)
                return
            report = markdown_report(symbol)
            if not report:
                self.send_json({"error": "Ativo não encontrado no catálogo."}, HTTPStatus.NOT_FOUND)
                return
            self.send_markdown(*report)
            return
        if parsed.path == "/api/portfolio-report":
            query = parse_qs(parsed.query)
            if query.get("format", ["md"])[0].lower() == "pdf":
                self.send_pdf(*portfolio_pdf_report())
            else:
                self.send_markdown(*portfolio_markdown_report())
            return
        if parsed.path == "/api/paper-report":
            query = parse_qs(parsed.query)
            policy = query.get("policy", ["strict"])[0].lower()
            if policy == "ladder":
                report_path = PAPER_LADDER_REPORT_PATH
                trades_path = PAPER_LADDER_TRADES_PATH
                report_prefix = "paper-ladder-v1"
            elif policy == "matrix":
                report_path = PAPER_MATRIX_REPORT_PATH
                trades_path = PAPER_MATRIX_TRADES_PATH
                report_prefix = "paper-matrix-v2"
            else:
                report_path = PAPER_REPORT_PATH
                trades_path = PAPER_TRADES_PATH
                report_prefix = "paper-week-100k"
            format_value = query.get("format", ["md"])[0].lower()
            if format_value == "csv":
                if not trades_path.is_file():
                    self.send_json({"error": "Ainda não existe um ledger de operações paper."}, HTTPStatus.NOT_FOUND)
                    return
                data = trades_path.read_bytes()
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", "text/csv; charset=utf-8")
                self.send_header("Content-Disposition", f'attachment; filename="{report_prefix}_trades.csv"')
                self.send_header("Content-Length", str(len(data)))
                self.send_header("Connection", "close")
                self.end_headers()
                self.send_bytes(data)
                return
            if not report_path.is_file():
                self.send_json({"error": "Ainda não existe um relatório do paper trading."}, HTTPStatus.NOT_FOUND)
                return
            self.send_markdown(report_path.name, report_path.read_text(encoding="utf-8"))
            return
        if parsed.path == "/api/sensitivity-report":
            report_path = sensitivity_report_path()
            if not report_path.is_file():
                self.send_json({"error": "Ainda não existe um estudo de sensibilidade."}, HTTPStatus.NOT_FOUND)
                return
            self.send_markdown(report_path.name, report_path.read_text(encoding="utf-8"))
            return
        if parsed.path == "/api/live-validation-report":
            self.send_markdown(*live_validation_markdown())
            return
        if parsed.path == "/api/report-library":
            self.send_json({"reports": report_library_entries()})
            return
        if parsed.path == "/api/snapshot-comparison-report":
            self.send_markdown(*snapshot_comparison_markdown())
            return
        if parsed.path == "/api/report-archive":
            filename = parse_qs(parsed.query).get("file", [""])[0]
            basename = Path(filename).name
            match = re.fullmatch(r"radar-diario-\d{4}-\d{2}-\d{2}\.(md|pdf)", basename)
            report_dir = (OUTPUT_DIR / "reports").resolve()
            candidate = (report_dir / basename).resolve()
            if filename != basename or not match or candidate.parent != report_dir or not candidate.is_file():
                self.send_json({"error": "Report arquivado não encontrado."}, HTTPStatus.NOT_FOUND)
                return
            if candidate.suffix.lower() == ".pdf":
                self.send_pdf(candidate.name, candidate.read_bytes())
            else:
                self.send_markdown(candidate.name, candidate.read_text(encoding="utf-8"))
            return
        if parsed.path == "/api/daily-report":
            report_path = OUTPUT_DIR / "relatorio-momentum.md"
            if not report_path.is_file():
                self.send_json({"error": "Ainda não existe um relatório diário em outputs/."}, HTTPStatus.NOT_FOUND)
                return
            query = parse_qs(parsed.query)
            if query.get("format", ["md"])[0].lower() == "pdf":
                report = daily_pdf_report()
                if not report:
                    self.send_json({"error": "Ainda não existe um snapshot diário com sinais."}, HTTPStatus.NOT_FOUND)
                    return
                self.send_pdf(*report)
                return
            self.send_markdown("relatorio-momentum.md", report_path.read_text(encoding="utf-8"))
            return
        if parsed.path.startswith("/api/"):
            self.send_json({"error": "Endpoint não encontrado."}, HTTPStatus.NOT_FOUND)
            return

        relative = parsed.path.lstrip("/") or "index.html"
        candidate = (UI_DIR / relative).resolve()
        try:
            candidate.relative_to(UI_DIR.resolve())
        except ValueError:
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        if not candidate.is_file():
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        content_type = "text/html; charset=utf-8" if candidate.suffix == ".html" else "text/css; charset=utf-8" if candidate.suffix == ".css" else "application/javascript; charset=utf-8"
        data = candidate.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)
        self.wfile.flush()

    def do_POST(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path == "/api/login":
            if auth_disabled():
                self.send_json({"ok": True, "authenticated": True, "username": configured_username()})
                return
            if setup_required():
                self.send_json({"error": "Define RADAR_AUTH_PASSWORD antes de iniciar o servidor."}, HTTPStatus.SERVICE_UNAVAILABLE)
                return
            address = self._client_address()
            if not login_allowed(address):
                self.send_json({"error": "Demasiadas tentativas. Tenta novamente dentro de 15 minutos."}, HTTPStatus.TOO_MANY_REQUESTS)
                return
            body = parse_body(self)
            username = str(body.get("username", ""))
            password = str(body.get("password", ""))
            if not verify_credentials(username, password):
                record_failed_login(address)
                self.send_json({"error": "Credenciais inválidas."}, HTTPStatus.UNAUTHORIZED)
                return
            token, expires = create_session(username.strip())
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Connection", "close")
            self.send_session_cookie(token, expires)
            payload = json.dumps({"ok": True, "authenticated": True, "username": username.strip()}, ensure_ascii=False).encode("utf-8")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.send_bytes(payload)
            return
        if parsed.path == "/api/logout":
            delete_session(parse_cookie(self.headers.get("Cookie")))
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Connection", "close")
            self.clear_session_cookie()
            payload = b'{"ok":true,"authenticated":false}'
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.send_bytes(payload)
            return
        if not self.require_auth(api=True):
            return
        if parsed.path == "/api/live-analyze":
            body = parse_body(self)
            result = collect_live_analysis(str(body.get("symbol", "")))
            if not result.get("ok"):
                self.send_json(result, HTTPStatus.BAD_GATEWAY)
                return
            result["state"] = load_state(include_heavy=False)
            self.send_json(result, HTTPStatus.OK)
            return
        if parsed.path == "/api/analyze":
            body = parse_body(self)
            result = analyze(str(body.get("symbol", "")))
            self.send_json(result or {"error": "Ativo sem sinal no snapshot atual."}, HTTPStatus.OK if result else HTTPStatus.NOT_FOUND)
            return
        if parsed.path == "/api/journal":
            body = parse_body(self)
            symbol = str(body.get("symbol", "")).strip().upper()
            note = str(body.get("note", ""))
            if not SYMBOL_RE.fullmatch(symbol):
                self.send_json({"error": "Indica um símbolo válido para guardar a nota."}, HTTPStatus.BAD_REQUEST)
                return
            if len(note) > 2000:
                self.send_json({"error": "A nota pode ter no máximo 2000 caracteres."}, HTTPStatus.BAD_REQUEST)
                return
            state = load_state()
            as_of = str(body.get("as_of") or state.get("meta", {}).get("as_of", "")).strip()
            if not as_of:
                self.send_json({"error": "Ainda não existe um snapshot ao qual ligar esta nota."}, HTTPStatus.BAD_REQUEST)
                return
            save_journal_entry(symbol, as_of, note)
            self.send_json(load_state(include_heavy=False), HTTPStatus.OK)
            return
        if parsed.path == "/api/portfolio":
            body = parse_body(self)
            raw_positions = body.get("positions")
            if not isinstance(raw_positions, list):
                self.send_json({"error": "positions tem de ser uma lista."}, HTTPStatus.BAD_REQUEST)
                return
            positions: list[dict[str, Any]] = []
            for raw in raw_positions:
                if not isinstance(raw, dict):
                    continue
                symbol = str(raw.get("symbol", "")).strip().upper()
                quantity = number(raw.get("quantity"))
                avg_cost = number(raw.get("avg_cost"))
                if not SYMBOL_RE.fullmatch(symbol) or quantity <= 0 or avg_cost < 0:
                    self.send_json({"error": f"Posição inválida: {symbol or 'sem símbolo'}."}, HTTPStatus.BAD_REQUEST)
                    return
                clean = {"symbol": symbol, "quantity": quantity, "avg_cost": avg_cost, "currency": str(raw.get("currency", "USD"))[:8]}
                for key in ("broker", "isin", "exchange", "reference_price", "cost_basis_status", "cost_basis_note", "cost_unit", "statement_value_eur"):
                    if key in raw and raw[key] not in (None, ""):
                        clean[key] = raw[key]
                positions.append(clean)
            write_json(PORTFOLIO_PATH, {"updated_at": dt.datetime.now(dt.timezone.utc).isoformat(), "positions": positions})
            self.send_json(load_state(include_heavy=False), HTTPStatus.OK)
            return
        if parsed.path == "/api/portfolio-targets":
            body = parse_body(self)
            targets = body.get("targets")
            if not isinstance(targets, dict):
                self.send_json({"error": "targets tem de ser um objeto por setor."}, HTTPStatus.BAD_REQUEST)
                return
            clean = {str(key): value for key, value in targets.items()}
            if sum(number(value, -1.0) for value in clean.values() if number(value, -1.0) >= 0) > 1.000001:
                self.send_json({"error": "As metas não podem somar mais de 100%."}, HTTPStatus.BAD_REQUEST)
                return
            saved = save_portfolio_targets(clean)
            # Keep the write endpoint small and deterministic. The browser
            # refreshes the read model separately, avoiding a full snapshot
            # rebuild while the target file is being replaced.
            self.send_json({"ok": True, "targets": saved}, HTTPStatus.OK)
            return
        self.send_json({"error": "Endpoint não encontrado."}, HTTPStatus.NOT_FOUND)

    def log_message(self, format: str, *args: object) -> None:
        print(f"[radar-ui] {format % args}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Servidor local da interface do Radar Momentum")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    if not auth_disabled() and not os.environ.get("RADAR_AUTH_PASSWORD") and args.host in {"127.0.0.1", "localhost", "::1"}:
        password = getpass("Password do Radar (não será guardada no projeto): ")
        if not password:
            print("É necessária uma password. Define RADAR_AUTH_DISABLED=1 apenas para desenvolvimento local.")
            return 2
        os.environ["RADAR_AUTH_PASSWORD"] = password
    if not auth_disabled() and not os.environ.get("RADAR_AUTH_PASSWORD"):
        print("RADAR_AUTH_PASSWORD é obrigatório quando o servidor aceita tráfego externo.")
        return 2
    UI_DIR.mkdir(parents=True, exist_ok=True)
    print(f"Radar UI em http://{args.host}:{args.port}")
    server = ThreadingHTTPServer((args.host, args.port), DashboardHandler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nRadar UI encerrado.")
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
