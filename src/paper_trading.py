#!/usr/bin/env python3
"""Small, deterministic paper-trading ledger; it never connects to a broker."""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
from pathlib import Path
from typing import Any

from src.horizon_signals import build_horizon_views


PAPER_REVIEW_TARGET_SNAPSHOTS = 60
PAPER_REVIEW_TARGET_DECISIONS = 50
DEFAULT_PAPER_ENTRY_LADDER = (
    {"name": "exploratoria", "min_score": 60.0, "max_score": 70.0, "horizon_days": 5, "allocation_pct": 0.005, "risk_pct": 0.0005},
    {"name": "confirmada", "min_score": 70.0, "max_score": 80.0, "horizon_days": 20, "allocation_pct": 0.02, "risk_pct": 0.0015},
    {"name": "forte", "min_score": 80.0, "max_score": 101.0, "horizon_days": 60, "allocation_pct": 0.04, "risk_pct": 0.0025},
)
DEFAULT_PAPER_ENTRY_MATRIX = {
    "enabled": False,
    "version": "paper-matrix-v2",
    "min_confidence": 70.0,
    "min_data_points": 200,
    "min_entry_score": 60.0,
    "exit_score": 45.0,
    "exit_on_maturity": True,
    "max_new_entries": 2,
    "cash_floor_pct": 0.50,
    "max_total_exposure_pct": 0.40,
    "max_asset_pct": 0.06,
    "max_position_pct": 0.04,
    "max_sector_pct": 0.15,
    "max_horizon_pct": 0.20,
    "horizons": (
        {"key": "short", "label": "Curto · 5 sessões", "sessions": 5, "tiers": (
            {"name": "60–69", "min_score": 60.0, "max_score": 70.0, "allocation_pct": 0.0025, "risk_pct": 0.00025},
            {"name": "70–79", "min_score": 70.0, "max_score": 80.0, "allocation_pct": 0.0050, "risk_pct": 0.00050},
            {"name": "80+", "min_score": 80.0, "max_score": 101.0, "allocation_pct": 0.0100, "risk_pct": 0.00100},
        )},
        {"key": "medium", "label": "Médio · 20 sessões", "sessions": 20, "tiers": (
            {"name": "60–69", "min_score": 60.0, "max_score": 70.0, "allocation_pct": 0.0050, "risk_pct": 0.00050},
            {"name": "70–79", "min_score": 70.0, "max_score": 80.0, "allocation_pct": 0.0100, "risk_pct": 0.00100},
            {"name": "80+", "min_score": 80.0, "max_score": 101.0, "allocation_pct": 0.0200, "risk_pct": 0.00150},
        )},
        {"key": "long", "label": "Longo · 60 sessões", "sessions": 60, "tiers": (
            {"name": "60–69", "min_score": 60.0, "max_score": 70.0, "allocation_pct": 0.0100, "risk_pct": 0.00075},
            {"name": "70–79", "min_score": 70.0, "max_score": 80.0, "allocation_pct": 0.0200, "risk_pct": 0.00150},
            {"name": "80+", "min_score": 80.0, "max_score": 101.0, "allocation_pct": 0.0300, "risk_pct": 0.00250},
        )},
    ),
}


def load_state(path: Path, initial_cash: float) -> dict[str, Any]:
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return {
        "version": 1,
        "initial_cash": initial_cash,
        "cash": initial_cash,
        "positions": {},
        "trades": [],
        "snapshots": [],
    }


def _write_state(path: Path, state: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def _write_text_atomic(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    try:
        temporary.write_text(content, encoding="utf-8")
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def _record_run(state: dict[str, Any], payload: dict[str, Any], processed: bool, reason: str = "") -> None:
    """Keep an operational run ledger separate from market-date snapshots."""
    signals = payload.get("signals", [])
    meta = payload.get("meta", {})
    runs = state.setdefault("runs", [])
    runs.append({
        "run_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "source_as_of": meta.get("as_of", ""),
        "mode": meta.get("mode", state.get("last_mode", "")),
        "signals": len(signals),
        "processed": processed,
        "reason": reason,
    })
    # Keep the state portable and bounded if a task is left running for months.
    if len(runs) > 100:
        del runs[:-100]


def paper_coverage(state: dict[str, Any]) -> dict[str, Any]:
    """Measure observed market dates against potential weekdays in the sample."""
    dates = sorted({
        str(item.get("date", ""))
        for item in state.get("snapshots", [])
        if isinstance(item, dict) and item.get("date")
    })
    valid_dates: list[dt.date] = []
    for value in dates:
        try:
            valid_dates.append(dt.date.fromisoformat(value))
        except ValueError:
            continue
    valid_dates.sort()
    if not valid_dates:
        return {
            "available": False,
            "observed_snapshots": 0,
            "potential_weekdays": 0,
            "missing_potential_dates": [],
            "coverage_pct": 0.0,
            "note": "A cobertura aparece quando existir pelo menos um snapshot com data de mercado.",
        }

    first = valid_dates[0]
    last = valid_dates[-1]
    potential: list[str] = []
    cursor = first
    while cursor <= last:
        if cursor.weekday() < 5:
            potential.append(cursor.isoformat())
        cursor += dt.timedelta(days=1)
    observed = {value.isoformat() for value in valid_dates}
    missing = [value for value in potential if value not in observed]
    return {
        "available": True,
        "first_snapshot": first.isoformat(),
        "last_snapshot": last.isoformat(),
        "observed_snapshots": len(observed),
        "potential_weekdays": len(potential),
        "missing_potential_dates": missing,
        "coverage_pct": round(len(observed) / len(potential) * 100.0, 1) if potential else 100.0,
        "note": "Dias úteis potenciais; feriados e fechos de mercado podem explicar parte das lacunas.",
    }


def review_progress(state: dict[str, Any]) -> dict[str, Any]:
    """Summarize whether the paper sample is large enough for a review."""
    snapshots = [item for item in state.get("snapshots", []) if isinstance(item, dict)]
    decisions = sum(max(0, int(item.get("signals", 0) or 0)) for item in snapshots)
    snapshot_count = len({str(item.get("date", "")) for item in snapshots if item.get("date")})
    snapshot_pct = min(100.0, snapshot_count / PAPER_REVIEW_TARGET_SNAPSHOTS * 100.0)
    decision_pct = min(100.0, decisions / PAPER_REVIEW_TARGET_DECISIONS * 100.0)
    missing_snapshots = max(0, PAPER_REVIEW_TARGET_SNAPSHOTS - snapshot_count)
    missing_decisions = max(0, PAPER_REVIEW_TARGET_DECISIONS - decisions)
    ready = missing_snapshots == 0 and missing_decisions == 0
    return {
        "snapshots": snapshot_count,
        "target_snapshots": PAPER_REVIEW_TARGET_SNAPSHOTS,
        "snapshot_progress_pct": round(snapshot_pct, 1),
        "decision_records": decisions,
        "target_decisions": PAPER_REVIEW_TARGET_DECISIONS,
        "decision_progress_pct": round(decision_pct, 1),
        "ready_for_review": ready,
        "coverage": paper_coverage(state),
        "message": "Amostra mínima atingida; já pode ser feita a revisão escrita." if ready else f"Faltam {missing_snapshots} snapshots únicos e {missing_decisions} decisões.",
    }


def _live_quality_failures(payload: dict[str, Any]) -> list[str]:
    """Return missing/failed live symbols required for a trustworthy paper run."""
    config = payload.get("config", {})
    required = {"GLOBAL"}
    required.update(str(item.get("symbol")) for item in config.get("universe", []) if item.get("symbol") and not item.get("portfolio_monitor_only"))
    quality_by_symbol = {str(row.get("symbol")): row for row in payload.get("quality", [])}
    return sorted(symbol for symbol in required if quality_by_symbol.get(symbol, {}).get("status") != "OK")


def _action_counts(signals: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for signal in signals:
        action = str(signal.get("action", "N\u00e3o agir"))
        counts[action] = counts.get(action, 0) + 1
    return dict(sorted(counts.items()))


def _watch_factors(signal: dict[str, Any]) -> list[str]:
    """Return the weakest model components without turning them into advice."""
    factors = [
        ("momentum", float(signal.get("momentum", 50.0) or 50.0)),
        ("força relativa", float(signal.get("relative_strength", 50.0) or 50.0)),
        ("tendência", float(signal.get("trend", 50.0) or 50.0)),
        ("volume", float(signal.get("volume", 50.0) or 50.0)),
        ("notícias", float(signal.get("news", 50.0) or 50.0)),
        ("macro", float(signal.get("macro", 50.0) or 50.0)),
    ]
    weak = [name for name, value in sorted(factors, key=lambda item: item[1]) if value < 50.0][:3]
    if not weak:
        weak = [name for name, _value in sorted(factors, key=lambda item: item[1])[:2]]
    try:
        risk_penalty = float(signal.get("risk_penalty", 0.0) or 0.0)
    except (TypeError, ValueError):
        risk_penalty = 0.0
    if risk_penalty >= 5.0:
        weak.append(f"risco penalizado ({risk_penalty:.1f})")
    return weak[:4]


def _entry_review(
    date_value: str,
    signals: list[dict[str, Any]],
    *,
    status: str,
    reason: str = "",
    entries: int = 0,
    buy_score: float = 80.0,
    hold_score: float = 55.0,
) -> dict[str, Any]:
    """Explain every paper snapshot, including snapshots with zero trades."""
    buy_candidates = [str(signal.get("symbol", "")) for signal in signals if str(signal.get("action", "")) == "Considerar compra"]
    near_entry = [
        {
            "symbol": str(signal.get("symbol", "")),
            "score": round(float(signal.get("score", 0.0)), 2),
            "action": str(signal.get("action", "")),
            "gap_to_buy": round(max(0.0, buy_score - float(signal.get("score", 0.0) or 0.0)), 2),
            "watch_factors": _watch_factors(signal),
        }
        for signal in signals
        if hold_score <= float(signal.get("score", 0.0) or 0.0) < buy_score and int(signal.get("data_points", 0) or 0) >= 200
    ]
    near_entry.sort(key=lambda item: item["score"], reverse=True)
    short_history = [str(signal.get("symbol", "")) for signal in signals if int(signal.get("data_points", 0) or 0) < 200]
    blockers: list[dict[str, Any]] = []
    if reason:
        blockers.append({"code": "run_blocked", "message": reason})
    if not buy_candidates and status == "processed":
        blockers.append({"code": "no_buy_signal", "message": "Nenhum sinal atingiu a ação Considerar compra."})
        if near_entry:
            top = near_entry[0]
            factors = ", ".join(top.get("watch_factors", [])) or "os componentes do score"
            blockers.append({"code": "below_buy_threshold", "symbol": top["symbol"], "gap_to_buy": top["gap_to_buy"], "watch_factors": top.get("watch_factors", []), "message": f"{top['symbol']} ficou {top['gap_to_buy']:.1f} pontos abaixo do limiar; vigiar {factors}."})
    if short_history:
        blockers.append({"code": "insufficient_history", "symbols": short_history, "message": "Alguns sinais ficaram em Não agir por terem menos de 200 observações."})
    if entries == 0 and buy_candidates and status == "processed":
        blockers.append({"code": "buy_candidates_not_executed", "symbols": buy_candidates, "message": "Havia candidatos, mas nenhuma alocação foi executada; consultar limites de posição, setor, caixa ou drawdown."})
    return {
        "date": date_value,
        "status": status,
        "signals": len(signals),
        "action_counts": _action_counts(signals),
        "buy_score": round(buy_score, 2),
        "buy_candidates": buy_candidates,
        "near_entry_candidates": near_entry,
        "entries": entries,
        "blockers": blockers,
    }


def _paper_entry_tier(signal: dict[str, Any], ladder: list[dict[str, Any]], min_confidence: float = 0.0) -> dict[str, Any] | None:
    """Return the first eligible ladder tier for a signal, without using action labels."""
    try:
        score = float(signal.get("score", 0.0) or 0.0)
        confidence = float(signal.get("confidence", 0.0) or 0.0)
        data_points = int(signal.get("data_points", 0) or 0)
    except (TypeError, ValueError):
        return None
    if score < 0 or confidence < min_confidence or data_points < 200:
        return None
    for raw_tier in ladder:
        if not isinstance(raw_tier, dict):
            continue
        try:
            minimum = float(raw_tier.get("min_score", 0.0))
            maximum = float(raw_tier.get("max_score", 101.0))
        except (TypeError, ValueError):
            continue
        if minimum <= score < maximum and str(signal.get("action", "")) != "Reduzir/evitar":
            return dict(raw_tier)
    return None


def _paper_ladder_config(thresholds: dict[str, Any]) -> dict[str, Any]:
    """Normalize the optional tiered paper policy from config."""
    raw = thresholds.get("paper_entry_ladder", {})
    settings = raw if isinstance(raw, dict) else {}
    raw_tiers = settings.get("tiers", DEFAULT_PAPER_ENTRY_LADDER)
    tiers = [dict(item) for item in raw_tiers if isinstance(item, dict)] if isinstance(raw_tiers, list) else []
    return {
        "enabled": bool(settings.get("enabled", False)),
        "min_confidence": float(settings.get("min_confidence", 70.0)),
        "max_new_entries": max(1, int(settings.get("max_new_entries", 2))),
        "cash_floor_pct": max(0.0, min(1.0, float(settings.get("cash_floor_pct", 0.50)))),
        "max_total_exposure_pct": max(0.0, min(1.0, float(settings.get("max_total_exposure_pct", 0.40)))),
        "max_position_pct": max(0.0, min(1.0, float(settings.get("max_position_pct", 0.04)))),
        "max_sector_pct": max(0.0, min(1.0, float(settings.get("max_sector_pct", 0.15)))),
        "tiers": tiers or [dict(item) for item in DEFAULT_PAPER_ENTRY_LADDER],
    }


def apply_signals(state: dict[str, Any], payload: dict[str, Any], strict_live_quality: bool = False) -> dict[str, Any]:
    signals = [
        signal for signal in payload.get("signals", [])
        if not any(
            isinstance(item, dict)
            and str(item.get("symbol", "")).upper() == str(signal.get("symbol", "")).upper()
            and item.get("portfolio_monitor_only")
            for item in payload.get("config", {}).get("universe", [])
        )
    ]
    config = payload.get("config", {})
    date_value = payload.get("meta", {}).get("as_of") or dt.date.today().isoformat()
    mode = payload.get("meta", {}).get("mode", state.get("last_mode", ""))
    thresholds = config.get("thresholds", {}) if isinstance(config.get("thresholds", {}), dict) else {}
    buy_score = float(thresholds.get("buy_score", 80.0))
    hold_score = float(thresholds.get("hold_score", 55.0))
    ladder = _paper_ladder_config(thresholds)
    state["policy"] = "paper-ladder-v1" if ladder["enabled"] else "strict-score-v1"

    def decorate_review(review: dict[str, Any]) -> dict[str, Any]:
        review["policy"] = "paper-ladder-v1" if ladder["enabled"] else "strict-score-v1"
        review["ladder"] = ladder if ladder["enabled"] else {"enabled": False, "tiers": []}
        review["ladder_candidates"] = [
            {"symbol": str(signal.get("symbol", "")), "score": round(float(signal.get("score", 0.0) or 0.0), 2), "tier": _paper_entry_tier(signal, ladder["tiers"], ladder["min_confidence"])}
            for signal in signals
            if ladder["enabled"] and _paper_entry_tier(signal, ladder["tiers"], ladder["min_confidence"]) and str(signal.get("action", "")) in {"Considerar compra", "Manter/observar"}
        ]
        return review

    if strict_live_quality and mode == "live":
        failures = _live_quality_failures(payload)
        if failures:
            state["last_mode"] = mode
            state["last_entry_review"] = decorate_review(_entry_review(date_value, signals, status="blocked", reason="qualidade live bloqueada: " + ", ".join(failures), buy_score=buy_score, hold_score=hold_score))
            _record_run(state, payload, False, "qualidade live bloqueada: " + ", ".join(failures))
            return state
    processed_dates = {
        str(item.get("date", ""))
        for item in state.get("snapshots", [])
        if isinstance(item, dict) and item.get("date")
    }
    if date_value in processed_dates:
        state["last_mode"] = mode
        state["last_entry_review"] = decorate_review(_entry_review(date_value, signals, status="duplicate", reason="same market date already processed", buy_score=buy_score, hold_score=hold_score))
        _record_run(state, payload, False, "mesma data de mercado já processada")
        return state
    latest_processed_date = max(processed_dates, default=str(state.get("last_date", "") or ""))
    if latest_processed_date and date_value < latest_processed_date:
        state["last_mode"] = mode
        reason = f"data de mercado anterior ao último snapshot processado ({latest_processed_date})"
        state["last_entry_review"] = decorate_review(_entry_review(date_value, signals, status="out_of_order", reason=reason, buy_score=buy_score, hold_score=hold_score))
        _record_run(state, payload, False, reason)
        return state
    max_position_pct = float(thresholds.get("max_position_pct", 0.1))
    max_sector_pct = float(thresholds.get("max_sector_pct", 0.2))
    drawdown_brake_pct = max(0.0, float(thresholds.get("paper_drawdown_brake_pct", 0.0)))
    execution_config = config.get("backtest", {})
    commission_rate = max(0.0, float(execution_config.get("commission_bps", 0.0))) / 10000.0
    slippage_rate = max(0.0, float(execution_config.get("slippage_bps", 0.0))) / 10000.0
    prices = {row["symbol"]: float(row["price"]) for row in signals if row.get("price") is not None}
    sectors = {row["symbol"]: row.get("sector", "") for row in signals}
    state.setdefault("positions", {})
    state.setdefault("trades", [])
    state.setdefault("snapshots", [])
    state["cash"] = float(state.get("cash", state.get("initial_cash", 0.0)))

    def equity_value() -> float:
        return state["cash"] + sum(float(pos["shares"]) * prices.get(symbol, float(pos.get("last_price", pos["entry_price"]))) for symbol, pos in state["positions"].items())

    starting_equity = equity_value()
    peak_equity = max(float(state.get("peak_equity", 0.0) or 0.0), starting_equity)
    portfolio_drawdown = (1.0 - starting_equity / peak_equity) if peak_equity > 0 else 0.0
    drawdown_brake_active = drawdown_brake_pct > 0 and portfolio_drawdown >= drawdown_brake_pct
    state["last_risk_control"] = {
        "drawdown_brake_pct": drawdown_brake_pct,
        "portfolio_drawdown": round(portfolio_drawdown, 6),
        "active": drawdown_brake_active,
        "message": "Novas compras bloqueadas pelo limite de drawdown; vendas continuam permitidas." if drawdown_brake_active else "Sem bloqueio de drawdown.",
    }
    entry_count = 0
    ladder_entry_count = 0
    allocation_blockers: list[dict[str, Any]] = []

    def record_trade(action: str, symbol: str, shares: float, price: float, reason: str, fees: float = 0.0, reference_price: float | None = None) -> None:
        notional = shares * price
        state["trades"].append({
            "date": date_value,
            "action": action,
            "symbol": symbol,
            "shares": round(shares, 8),
            "price": round(price, 8),
            "reference_price": round(reference_price if reference_price is not None else price, 8),
            "notional": round(notional, 2),
            "fees": round(fees, 2),
            "reason": reason,
        })

    for signal in signals:
        symbol = signal["symbol"]
        action = signal.get("action", "Não agir")
        price = prices.get(symbol)
        if price is None or price <= 0:
            continue
        position = state["positions"].get(symbol)
        if position:
            position["last_price"] = price
        if action == "Reduzir/evitar" and position:
            shares = float(position["shares"])
            execution_price = price * (1.0 - slippage_rate)
            gross_notional = shares * execution_price
            fees = gross_notional * commission_rate
            state["cash"] += gross_notional - fees
            record_trade("SELL", symbol, shares, execution_price, "sinal Reduzir/evitar", fees, price)
            del state["positions"][symbol]
        else:
            entry_tier = _paper_entry_tier(signal, ladder["tiers"], ladder["min_confidence"]) if ladder["enabled"] else None
            ladder_buy = entry_tier is not None and action in {"Considerar compra", "Manter/observar"}
            should_buy = ladder_buy if ladder["enabled"] else action == "Considerar compra"
            if not should_buy or position:
                continue
            if drawdown_brake_active:
                allocation_blockers.append({"symbol": symbol, "message": "compras bloqueadas pelo travão de drawdown"})
                continue
            if ladder["enabled"] and ladder_entry_count >= ladder["max_new_entries"]:
                allocation_blockers.append({"symbol": symbol, "message": f"limite de {ladder['max_new_entries']} novas entradas por sessão atingido"})
                continue
            equity = max(equity_value(), 0.0)
            current_exposure = sum(float(pos["shares"]) * prices.get(item, float(pos.get("last_price", pos["entry_price"]))) for item, pos in state["positions"].items())
            position_cap = equity * max_position_pct
            risk_distance = None
            reason = "sinal Considerar compra"
            if ladder["enabled"] and entry_tier:
                tier_allocation = max(0.0, min(1.0, float(entry_tier.get("allocation_pct", 0.0))))
                position_cap = equity * min(ladder["max_position_pct"], tier_allocation)
                horizon = max(1, int(entry_tier.get("horizon_days", 5)))
                try:
                    annual_volatility = max(0.0, float(signal.get("volatility_annual", 0.0) or 0.0))
                except (TypeError, ValueError):
                    annual_volatility = 0.0
                risk_distance = max(0.04, min(0.12, annual_volatility * (horizon / 252.0) ** 0.5))
                risk_budget = equity * max(0.0, float(entry_tier.get("risk_pct", 0.0)))
                position_cap = min(position_cap, risk_budget / risk_distance if risk_distance else position_cap)
                reason = f"escada {entry_tier.get('name', 'paper')} · score {float(signal.get('score', 0.0)):.1f} · horizonte {horizon} sessões"
            sector_value = sum(float(pos["shares"]) * prices.get(item, float(pos.get("last_price", pos["entry_price"]))) for item, pos in state["positions"].items() if sectors.get(item) == signal.get("sector"))
            sector_limit = ladder["max_sector_pct"] if ladder["enabled"] else max_sector_pct
            exposure_headroom = max(0.0, equity * (ladder["max_total_exposure_pct"] if ladder["enabled"] else 1.0) - current_exposure)
            cash_available = max(0.0, state["cash"] - equity * ladder["cash_floor_pct"]) if ladder["enabled"] else state["cash"]
            sector_cap = max(0.0, equity * sector_limit - sector_value)
            allocation = min(cash_available, position_cap, sector_cap, exposure_headroom)
            if allocation > 0:
                execution_price = price * (1.0 + slippage_rate)
                shares = allocation / (execution_price * (1.0 + commission_rate))
                gross_notional = shares * execution_price
                fees = gross_notional * commission_rate
                state["cash"] -= gross_notional + fees
                position_payload = {"shares": shares, "entry_price": execution_price, "last_price": price, "sector": signal.get("sector", ""), "entry_date": date_value}
                if entry_tier:
                    position_payload.update({"entry_policy": "paper-ladder-v1", "entry_tier": entry_tier.get("name", ""), "entry_horizon_days": int(entry_tier.get("horizon_days", 5)), "entry_score": round(float(signal.get("score", 0.0)), 2), "entry_confidence": round(float(signal.get("confidence", 0.0)), 2), "risk_distance": round(risk_distance or 0.0, 6)})
                state["positions"][symbol] = position_payload
                record_trade("BUY", symbol, shares, execution_price, reason, fees, price)
                entry_count += 1
                if entry_tier:
                    ladder_entry_count += 1
            else:
                allocation_blockers.append({"symbol": symbol, "message": "alocação calculada foi zero por limite de caixa/posição/setor"})

    for symbol, position in state["positions"].items():
        if symbol in prices:
            position["last_price"] = prices[symbol]
    equity = equity_value()
    peak_equity = max(peak_equity, equity)
    portfolio_drawdown = (1.0 - equity / peak_equity) if peak_equity > 0 else 0.0
    state["peak_equity"] = round(peak_equity, 2)
    state["portfolio_drawdown"] = round(portfolio_drawdown, 6)
    state["last_risk_control"].update({"portfolio_drawdown": round(portfolio_drawdown, 6), "active": drawdown_brake_pct > 0 and portfolio_drawdown >= drawdown_brake_pct})
    state["last_date"] = date_value
    state["last_mode"] = mode
    review = decorate_review(_entry_review(date_value, signals, status="processed", entries=entry_count, buy_score=buy_score, hold_score=hold_score))
    if allocation_blockers:
        review["blockers"].extend({"code": "allocation_blocked", **item} for item in allocation_blockers)
    state["last_entry_review"] = review
    state["snapshots"].append({"date": date_value, "source_generated_at": str(payload.get("meta", {}).get("generated_at", "")), "source": str(payload.get("meta", {}).get("replay_source", "momentum_data")), "cash": round(state["cash"], 2), "equity": round(equity, 2), "peak_equity": round(peak_equity, 2), "portfolio_drawdown": round(portfolio_drawdown, 6), "drawdown_brake_active": drawdown_brake_pct > 0 and portfolio_drawdown >= drawdown_brake_pct, "positions": len(state["positions"]), "signals": len(signals)})
    _record_run(state, payload, True)
    return state


def _paper_matrix_config(thresholds: dict[str, Any]) -> dict[str, Any]:
    """Normalize the experimental score-by-horizon matrix."""
    raw = thresholds.get("paper_entry_matrix", {})
    settings = raw if isinstance(raw, dict) else {}
    defaults = DEFAULT_PAPER_ENTRY_MATRIX
    horizons: list[dict[str, Any]] = []
    raw_horizons = settings.get("horizons", defaults["horizons"])
    if isinstance(raw_horizons, list):
        for item in raw_horizons:
            if not isinstance(item, dict):
                continue
            key = str(item.get("key", "")).strip().lower()
            if key not in {"short", "medium", "long"}:
                continue
            tiers = [dict(tier) for tier in item.get("tiers", []) if isinstance(tier, dict)]
            if len(tiers) != 3:
                continue
            horizons.append({
                "key": key,
                "label": str(item.get("label", key)),
                "sessions": max(1, int(item.get("sessions", 5))),
                "tiers": tiers,
            })
    if len(horizons) != 3:
        horizons = [{"key": item["key"], "label": item["label"], "sessions": item["sessions"], "tiers": [dict(tier) for tier in item["tiers"]]} for item in defaults["horizons"]]
    return {
        "enabled": bool(settings.get("enabled", False)),
        "version": str(settings.get("version", defaults["version"])),
        "min_confidence": max(0.0, min(100.0, float(settings.get("min_confidence", defaults["min_confidence"])))),
        "min_data_points": max(0, int(settings.get("min_data_points", defaults["min_data_points"]))),
        "min_entry_score": max(0.0, min(100.0, float(settings.get("min_entry_score", defaults["min_entry_score"])))),
        "exit_score": max(0.0, min(100.0, float(settings.get("exit_score", defaults["exit_score"])))),
        "exit_on_maturity": bool(settings.get("exit_on_maturity", defaults["exit_on_maturity"])),
        "max_new_entries": max(1, int(settings.get("max_new_entries", defaults["max_new_entries"]))),
        "cash_floor_pct": max(0.0, min(1.0, float(settings.get("cash_floor_pct", defaults["cash_floor_pct"])))),
        "max_total_exposure_pct": max(0.0, min(1.0, float(settings.get("max_total_exposure_pct", defaults["max_total_exposure_pct"])))),
        "max_asset_pct": max(0.0, min(1.0, float(settings.get("max_asset_pct", defaults["max_asset_pct"])))),
        "max_position_pct": max(0.0, min(1.0, float(settings.get("max_position_pct", defaults["max_position_pct"])))),
        "max_sector_pct": max(0.0, min(1.0, float(settings.get("max_sector_pct", defaults["max_sector_pct"])))),
        "max_horizon_pct": max(0.0, min(1.0, float(settings.get("max_horizon_pct", defaults["max_horizon_pct"])))),
        "horizons": horizons,
    }


def _matrix_horizon_tier(view: dict[str, Any], horizon: dict[str, Any], matrix: dict[str, Any]) -> dict[str, Any] | None:
    try:
        score = float(view.get("score", 0.0) or 0.0)
    except (TypeError, ValueError):
        return None
    if score < matrix["min_entry_score"]:
        return None
    for raw_tier in horizon.get("tiers", []):
        try:
            if float(raw_tier.get("min_score", 0.0)) <= score < float(raw_tier.get("max_score", 101.0)):
                tier = dict(raw_tier)
                tier["score"] = round(score, 2)
                return tier
        except (TypeError, ValueError):
            continue
    return None


def _matrix_review(date_value: str, signals: list[dict[str, Any]], matrix: dict[str, Any], candidates: list[dict[str, Any]], exits: list[dict[str, Any]], blockers: list[dict[str, Any]], entries: int) -> dict[str, Any]:
    cells = []
    for horizon in matrix["horizons"]:
        cells.extend({
            "horizon": horizon["key"],
            "label": horizon["label"],
            "sessions": horizon["sessions"],
            "tier": tier.get("name", ""),
            "min_score": tier.get("min_score"),
            "max_score": tier.get("max_score"),
            "allocation_pct": tier.get("allocation_pct", 0.0),
            "risk_pct": tier.get("risk_pct", 0.0),
        } for tier in horizon["tiers"])
    return {
        "date": date_value,
        "status": "processed",
        "signals": len(signals),
        "action_counts": _action_counts(signals),
        "policy": matrix["version"],
        "matrix": matrix,
        "cells": cells,
        "candidates": candidates,
        "exits": exits,
        "entries": entries,
        "blockers": blockers,
    }


def apply_matrix_signals(state: dict[str, Any], payload: dict[str, Any], strict_live_quality: bool = False) -> dict[str, Any]:
    """Run the score × horizon experiment with shared portfolio risk limits."""
    config = payload.get("config", {}) if isinstance(payload.get("config", {}), dict) else {}
    signals = [
        signal for signal in payload.get("signals", [])
        if not any(isinstance(item, dict) and str(item.get("symbol", "")).upper() == str(signal.get("symbol", "")).upper() and item.get("portfolio_monitor_only") for item in config.get("universe", []))
    ]
    date_value = payload.get("meta", {}).get("as_of") or dt.date.today().isoformat()
    mode = payload.get("meta", {}).get("mode", state.get("last_mode", ""))
    thresholds = config.get("thresholds", {}) if isinstance(config.get("thresholds", {}), dict) else {}
    matrix = _paper_matrix_config(thresholds)
    state["policy"] = matrix["version"]
    state["matrix_config"] = matrix
    state["version"] = 2

    if strict_live_quality and mode == "live":
        failures = _live_quality_failures(payload)
        if failures:
            state["last_mode"] = mode
            state["last_entry_review"] = {"date": date_value, "status": "blocked", "policy": matrix["version"], "entries": 0, "candidates": [], "exits": [], "blockers": [{"code": "run_blocked", "message": "qualidade live bloqueada: " + ", ".join(failures)}]}
            _record_run(state, payload, False, "qualidade live bloqueada: " + ", ".join(failures))
            return state

    processed_dates = {str(item.get("date", "")) for item in state.get("snapshots", []) if isinstance(item, dict) and item.get("date")}
    if date_value in processed_dates:
        state["last_mode"] = mode
        state["last_entry_review"] = {"date": date_value, "status": "duplicate", "policy": matrix["version"], "entries": 0, "candidates": [], "exits": [], "blockers": [{"code": "duplicate", "message": "mesma data de mercado já processada"}]}
        _record_run(state, payload, False, "mesma data de mercado já processada")
        return state
    latest_processed_date = max(processed_dates, default=str(state.get("last_date", "") or ""))
    if latest_processed_date and date_value < latest_processed_date:
        reason = f"data de mercado anterior ao último snapshot processado ({latest_processed_date})"
        state["last_mode"] = mode
        state["last_entry_review"] = {"date": date_value, "status": "out_of_order", "policy": matrix["version"], "entries": 0, "candidates": [], "exits": [], "blockers": [{"code": "out_of_order", "message": reason}]}
        _record_run(state, payload, False, reason)
        return state

    execution_config = config.get("backtest", {}) if isinstance(config.get("backtest", {}), dict) else {}
    commission_rate = max(0.0, float(execution_config.get("commission_bps", 0.0))) / 10000.0
    slippage_rate = max(0.0, float(execution_config.get("slippage_bps", 0.0))) / 10000.0
    prices = {str(row.get("symbol", "")): float(row["price"]) for row in signals if row.get("price") is not None and float(row.get("price", 0.0) or 0.0) > 0}
    sectors = {str(row.get("symbol", "")): str(row.get("sector", "")) for row in signals}
    state.setdefault("positions", {})
    state.setdefault("trades", [])
    state.setdefault("snapshots", [])
    state["cash"] = float(state.get("cash", state.get("initial_cash", 0.0)))

    def position_value(position: dict[str, Any]) -> float:
        symbol = str(position.get("symbol", ""))
        return float(position.get("shares", 0.0)) * prices.get(symbol, float(position.get("last_price", position.get("entry_price", 0.0))))

    def equity_value() -> float:
        return state["cash"] + sum(position_value(position) for position in state["positions"].values())

    starting_equity = equity_value()
    peak_equity = max(float(state.get("peak_equity", 0.0) or 0.0), starting_equity)
    portfolio_drawdown = (1.0 - starting_equity / peak_equity) if peak_equity > 0 else 0.0
    drawdown_brake_pct = max(0.0, float(thresholds.get("paper_drawdown_brake_pct", 0.0)))
    drawdown_brake_active = drawdown_brake_pct > 0 and portfolio_drawdown >= drawdown_brake_pct
    state["last_risk_control"] = {"drawdown_brake_pct": drawdown_brake_pct, "portfolio_drawdown": round(portfolio_drawdown, 6), "active": drawdown_brake_active, "message": "Novas compras bloqueadas pelo limite de drawdown; vendas continuam permitidas." if drawdown_brake_active else "Sem bloqueio de drawdown."}

    snapshot_dates = sorted({str(item.get("date", "")) for item in state.get("snapshots", []) if isinstance(item, dict) and item.get("date")})
    candidate_map: list[dict[str, Any]] = []
    exit_records: list[dict[str, Any]] = []
    blockers: list[dict[str, Any]] = []
    entry_count = 0

    def record_trade(action: str, symbol: str, horizon_key: str, shares: float, price: float, reason: str, fees: float, reference_price: float) -> None:
        state["trades"].append({"date": date_value, "action": action, "symbol": symbol, "horizon": horizon_key, "shares": round(shares, 8), "price": round(price, 8), "reference_price": round(reference_price, 8), "notional": round(shares * price, 2), "fees": round(fees, 2), "reason": reason})

    # First manage existing slots. Each slot has its own maturity and exit score.
    for position_key, position in list(state["positions"].items()):
        symbol = str(position.get("symbol", position_key.split("::", 1)[0]))
        horizon_key = str(position.get("horizon", position_key.split("::", 1)[-1]))
        price = prices.get(symbol)
        if price is None:
            continue
        position["last_price"] = price
        horizon = next((item for item in matrix["horizons"] if item["key"] == horizon_key), None)
        signal = next((item for item in signals if str(item.get("symbol", "")) == symbol), None)
        view = ((signal or {}).get("horizons") or {}).get(horizon_key) if isinstance((signal or {}).get("horizons"), dict) else None
        if signal and not isinstance(view, dict):
            view = build_horizon_views(signal, payload.get("context", {})).get(horizon_key, {})
        elapsed = len([item for item in snapshot_dates if item > str(position.get("entry_date", ""))]) + (1 if date_value > str(position.get("entry_date", "")) else 0)
        matured = bool(matrix["exit_on_maturity"] and horizon and elapsed >= horizon["sessions"])
        weak = isinstance(view, dict) and (float(view.get("score", 0.0) or 0.0) < matrix["exit_score"] or view.get("action") == "Não agir")
        if matured or weak:
            shares = float(position.get("shares", 0.0))
            execution_price = price * (1.0 - slippage_rate)
            gross_notional = shares * execution_price
            fees = gross_notional * commission_rate
            state["cash"] += gross_notional - fees
            reason = "prazo atingido" if matured else f"score do prazo abaixo de {matrix['exit_score']:.0f}"
            record_trade("SELL", symbol, horizon_key, shares, execution_price, reason, fees, price)
            exit_records.append({"symbol": symbol, "horizon": horizon_key, "reason": reason})
            del state["positions"][position_key]

    equity = max(equity_value(), 0.0)
    current_exposure = sum(position_value(position) for position in state["positions"].values())
    asset_values: dict[str, float] = {}
    sector_values: dict[str, float] = {}
    horizon_values: dict[str, float] = {}
    for position in state["positions"].values():
        value = position_value(position)
        symbol = str(position.get("symbol", ""))
        sector = str(position.get("sector", ""))
        horizon_key = str(position.get("horizon", ""))
        asset_values[symbol] = asset_values.get(symbol, 0.0) + value
        sector_values[sector] = sector_values.get(sector, 0.0) + value
        horizon_values[horizon_key] = horizon_values.get(horizon_key, 0.0) + value

    for signal in signals:
        symbol = str(signal.get("symbol", ""))
        price = prices.get(symbol)
        if not symbol or price is None:
            continue
        views = signal.get("horizons") if isinstance(signal.get("horizons"), dict) else build_horizon_views(signal, payload.get("context", {}))
        confidence = float(signal.get("confidence", 0.0) or 0.0)
        data_points = int(signal.get("data_points", 0) or 0)
        for horizon in matrix["horizons"]:
            view = views.get(horizon["key"], {}) if isinstance(views, dict) else {}
            tier = _matrix_horizon_tier(view, horizon, matrix)
            if tier is None:
                continue
            position_key = f"{symbol}::{horizon['key']}"
            if position_key in state["positions"]:
                continue
            candidate = {"symbol": symbol, "horizon": horizon["key"], "horizon_label": horizon["label"], "score": tier["score"], "tier": tier.get("name", ""), "allocation_pct": float(tier.get("allocation_pct", 0.0) or 0.0), "eligible": confidence >= matrix["min_confidence"] and data_points >= matrix["min_data_points"]}
            candidate_map.append(candidate)
            if confidence < matrix["min_confidence"]:
                blockers.append({"code": "confidence", "symbol": symbol, "horizon": horizon["key"], "message": f"confiança {confidence:.1f} abaixo do mínimo {matrix['min_confidence']:.1f}"})
                continue
            if data_points < matrix["min_data_points"]:
                blockers.append({"code": "insufficient_history", "symbol": symbol, "horizon": horizon["key"], "message": f"histórico {data_points} abaixo do mínimo {matrix['min_data_points']}"})
                continue
            if drawdown_brake_active:
                blockers.append({"code": "drawdown", "symbol": symbol, "horizon": horizon["key"], "message": "compras bloqueadas pelo travão de drawdown"})
                continue
            if entry_count >= matrix["max_new_entries"]:
                blockers.append({"code": "entry_limit", "symbol": symbol, "horizon": horizon["key"], "message": f"limite de {matrix['max_new_entries']} novas entradas por sessão atingido"})
                continue
            equity = max(equity_value(), 0.0)
            annual_volatility = max(0.0, float(signal.get("volatility_annual", 0.0) or 0.0))
            risk_distance = max(0.04, min(0.12, annual_volatility * (horizon["sessions"] / 252.0) ** 0.5))
            risk_budget = equity * max(0.0, float(tier.get("risk_pct", 0.0) or 0.0))
            requested = equity * max(0.0, min(matrix["max_position_pct"], float(tier.get("allocation_pct", 0.0) or 0.0)))
            requested = min(requested, risk_budget / risk_distance if risk_distance else requested)
            cash_available = max(0.0, state["cash"] - equity * matrix["cash_floor_pct"])
            exposure_headroom = max(0.0, equity * matrix["max_total_exposure_pct"] - current_exposure)
            asset_headroom = max(0.0, equity * matrix["max_asset_pct"] - asset_values.get(symbol, 0.0))
            sector_headroom = max(0.0, equity * matrix["max_sector_pct"] - sector_values.get(str(signal.get("sector", "")), 0.0))
            horizon_headroom = max(0.0, equity * matrix["max_horizon_pct"] - horizon_values.get(horizon["key"], 0.0))
            allocation = min(cash_available, exposure_headroom, asset_headroom, sector_headroom, horizon_headroom, requested)
            if allocation <= 0:
                blockers.append({"code": "allocation", "symbol": symbol, "horizon": horizon["key"], "message": "alocação zero por caixa, ativo, setor, horizonte ou exposição total"})
                continue
            execution_price = price * (1.0 + slippage_rate)
            shares = allocation / (execution_price * (1.0 + commission_rate))
            gross_notional = shares * execution_price
            fees = gross_notional * commission_rate
            state["cash"] -= gross_notional + fees
            state["positions"][position_key] = {"symbol": symbol, "horizon": horizon["key"], "horizon_label": horizon["label"], "shares": shares, "entry_price": execution_price, "last_price": price, "sector": signal.get("sector", ""), "entry_date": date_value, "target_sessions": horizon["sessions"], "entry_policy": matrix["version"], "entry_cell": tier.get("name", ""), "entry_score": tier["score"], "entry_confidence": round(confidence, 2), "risk_distance": round(risk_distance, 6)}
            record_trade("BUY", symbol, horizon["key"], shares, execution_price, f"matriz {horizon['key']} · {tier.get('name', '')} · score {tier['score']:.1f}", fees, price)
            entry_count += 1
            current_exposure += gross_notional
            asset_values[symbol] = asset_values.get(symbol, 0.0) + gross_notional
            sector_key = str(signal.get("sector", ""))
            sector_values[sector_key] = sector_values.get(sector_key, 0.0) + gross_notional
            horizon_values[horizon["key"]] = horizon_values.get(horizon["key"], 0.0) + gross_notional

    for position in state["positions"].values():
        symbol = str(position.get("symbol", ""))
        if symbol in prices:
            position["last_price"] = prices[symbol]
    final_equity = equity_value()
    peak_equity = max(peak_equity, final_equity)
    portfolio_drawdown = (1.0 - final_equity / peak_equity) if peak_equity > 0 else 0.0
    state["peak_equity"] = round(peak_equity, 2)
    state["portfolio_drawdown"] = round(portfolio_drawdown, 6)
    state["last_risk_control"].update({"portfolio_drawdown": round(portfolio_drawdown, 6), "active": drawdown_brake_pct > 0 and portfolio_drawdown >= drawdown_brake_pct})
    state["last_date"] = date_value
    state["last_mode"] = mode
    if not candidate_map:
        blockers.append({"code": "no_eligible_cell", "message": "Nenhum ativo atingiu uma célula score × prazo elegível nesta ronda."})
    state["last_entry_review"] = _matrix_review(date_value, signals, matrix, candidate_map, exit_records, blockers, entry_count)
    state["snapshots"].append({"date": date_value, "source_generated_at": str(payload.get("meta", {}).get("generated_at", "")), "source": str(payload.get("meta", {}).get("replay_source", "momentum_data")), "cash": round(state["cash"], 2), "equity": round(final_equity, 2), "peak_equity": round(peak_equity, 2), "portfolio_drawdown": round(portfolio_drawdown, 6), "drawdown_brake_active": bool(state["last_risk_control"].get("active")), "positions": len(state["positions"]), "signals": len(signals)} )
    _record_run(state, payload, True)
    return state


def write_outputs(state: dict[str, Any], output_dir: Path, output_prefix: str = "paper") -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    _write_text_atomic(output_dir / f"{output_prefix}_portfolio.json", json.dumps(state, ensure_ascii=False, indent=2))
    trades_path = output_dir / f"{output_prefix}_trades.csv"
    trades_temporary = trades_path.with_suffix(trades_path.suffix + ".tmp")
    try:
        with trades_temporary.open("w", encoding="utf-8", newline="") as handle:
            fields = ["date", "action", "symbol", "horizon", "shares", "price", "reference_price", "notional", "fees", "reason"]
            writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(state.get("trades", []))
        trades_temporary.replace(trades_path)
    finally:
        trades_temporary.unlink(missing_ok=True)
    latest = state.get("snapshots", [])[-1] if state.get("snapshots") else {"date": "", "equity": state.get("initial_cash", 0.0), "cash": state.get("cash", 0.0), "positions": 0, "signals": 0}
    progress = review_progress(state)
    near_entry_text = ", ".join(
        f"{item.get('symbol', '')} ({float(item.get('score', 0.0)):.1f}; faltam {float(item.get('gap_to_buy', 0.0)):.1f}; vigiar {', '.join(item.get('watch_factors', []))})"
        for item in state.get("last_entry_review", {}).get("near_entry_candidates", [])
    ) or "nenhum"
    entry_review = state.get("last_entry_review", {}) if isinstance(state.get("last_entry_review", {}), dict) else {}
    entry_status = str(entry_review.get("status", "sem diagnostico"))
    entry_reason = next((str(item.get("message", "")) for item in entry_review.get("blockers", []) if isinstance(item, dict) and item.get("message")), "")
    ladder_candidates_text = ", ".join(
        f"{item.get('symbol', '')} ({item.get('tier', {}).get('name', 'sem nível')})"
        for item in entry_review.get("ladder_candidates", [])
        if isinstance(item, dict) and isinstance(item.get("tier"), dict)
    ) or "nenhum"
    coverage = progress.get("coverage", {})
    coverage_missing = ", ".join(coverage.get("missing_potential_dates", [])[:8]) if isinstance(coverage, dict) else ""
    lines = [
        "# Paper trading — Radar de momentum",
        "",
        "> [!warning] Simulação",
        "> Este diário é fictício, não envia ordens e não representa execução real, custos ou liquidez de uma corretora.",
        "",
        f"**Data:** {latest['date']}",
        f"**Equity simulada:** {latest['equity']:.2f}",
        f"**Cash:** {latest['cash']:.2f}",
        f"**Posições:** {latest['positions']}",
        f"**Sinais processados:** {latest['signals']}",
        f"**Execuções da tarefa:** {len(state.get('runs', []))}",
        f"**Decisões registadas:** {progress['decision_records']}",
        f"**Progresso para revisão:** {progress['snapshots']}/{progress['target_snapshots']} snapshots · {progress['decision_records']}/{progress['target_decisions']} decisões",
        f"**Pronto para revisão:** {'sim' if progress['ready_for_review'] else 'não'}",
        f"**Estado da revisao de entradas:** {entry_status}",
        f"**Política de entradas:** {state.get('policy', 'strict-score-v1')}",
        f"**Motivo da revisao:** {entry_reason or 'sem bloqueio registado'}",
        f"**Custos simulados:** {sum(float(trade.get('fees', 0.0)) for trade in state.get('trades', [])):.2f}",
        f"**Drawdown da carteira:** {float(state.get('portfolio_drawdown', 0.0)):.1%} desde o pico · limite {'ativo' if state.get('last_risk_control', {}).get('active') else 'inativo'}",
        "",
        "## Cobertura operacional",
        "",
        f"**Snapshots observados:** {coverage.get('observed_snapshots', 0)}/{coverage.get('potential_weekdays', 0)} dias úteis potenciais ({float(coverage.get('coverage_pct', 0.0)):.1f}%)." if isinstance(coverage, dict) and coverage.get("available") else "**Snapshots observados:** ainda não há dados suficientes para medir a cobertura.",
        f"**Intervalo:** {coverage.get('first_snapshot', '')} → {coverage.get('last_snapshot', '')}" if isinstance(coverage, dict) and coverage.get("available") else "",
        f"**Dias potenciais sem snapshot:** {coverage_missing or 'nenhum'}",
        f"**Nota:** {coverage.get('note', '')}" if isinstance(coverage, dict) and coverage.get("note") else "",
        "",
        "## Revisão de entradas",
        "",
        f"**Limiar de compra:** {float(state.get('last_entry_review', {}).get('matrix', {}).get('min_entry_score', state.get('last_entry_review', {}).get('buy_score', 80.0))):.1f}/100",
        f"**Candidatos a compra:** {', '.join(sorted({str(item.get('symbol', '')) + ' · ' + str(item.get('horizon', '')) for item in state.get('last_entry_review', {}).get('candidates', []) if item.get('symbol')})) or ', '.join(state.get('last_entry_review', {}).get('buy_candidates', [])) or 'nenhum'}",
        f"**Candidatos da escada:** {ladder_candidates_text if state.get('policy') != 'paper-matrix-v2' else 'não aplicável — ver candidatos score × prazo'}",
        f"**Em observação (sem entrada confirmada):** {near_entry_text}",
        f"**Entradas executadas neste snapshot:** {int(state.get('last_entry_review', {}).get('entries', 0))}",
        f"**Ações recebidas:** {', '.join(f'{key}: {value}' for key, value in state.get('last_entry_review', {}).get('action_counts', {}).items()) or 'sem sinais'}",
        *[f"- {item.get('message', '')}" for item in state.get('last_entry_review', {}).get('blockers', []) if item.get('message')],
        "",
        "## Últimas operações",
        "",
        "| Data | Ação | Símbolo | Quantidade | Preço execução | Valor | Custos | Motivo |",
        "|---|---|---|---:|---:|---:|---:|---|",
    ]
    if state.get("policy") == "paper-matrix-v2":
        matrix = state.get("matrix_config", {})
        lines.extend([
            "**Matriz experimental:** 3 horizontes × 3 bandas de score; os valores são parâmetros de paper trading e não uma garantia de retorno.",
            f"**Limites agregados:** ativo {float(matrix.get('max_asset_pct', 0.0)):.1%} · setor {float(matrix.get('max_sector_pct', 0.0)):.1%} · exposição total {float(matrix.get('max_total_exposure_pct', 0.0)):.1%} · caixa mínimo {float(matrix.get('cash_floor_pct', 0.0)):.1%}",
            "**Células observadas:** " + ", ".join(f"{item.get('horizon')} {item.get('tier')}={float(item.get('allocation_pct', 0.0)):.2%}" for item in state.get("last_entry_review", {}).get("cells", [])),
        ])
    for trade in state.get("trades", [])[-20:]:
        lines.append(f"| {trade['date']} | {trade['action']} | {trade['symbol']} | {trade['shares']:.6f} | {trade['price']:.4f} | {trade['notional']:.2f} | {float(trade.get('fees', 0.0)):.2f} | {trade['reason']} |")
    _write_text_atomic(output_dir / f"{output_prefix}-report.md", "\n".join(lines) + "\n")
    latest = state.get("snapshots", [])[-1] if state.get("snapshots") else {"date": "", "equity": state.get("initial_cash", 0.0), "cash": state.get("cash", 0.0), "positions": 0, "signals": 0}
    status = {
        "updated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "mode": state.get("last_mode", ""),
        "as_of": state.get("last_date", latest.get("date", "")),
        "initial_cash": state.get("initial_cash", 0.0),
        "cash": state.get("cash", 0.0),
        "equity": latest.get("equity", state.get("cash", 0.0)),
        "positions": latest.get("positions", len(state.get("positions", {}))),
        "total_trades": len(state.get("trades", [])),
        "total_fees": round(sum(float(trade.get("fees", 0.0)) for trade in state.get("trades", [])), 2),
        "snapshots": len(state.get("snapshots", [])),
        "runs": len(state.get("runs", [])),
        "last_run_at": state.get("runs", [])[-1].get("run_at", "") if state.get("runs") else "",
        "last_run_processed": state.get("runs", [])[-1].get("processed", False) if state.get("runs") else False,
        "last_run_reason": state.get("runs", [])[-1].get("reason", "") if state.get("runs") else "",
        "last_entry_review": state.get("last_entry_review", {}),
        "policy": state.get("policy", "strict-score-v1"),
        "entry_ladder": state.get("last_entry_review", {}).get("ladder", {}),
        "entry_matrix": state.get("matrix_config", {}) if state.get("policy") == "paper-matrix-v2" else {},
        "review_progress": progress,
        "portfolio_drawdown": state.get("portfolio_drawdown", 0.0),
        "peak_equity": state.get("peak_equity", state.get("initial_cash", 0.0)),
        "last_risk_control": state.get("last_risk_control", {}),
        "paper_only": True,
    }
    _write_text_atomic(output_dir / f"{output_prefix}_status.json", json.dumps(status, ensure_ascii=False, indent=2))


def main() -> int:
    parser = argparse.ArgumentParser(description="Aplicar sinais a um diário de paper trading")
    parser.add_argument("--signals", type=Path, default=Path("outputs/momentum_data.json"))
    parser.add_argument("--state", type=Path, default=Path("outputs/paper_portfolio.json"))
    parser.add_argument("--output-dir", type=Path, default=Path("outputs"))
    parser.add_argument("--initial-cash", type=float, default=10000.0)
    parser.add_argument("--output-prefix", default="paper", help="prefixo dos ficheiros gerados para permitir carteiras separadas")
    parser.add_argument("--strict-live-quality", action="store_true", help="bloqueia paper trading live se faltar qualquer ativo crítico ou benchmark")
    parser.add_argument("--policy", choices=["strict", "ladder", "matrix"], default="strict", help="política fictícia: limiar único, escada ou matriz score × prazo")
    args = parser.parse_args()
    payload = json.loads(args.signals.read_text(encoding="utf-8"))
    thresholds = payload.setdefault("config", {}).setdefault("thresholds", {})
    ladder_config = thresholds.setdefault("paper_entry_ladder", {})
    ladder_config["enabled"] = args.policy == "ladder"
    matrix_config = thresholds.setdefault("paper_entry_matrix", {})
    matrix_config["enabled"] = args.policy == "matrix"
    loaded_state = load_state(args.state, args.initial_cash)
    state = apply_matrix_signals(loaded_state, payload, strict_live_quality=args.strict_live_quality) if args.policy == "matrix" else apply_signals(loaded_state, payload, strict_live_quality=args.strict_live_quality)
    _write_state(args.state, state)
    write_outputs(state, args.output_dir, args.output_prefix)
    latest = state.get("snapshots", [])[-1] if state.get("snapshots") else {"date": "", "equity": state.get("cash", state.get("initial_cash", 0.0)), "positions": len(state.get("positions", {}))}
    print(json.dumps({"date": latest["date"], "equity": latest["equity"], "positions": latest["positions"], "trades": len(state.get("trades", []))}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
