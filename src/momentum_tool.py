#!/usr/bin/env python3
"""Daily sector-momentum radar.

The demo mode is deterministic and needs no network or API key. Live mode uses
the provider configured for each asset and expects environment variables for
credentials. The calculation layer stays provider-agnostic so the workbook
can be generated from either mode.
"""

from __future__ import annotations

import argparse
from contextlib import contextmanager
import csv
import datetime as dt
import hashlib
import json
import math
import os
import random
import re
import statistics
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Iterable


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = ROOT / "config.json"
DATA_DIR = ROOT / "data"
OUTPUT_DIR = ROOT / "outputs"
_LAST_REQUEST_AT: dict[str, float] = {}
_RATE_LIMIT_LOCK = threading.Lock()
_CACHE_LOCKS: dict[str, threading.Lock] = {}
_CACHE_LOCKS_GUARD = threading.Lock()
_CACHE_STATS_LOCK = threading.Lock()


def safe_error_message(value: object) -> str:
    """Keep provider diagnostics useful without persisting API credentials."""
    message = str(value)
    for variable in ("ALPHAVANTAGE_API_KEY", "TIINGO_API_KEY", "FRED_API_KEY", "COINMARKETCAP_API_KEY"):
        secret = os.environ.get(variable, "").strip()
        if secret:
            message = message.replace(secret, "<redacted>")
    # Alpha Vantage occasionally echoes a key even when the request is rate-limited.
    message = re.sub(r"(api\s*key(?:\s+as)?\s+)[A-Za-z0-9_-]{8,}", r"\1<redacted>", message, flags=re.IGNORECASE)
    return message


def load_config(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def should_skip_weekend_run(
    config: dict[str, Any],
    mode: str,
    requested_symbols: set[str],
    today: dt.date | None = None,
) -> bool:
    """Avoid a full scheduled market sweep on weekends unless explicitly requested."""
    network = config.get("network", {}) if isinstance(config.get("network", {}), dict) else {}
    enabled = bool(network.get("skip_weekend_full_runs", True))
    current = today or dt.datetime.now(dt.timezone.utc).date()
    return enabled and mode == "live" and not requested_symbols and current.weekday() >= 5


def apply_universe_profile(config: dict[str, Any], profile: str = "core") -> dict[str, Any]:
    """Return a config with an explicit universe profile, without mutating the source file."""
    selected = str(profile or "core").strip().lower()
    if selected == "core":
        config["universe_profile"] = "core"
        return config
    profiles = config.get("universe_profiles", {})
    additions = profiles.get(selected) if isinstance(profiles, dict) else None
    if not isinstance(additions, list):
        available = ", ".join(sorted(str(key) for key in profiles)) if isinstance(profiles, dict) else "core"
        raise ValueError(f"perfil de universo desconhecido: {selected}; disponíveis: core, {available}")
    base = [item for item in config.get("universe", []) if isinstance(item, dict)]
    symbols = {str(item.get("symbol", "")).upper() for item in base}
    merged = list(base)
    for item in additions:
        if not isinstance(item, dict):
            continue
        symbol = str(item.get("symbol", "")).strip().upper()
        if symbol and symbol not in symbols:
            merged.append(item)
            symbols.add(symbol)
    config["universe"] = merged
    config["universe_profile"] = selected
    return config


def prepare_portfolio_monitor(config: dict[str, Any], limit: int | None = None, snapshot_path: Path | None = None) -> tuple[set[str], dict[str, Any]]:
    """Add a small holding cohort, prioritizing unread and oldest local data."""
    settings = config.get("network", {}).get("portfolio_monitor", {})
    if not isinstance(settings, dict) or settings.get("enabled", True) is False:
        return set(), {"enabled": False, "selected_symbols": [], "reserve_calls": 0}
    max_assets = max(0, int(limit if limit is not None else settings.get("max_assets_per_run", 10)))
    portfolio_path = DATA_DIR / "user_portfolio.json"
    imported_path = DATA_DIR / "portfolio_import_2026-08-06.json"
    try:
        portfolio = json.loads(portfolio_path.read_text(encoding="utf-8"))
        imported = json.loads(imported_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return set(), {"enabled": True, "selected_symbols": [], "reserve_calls": int(settings.get("reserve_calls", 5)), "message": "carteira local indisponível"}
    positions = portfolio.get("positions", []) if isinstance(portfolio, dict) else []
    assets = imported.get("assets", []) if isinstance(imported, dict) else []
    asset_map = {str(item.get("symbol", "")).strip().upper(): item for item in assets if isinstance(item, dict) and str(item.get("symbol", "")).strip()}
    known = {str(item.get("symbol", "")).strip().upper() for item in config.get("universe", []) if isinstance(item, dict)}
    latest_by_symbol: dict[str, str] = {}
    try:
        snapshot = json.loads((snapshot_path or (OUTPUT_DIR / "momentum_data.json")).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        snapshot = {}
    if isinstance(snapshot, dict):
        for row in snapshot.get("history", []):
            if not isinstance(row, dict):
                continue
            symbol = str(row.get("symbol", "")).strip().upper()
            date = str(row.get("date", "")).strip()
            if symbol and date and date > latest_by_symbol.get(symbol, ""):
                latest_by_symbol[symbol] = date
        signal_date = str(snapshot.get("meta", {}).get("as_of", "")) if isinstance(snapshot.get("meta", {}), dict) else ""
        for signal in snapshot.get("signals", []):
            if isinstance(signal, dict) and signal_date:
                symbol = str(signal.get("symbol", "")).strip().upper()
                if symbol and signal_date > latest_by_symbol.get(symbol, ""):
                    latest_by_symbol[symbol] = signal_date
    def priority(item: dict[str, Any]) -> tuple[str, float, str]:
        symbol = str(item.get("symbol", "")).strip().upper()
        value = float(item.get("statement_value_eur", item.get("market_value", 0)) or 0)
        return latest_by_symbol.get(symbol, ""), -value, symbol
    ranked = sorted((item for item in positions if isinstance(item, dict)), key=priority)
    selected: list[str] = []
    for position in ranked:
        symbol = str(position.get("symbol", "")).strip().upper()
        if not symbol or symbol in known or symbol not in asset_map or symbol in selected:
            continue
        monitored_asset = dict(asset_map[symbol])
        monitored_asset["portfolio_monitor_only"] = True
        config["universe"].append(monitored_asset)
        selected.append(symbol)
        if len(selected) >= max_assets:
            break
    return set(selected), {
        "enabled": True,
        "selected_symbols": selected,
        "max_assets_per_run": max_assets,
        "reserve_calls": int(settings.get("reserve_calls", 5)),
        "selection": "sem leitura primeiro; depois leitura mais antiga; valor como desempate",
        "message": f"{len(selected)} posições prioritárias adicionadas à ronda live",
    }


def fit_portfolio_monitor_to_budget(config: dict[str, Any], active_symbols: set[str], monitor: dict[str, Any]) -> tuple[set[str], dict[str, Any], dict[str, Any]]:
    """Trim only portfolio additions until the local pre-flight preserves quota reserves."""
    fitted = set(active_symbols)
    selected = [str(value).upper() for value in monitor.get("selected_symbols", []) if str(value).strip()]
    trimmed: list[str] = []
    plan = live_network_plan(config, fitted)
    while selected and any(int(row.get("shortfall", 0) or 0) > 0 for row in plan.get("daily_budgets", [])):
        removed = selected.pop()
        fitted.discard(removed)
        trimmed.append(removed)
        plan = live_network_plan(config, fitted)
    adjusted = dict(monitor)
    adjusted["requested_count"] = len(selected) + len(trimmed)
    adjusted["selected_symbols"] = selected
    adjusted["trimmed_symbols"] = trimmed
    adjusted["trimmed_count"] = len(trimmed)
    adjusted["budget_fitted"] = not any(int(row.get("shortfall", 0) or 0) > 0 for row in plan.get("daily_budgets", []))
    if trimmed:
        adjusted["message"] = f"ronda reduzida para {len(selected)} posições; {len(trimmed)} adiadas para preservar a reserva"
    return fitted, adjusted, plan


def select_rotating_cohort(config: dict[str, Any], profile: str, cohort_size: int = 15, cohort_index: int | None = None) -> tuple[set[str], dict[str, Any]]:
    """Select core assets plus a balanced, deterministic slice of an expanded profile."""
    universe = [item for item in config.get("universe", []) if isinstance(item, dict)]
    all_symbols = {str(item.get("symbol", "")).strip().upper() for item in universe if str(item.get("symbol", "")).strip()}
    profiles = config.get("universe_profiles", {})
    additions = profiles.get(str(profile).lower(), []) if isinstance(profiles, dict) else []
    addition_symbols = {str(item.get("symbol", "")).strip().upper() for item in additions if isinstance(item, dict) and str(item.get("symbol", "")).strip()}
    addition_symbols &= all_symbols
    core_symbols = all_symbols - addition_symbols
    if str(profile).lower() != "expanded" or not addition_symbols:
        return all_symbols, {"profile": str(profile).lower(), "index": 0, "size": len(addition_symbols), "selected_additions": sorted(addition_symbols), "sector_coverage": sorted({str(item.get("sector", "Sem setor")) for item in universe if str(item.get("symbol", "")).upper() in addition_symbols})}
    if cohort_size <= 0:
        return core_symbols, {"profile": "expanded", "index": 0, "rounds": 0, "size": 0, "selected_additions": [], "sector_coverage": []}
    grouped: dict[str, list[str]] = {}
    for item in universe:
        symbol = str(item.get("symbol", "")).strip().upper()
        if symbol in addition_symbols:
            grouped.setdefault(str(item.get("sector", "Sem setor")), []).append(symbol)
    for symbols in grouped.values():
        symbols.sort()
    sectors = sorted(grouped)
    total_additions = sum(len(values) for values in grouped.values())
    rounds = max(1, math.ceil(total_additions / max(1, cohort_size)))
    rotation_date = dt.datetime.now(dt.timezone.utc).date()
    automatic_rotation = cohort_index is None
    rotation = int(cohort_index if cohort_index is not None else rotation_date.toordinal()) % rounds
    selected: list[str] = []
    for offset in range(min(cohort_size, total_additions)):
        sector = sectors[offset % len(sectors)]
        sector_round = offset // len(sectors)
        values = grouped[sector]
        selected.append(values[(rotation + sector_round) % len(values)])
    selected = list(dict.fromkeys(selected))
    return core_symbols | set(selected), {
        "profile": "expanded",
        "index": rotation,
        "rounds": rounds,
        "size": len(selected),
        "selected_additions": sorted(selected),
        "sector_coverage": sorted({str(item.get("sector", "Sem setor")) for item in universe if str(item.get("symbol", "")).upper() in set(selected)}),
        "automatic": automatic_rotation,
        "rotation_date": rotation_date.isoformat(),
        "next_index": (rotation + 1) % rounds,
        "next_rotation_date": (rotation_date + dt.timedelta(days=1)).isoformat() if automatic_rotation else None,
    }


def validate_config(config: dict[str, Any]) -> dict[str, list[str]]:
    """Validate the editable universe without calling any provider API."""
    errors: list[str] = []
    warnings: list[str] = []
    universe = config.get("universe")
    if not isinstance(universe, list) or not universe:
        errors.append("universe tem de conter pelo menos um ativo")
        universe = []
    symbols: set[str] = set()
    news_tickers: set[str] = set()
    for index, item in enumerate(universe):
        label = f"universe[{index}]"
        if not isinstance(item, dict):
            errors.append(f"{label} tem de ser um objeto")
            continue
        symbol = str(item.get("symbol", "")).strip().upper()
        provider = str(item.get("provider", "")).strip().lower()
        source_id = str(item.get("source_id", "")).strip()
        if not symbol:
            errors.append(f"{label}.symbol está vazio")
        elif symbol in symbols:
            errors.append(f"símbolo duplicado: {symbol}")
        symbols.add(symbol)
        if not item.get("sector"):
            errors.append(f"{label} ({symbol or 'sem símbolo'}) não tem sector")
        if provider not in {"alpha_vantage", "tiingo", "coinmarketcap", "yahoo_finance"}:
            errors.append(f"{label} ({symbol or 'sem símbolo'}) usa provider não suportado: {provider or 'vazio'}")
        elif not source_id:
            errors.append(f"{label} ({symbol}) não tem source_id")
        elif provider == "coinmarketcap" and not source_id.isdigit():
            errors.append(f"{label} ({symbol}) precisa de source_id numérico CoinMarketCap")
        ticker = str(item.get("news_ticker", "")).strip().upper()
        if ticker:
            if ticker in news_tickers:
                errors.append(f"news_ticker duplicado: {ticker}")
            news_tickers.add(ticker)
    weights = config.get("weights", {})
    try:
        weight_total = sum(float(weights.get(key, 0.0)) for key in ("momentum", "relative_strength", "trend", "breadth", "volume", "news", "macro"))
        if abs(weight_total - 1.0) > 0.001:
            errors.append(f"pesos devem somar 1.0; soma atual: {weight_total:.4f}")
        if any(float(value) < 0 for value in weights.values()):
            errors.append("pesos não podem ser negativos")
    except (TypeError, ValueError):
        errors.append("pesos contêm valores não numéricos")
    thresholds = config.get("thresholds", {})
    try:
        buy_score = float(thresholds.get("buy_score", 80))
        hold_score = float(thresholds.get("hold_score", 55))
        confidence = float(thresholds.get("min_confidence", 55))
        if not 0 <= hold_score <= buy_score <= 100:
            errors.append("thresholds devem cumprir 0 <= hold_score <= buy_score <= 100")
        if not 0 <= confidence <= 100:
            errors.append("min_confidence deve estar entre 0 e 100")
    except (TypeError, ValueError):
        errors.append("thresholds contêm valores não numéricos")
    backtest = config.get("backtest", {})
    try:
        if float(backtest.get("signal_delay_days", 0)) < 0 or float(backtest.get("commission_bps", 0)) < 0 or float(backtest.get("slippage_bps", 0)) < 0:
            errors.append("atraso, comissão e slippage não podem ser negativos")
    except (TypeError, ValueError):
        errors.append("backtest contém valores não numéricos")
    query_tickers = {str(value).upper() for value in config.get("news", {}).get("query_tickers", [])}
    for item in universe:
        if not isinstance(item, dict):
            continue
        ticker = str(item.get("news_ticker", "")).strip().upper()
        if ticker and ticker not in query_tickers:
            warnings.append(f"{ticker} não está em news.query_tickers; ficará sem sentimento de notícias")
    if not config.get("macro", {}).get("series"):
        warnings.append("macro.series está vazio; o contexto macro ficará neutro")
    return {"errors": errors, "warnings": warnings}


def business_dates(count: int, end: dt.date | None = None) -> list[dt.date]:
    current = end or dt.date.today()
    dates: list[dt.date] = []
    while len(dates) < count:
        if current.weekday() < 5:
            dates.append(current)
        current -= dt.timedelta(days=1)
    return list(reversed(dates))


def deterministic_seed(value: str) -> int:
    return int(hashlib.sha256(value.encode("utf-8")).hexdigest()[:8], 16)


def generate_demo_data(config: dict[str, Any]) -> list[dict[str, Any]]:
    """Create reproducible, clearly-labelled market-like data for dry runs."""
    dates = business_dates(int(config.get("lookback_days", 900)))
    universe = [{"symbol": "GLOBAL", "sector": "Benchmark global", "source_id": "global"}]
    universe.extend(config["universe"])
    rows: list[dict[str, Any]] = []
    for item in universe:
        symbol = item["symbol"]
        rng = random.Random(deterministic_seed(symbol))
        price = 100.0 + rng.random() * 35.0
        volume_base = 1_000_000 + rng.random() * 5_000_000
        if symbol == "GLOBAL":
            drift, vol, cycle = 0.00032, 0.008, 0.018
        else:
            drift = 0.00005 + (rng.random() - 0.25) * 0.0007
            vol = 0.009 + rng.random() * 0.015
            cycle = 0.02 + rng.random() * 0.04
        for index, date_value in enumerate(dates):
            seasonal = math.sin(index / 45.0 + rng.random() * 0.2) * cycle / 20.0
            regime = 0.00035 if 480 <= index < 650 and symbol in {"AI", "BTC", "CLOUD"} else 0.0
            shock = -0.028 if index in {270, 271} and symbol in {"BTC", "ETH", "URANIUM"} else 0.0
            daily_return = drift + seasonal + regime + shock + rng.gauss(0, vol)
            price = max(price * math.exp(daily_return), 1.0)
            volume = max(volume_base * (1 + rng.gauss(0, 0.12)), 1.0)
            if index in {480, 481, 482} and symbol in {"AI", "BTC", "CLOUD"}:
                volume *= 3.2
            rows.append({
                "date": date_value.isoformat(),
                "symbol": symbol,
                "sector": item["sector"],
                "close": round(price, 6),
                "volume": round(volume, 2),
                "currency": config.get("currency", "USD"),
                "source": "demo",
                "source_id": item.get("source_id", symbol.lower()),
            })
    return rows


def _rate_limit_seconds(config: dict[str, Any] | None, namespace: str) -> float:
    """Return a provider interval suitable for free-tier APIs."""
    if not config:
        return 0.0
    network = config.get("network", {})
    if namespace in {"alpha_vantage", "news"}:
        return max(0.0, float(network.get("alpha_vantage_min_interval_seconds", 1.2)))
    if namespace == "tiingo":
        return max(0.0, float(network.get("tiingo_min_interval_seconds", 1.0)))
    if namespace == "coinmarketcap":
        return max(0.0, float(network.get("coinmarketcap_min_interval_seconds", 2.0)))
    if namespace == "yahoo_finance":
        return max(0.0, float(network.get("yahoo_finance_min_interval_seconds", 0.5)))
    return max(0.0, float(network.get("default_min_interval_seconds", 0.0)))


def _wait_for_rate_limit(config: dict[str, Any] | None, namespace: str) -> None:
    interval = _rate_limit_seconds(config, namespace)
    if interval <= 0:
        return
    # News and price calls share the Alpha Vantage quota.
    bucket = _provider_bucket(namespace)
    with _RATE_LIMIT_LOCK:
        elapsed = time.monotonic() - _LAST_REQUEST_AT.get(bucket, 0.0)
        if elapsed < interval:
            time.sleep(interval - elapsed)
        _LAST_REQUEST_AT[bucket] = time.monotonic()


def _provider_bucket(namespace: str) -> str:
    """Return the quota bucket shared by related provider endpoints."""
    return "alpha_vantage" if namespace in {"alpha_vantage", "news"} else namespace


def _daily_call_budget(config: dict[str, Any] | None, namespace: str) -> int | None:
    """Return the optional local daily call cap for a provider quota bucket."""
    network = config.get("network", {}) if isinstance(config, dict) else {}
    budgets = network.get("daily_call_budgets", {}) if isinstance(network, dict) else {}
    if not isinstance(budgets, dict):
        return None
    value = budgets.get(_provider_bucket(namespace))
    if value is None or str(value).strip().lower() in {"", "none", "unlimited"}:
        return None
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return None


def _reserve_provider_call(namespace: str, config: dict[str, Any] | None) -> None:
    """Reserve one outbound request without persisting URLs, parameters or keys."""
    budget = _daily_call_budget(config, namespace)
    bucket = _provider_bucket(namespace)
    today = dt.datetime.now(dt.timezone.utc).date().isoformat()
    now = dt.datetime.now(dt.timezone.utc).isoformat()
    with _CACHE_STATS_LOCK:
        with _cache_stats_file_lock():
            payload = read_cache_stats()
            daily_calls = payload.setdefault("daily_calls", {})
            if not isinstance(daily_calls, dict):
                daily_calls = {}
                payload["daily_calls"] = daily_calls
            item = daily_calls.get(bucket, {})
            if not isinstance(item, dict) or item.get("date") != today:
                item = {"date": today, "calls": 0}
                daily_calls[bucket] = item
            try:
                used = max(0, int(item.get("calls", 0)))
            except (TypeError, ValueError):
                used = 0
            if budget is not None and used >= budget:
                item["last_blocked_at"] = now
                item["budget"] = budget
                payload["updated_at"] = now
                try:
                    _write_cache_stats(payload)
                except OSError:
                    pass
                raise RuntimeError(f"provider {bucket} atingiu o orçamento diário local ({budget} chamadas); aguarda o reset UTC ou ajusta network.daily_call_budgets")
            item["calls"] = used + 1
            if budget is not None:
                item["budget"] = budget
            item["last_call_at"] = now
            payload["updated_at"] = now
            try:
                _write_cache_stats(payload)
            except OSError:
                return


def _cache_lock(cache_file: Path) -> threading.Lock:
    key = str(cache_file)
    with _CACHE_LOCKS_GUARD:
        return _CACHE_LOCKS.setdefault(key, threading.Lock())


def _cache_key_url(url: str) -> str:
    """Remove credentials from cache identity so key rotation does not miss cache."""
    parsed = urllib.parse.urlsplit(url)
    query = urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)
    safe_query = [(key, value) for key, value in query if key.lower() not in {"apikey", "api_key"}]
    return urllib.parse.urlunsplit((parsed.scheme, parsed.netloc, parsed.path, urllib.parse.urlencode(safe_query), parsed.fragment))


def _cache_ttl(config: dict[str, Any], namespace: str) -> int:
    cache_config = config.get("cache", {})
    by_namespace = cache_config.get("ttl_by_namespace", {})
    value = by_namespace.get(namespace, cache_config.get("ttl_seconds", 900))
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return 900


def _cache_file_for_url(namespace: str, url: str) -> Path:
    """Return the credential-free cache path for one provider resource."""
    canonical_url = _cache_key_url(url)
    return DATA_DIR / "cache" / namespace / f"{hashlib.sha256(canonical_url.encode('utf-8')).hexdigest()}.json"


def _cache_request_is_fresh(config: dict[str, Any], namespace: str, url: str, now: float | None = None) -> bool:
    """Check a specific request's local TTL without touching the provider."""
    if not config.get("cache", {}).get("enabled", True):
        return False
    cache_file = _cache_file_for_url(namespace, url)
    try:
        current = now if now is not None else dt.datetime.now().timestamp()
        return cache_file.is_file() and current - cache_file.stat().st_mtime <= _cache_ttl(config, namespace)
    except OSError:
        return False


def _cache_stats_path() -> Path:
    return DATA_DIR / "cache" / "stats.json"


@contextmanager
def _cache_stats_file_lock():
    """Serialize cache-ledger read/modify/write operations across processes."""
    if os.name != "nt":
        yield
        return
    try:
        import msvcrt
    except ImportError:
        yield
        return
    lock_path = _cache_stats_path().with_suffix(".lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    handle = lock_path.open("a+b")
    try:
        handle.seek(0, os.SEEK_END)
        if handle.tell() == 0:
            handle.write(b"0")
            handle.flush()
        handle.seek(0)
        while True:
            try:
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                break
            except OSError:
                time.sleep(0.05)
        try:
            yield
        finally:
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
    finally:
        handle.close()


def _write_cache_stats(payload: dict[str, Any]) -> None:
    """Atomically persist counters with a process-specific temporary file."""
    path = _cache_stats_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def read_cache_stats() -> dict[str, Any]:
    """Read cache counters without exposing cache keys, URLs or credentials."""
    try:
        payload = json.loads(_cache_stats_path().read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else {"version": 1, "namespaces": {}}
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        return {"version": 1, "namespaces": {}}


def cache_stats_delta(before: dict[str, Any], after: dict[str, Any], now: dt.datetime | None = None) -> dict[str, Any]:
    """Summarize cache and outbound-call changes for one local execution."""
    current = now or dt.datetime.now(dt.timezone.utc)
    today = current.astimezone(dt.timezone.utc).date().isoformat()
    metric_names = ("hits", "misses", "errors", "bypass", "stale_fallbacks")
    before_namespaces = before.get("namespaces", {}) if isinstance(before, dict) else {}
    after_namespaces = after.get("namespaces", {}) if isinstance(after, dict) else {}
    namespace_delta: dict[str, dict[str, int]] = {}
    before_keys = set(before_namespaces) if isinstance(before_namespaces, dict) else set()
    after_keys = set(after_namespaces) if isinstance(after_namespaces, dict) else set()
    for namespace in sorted(before_keys | after_keys):
        previous = before_namespaces.get(namespace, {}) if isinstance(before_namespaces, dict) and isinstance(before_namespaces.get(namespace, {}), dict) else {}
        latest = after_namespaces.get(namespace, {}) if isinstance(after_namespaces, dict) and isinstance(after_namespaces.get(namespace, {}), dict) else {}
        values = {name: max(0, int(latest.get(name, 0) or 0) - int(previous.get(name, 0) or 0)) for name in metric_names}
        if any(values.values()):
            namespace_delta[str(namespace)] = values
    before_calls = before.get("daily_calls", {}) if isinstance(before, dict) else {}
    after_calls = after.get("daily_calls", {}) if isinstance(after, dict) else {}
    calls_by_bucket: dict[str, int] = {}
    before_keys = set(before_calls) if isinstance(before_calls, dict) else set()
    after_keys = set(after_calls) if isinstance(after_calls, dict) else set()
    for bucket in sorted(before_keys | after_keys):
        previous = before_calls.get(bucket, {}) if isinstance(before_calls, dict) and isinstance(before_calls.get(bucket, {}), dict) else {}
        latest = after_calls.get(bucket, {}) if isinstance(after_calls, dict) and isinstance(after_calls.get(bucket, {}), dict) else {}
        previous_count = int(previous.get("calls", 0) or 0) if previous.get("date") == today else 0
        latest_count = int(latest.get("calls", 0) or 0) if latest.get("date") == today else 0
        delta = max(0, latest_count - previous_count)
        if delta:
            calls_by_bucket[str(bucket)] = delta
    return {
        "as_of": today,
        "outbound_calls": sum(calls_by_bucket.values()),
        "outbound_calls_by_bucket": calls_by_bucket,
        "cache_events": namespace_delta,
    }


def _provider_cooldown_seconds(config: dict[str, Any] | None) -> int:
    network = config.get("network", {}) if isinstance(config, dict) else {}
    try:
        return max(0, int(network.get("provider_cooldown_seconds", 300)))
    except (TypeError, ValueError):
        return 300


def _provider_cooldown_remaining(namespace: str) -> int:
    bucket = _provider_bucket(namespace)
    if not bucket:
        return 0
    with _CACHE_STATS_LOCK:
        payload = read_cache_stats()
        cooldowns = payload.get("cooldowns", {}) if isinstance(payload, dict) else {}
        item = cooldowns.get(bucket, {}) if isinstance(cooldowns, dict) else {}
        if not isinstance(item, dict):
            return 0
        try:
            until = dt.datetime.fromisoformat(str(item.get("until", ""))).timestamp()
        except (TypeError, ValueError, OverflowError):
            return 0
        return max(0, int(until - dt.datetime.now(dt.timezone.utc).timestamp()))


def _record_provider_cooldown(namespace: str, config: dict[str, Any] | None, reason: str = "rate_limit") -> None:
    bucket = _provider_bucket(namespace)
    seconds = _provider_cooldown_seconds(config)
    if not bucket or seconds <= 0:
        return
    now = dt.datetime.now(dt.timezone.utc)
    until = now + dt.timedelta(seconds=seconds)
    with _CACHE_STATS_LOCK:
        with _cache_stats_file_lock():
            payload = read_cache_stats()
            cooldowns = payload.setdefault("cooldowns", {})
            if not isinstance(cooldowns, dict):
                cooldowns = {}
                payload["cooldowns"] = cooldowns
            cooldowns[bucket] = {"until": until.isoformat(), "reason": reason if reason in {"rate_limit", "http_429"} else "rate_limit"}
            payload["updated_at"] = now.isoformat()
            try:
                _write_cache_stats(payload)
            except OSError:
                return


def _record_cache_event(namespace: str, event: str) -> None:
    if not namespace or event not in {"hit", "miss", "error", "bypass", "stale"}:
        return
    with _CACHE_STATS_LOCK:
        with _cache_stats_file_lock():
            payload = read_cache_stats()
            payload.setdefault("version", 1)
            namespaces = payload.setdefault("namespaces", {})
            if not isinstance(namespaces, dict):
                namespaces = {}
                payload["namespaces"] = namespaces
            item = namespaces.setdefault(namespace, {"hits": 0, "misses": 0, "errors": 0, "bypass": 0, "stale_fallbacks": 0})
            if not isinstance(item, dict):
                item = {"hits": 0, "misses": 0, "errors": 0, "bypass": 0, "stale_fallbacks": 0}
                namespaces[namespace] = item
            counter_key = {"hit": "hits", "miss": "misses", "error": "errors", "bypass": "bypass", "stale": "stale_fallbacks"}[event]
            try:
                current_count = int(item.get(counter_key, 0))
            except (TypeError, ValueError):
                current_count = 0
            item[counter_key] = current_count + 1
            item["last_event_at"] = dt.datetime.now(dt.timezone.utc).isoformat()
            payload["updated_at"] = item["last_event_at"]
            try:
                _write_cache_stats(payload)
            except OSError:
                return


def _cache_marker(payload: object) -> dict[str, Any]:
    """Expose stale-cache provenance to quality/report layers without secrets."""
    marker = payload.get("_radar_cache") if isinstance(payload, dict) else None
    if not isinstance(marker, dict) or marker.get("status") != "stale_fallback":
        return {}
    result: dict[str, Any] = {"cache_status": "stale_fallback"}
    try:
        result["cache_age_seconds"] = max(0, int(marker.get("age_seconds", 0)))
    except (TypeError, ValueError):
        pass
    return result


def _provider_rate_limit_message(payload: object) -> str | None:
    """Return a provider message that is safe to retry after a short backoff."""
    if not isinstance(payload, dict):
        return None
    candidates: list[str] = []
    for key in ("Note", "Information", "error_message"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            candidates.append(value.strip())
    status = payload.get("status")
    if isinstance(status, dict):
        value = status.get("error_message")
        if isinstance(value, str) and value.strip():
            candidates.append(value.strip())
        error_code = status.get("error_code")
        if error_code in {1008, 1009, 1010, 1011, 1012}:
            candidates.append(f"CoinMarketCap error_code {error_code}")
    message = " | ".join(dict.fromkeys(candidates))
    if not message:
        return None
    lowered = message.lower()
    retry_markers = (
        "rate limit",
        "rate-limit",
        "requests per",
        "spread out",
        "too many",
        "quota",
        "error_code 1008",
        "error_code 1009",
        "error_code 1010",
        "error_code 1011",
        "error_code 1012",
    )
    return message if any(marker in lowered for marker in retry_markers) else None


def http_json(
    url: str,
    extra_headers: dict[str, str] | None = None,
    *,
    config: dict[str, Any] | None = None,
    namespace: str = "",
) -> Any:
    cooldown = _provider_cooldown_remaining(namespace)
    if cooldown:
        raise RuntimeError(f"provider {namespace} em cooldown local por mais {cooldown}s após rate limit")
    headers = {"User-Agent": "sector-momentum-radar/0.1", **(extra_headers or {})}
    last_error: Exception | None = None
    for attempt in range(3):
        request = urllib.request.Request(url, headers=headers)
        try:
            _reserve_provider_call(namespace, config)
            _wait_for_rate_limit(config, namespace)
            with urllib.request.urlopen(request, timeout=20) as response:
                payload = json.loads(response.read().decode("utf-8"))
                provider_message = _provider_rate_limit_message(payload)
                if not provider_message:
                    return payload
                last_error = RuntimeError(f"provider rate limit: {provider_message}")
                if attempt < 2:
                    time.sleep(5.0 * (attempt + 1))
                    continue
                _record_provider_cooldown(namespace, config, "rate_limit")
                break
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError) as exc:
            if isinstance(exc, urllib.error.HTTPError):
                try:
                    detail = exc.read().decode("utf-8", errors="replace").strip().replace("\n", " ")[:300]
                except Exception:  # noqa: BLE001 - diagnostic detail must not hide the original error
                    detail = ""
                last_error = RuntimeError(f"HTTP {exc.code}{': ' + detail if detail else ''}")
            else:
                last_error = exc
            if attempt == 2 and isinstance(exc, urllib.error.HTTPError) and exc.code == 429:
                _record_provider_cooldown(namespace, config, "http_429")
            if attempt < 2:
                retry_after = None
                if isinstance(exc, urllib.error.HTTPError):
                    retry_after = exc.headers.get("Retry-After")
                try:
                    delay = float(retry_after) if retry_after else 0.0
                except (TypeError, ValueError):
                    delay = 0.0
                if not delay:
                    delay = 5.0 * (attempt + 1) if isinstance(exc, urllib.error.HTTPError) and exc.code == 429 else 1.0 + attempt * 2
                time.sleep(delay)
    raise RuntimeError(f"falha HTTP depois de 3 tentativas: {safe_error_message(last_error)}")


def cached_http_json(url: str, config: dict[str, Any], namespace: str, extra_headers: dict[str, str] | None = None) -> Any:
    cache_config = config.get("cache", {})
    if not cache_config.get("enabled", True):
        _record_cache_event(namespace, "bypass")
        return http_json(url, extra_headers, config=config, namespace=namespace)
    cache_root = DATA_DIR / "cache" / namespace
    cache_root.mkdir(parents=True, exist_ok=True)
    cache_file = _cache_file_for_url(namespace, url)
    ttl = _cache_ttl(config, namespace)
    # A live analysis can be requested twice from the UI while the first call
    # is still running. The per-resource lock turns that into one provider call.
    with _cache_lock(cache_file):
        if cache_file.exists() and (dt.datetime.now().timestamp() - cache_file.stat().st_mtime) <= ttl:
            try:
                _record_cache_event(namespace, "hit")
                return json.loads(cache_file.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                pass
        try:
            payload = http_json(url, extra_headers, config=config, namespace=namespace)
        except Exception:
            _record_cache_event(namespace, "error")
            if cache_config.get("stale_if_error", True):
                try:
                    stale_payload = json.loads(cache_file.read_text(encoding="utf-8"))
                    age_seconds = max(0, int(dt.datetime.now().timestamp() - cache_file.stat().st_mtime))
                except (OSError, json.JSONDecodeError, ValueError):
                    stale_payload = None
                    age_seconds = 0
                if isinstance(stale_payload, dict):
                    stale_payload["_radar_cache"] = {"status": "stale_fallback", "age_seconds": age_seconds}
                    _record_cache_event(namespace, "stale")
                    return stale_payload
                if isinstance(stale_payload, list):
                    _record_cache_event(namespace, "stale")
                    return {"_radar_data": stale_payload, "_radar_cache": {"status": "stale_fallback", "age_seconds": age_seconds}}
            raise
        # Do not persist provider error envelopes (e.g. Alpha Vantage quota
        # responses). Caching those would keep live validation broken after the
        # provider's daily quota resets.
        provider_error = False
        if isinstance(payload, dict):
            provider_error = any(
                key in payload
                for key in ("Note", "Information", "error", "error_code", "error_message")
            )
            status = payload.get("status")
            if isinstance(status, dict) and status.get("error_code") not in (None, 0):
                provider_error = True
        _record_cache_event(namespace, "error" if provider_error else "miss")
        if not provider_error:
            temporary = cache_file.with_suffix(".tmp")
            temporary.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            temporary.replace(cache_file)
        return payload


def fetch_alpha_vantage(item: dict[str, Any], api_key: str, config: dict[str, Any]) -> list[dict[str, Any]]:
    alpha_config = config.get("alpha_vantage", {})
    outputsize = str(alpha_config.get("outputsize", "compact")).lower()
    if outputsize not in {"compact", "full"}:
        outputsize = "compact"
    query = urllib.parse.urlencode({
        "function": "TIME_SERIES_DAILY",
        "symbol": item["source_id"],
        "outputsize": outputsize,
        "apikey": api_key,
    })
    payload = cached_http_json(f"https://www.alphavantage.co/query?{query}", config, "alpha_vantage")
    cache_marker = _cache_marker(payload)
    series = payload.get("Time Series (Daily)")
    if not series:
        message = payload.get("Note") or payload.get("Information") or "resposta sem série diária"
        raise RuntimeError(f"Alpha Vantage não devolveu {item['symbol']}: {message}")
    rows: list[dict[str, Any]] = []
    for date_value, values in series.items():
        rows.append({
            "date": date_value,
            "symbol": item["symbol"],
            "sector": item["sector"],
            "close": float(values["4. close"]),
            "volume": float(values.get("5. volume", 0)),
            "currency": config.get("currency", "USD"),
            "source": "alpha_vantage",
            "source_id": item["source_id"],
            **cache_marker,
        })
    return sorted(rows, key=lambda row: row["date"])[-int(config.get("lookback_days", 900)):]


def fetch_tiingo(item: dict[str, Any], api_key: str, config: dict[str, Any]) -> list[dict[str, Any]]:
    """Fetch adjusted daily OHLCV history from Tiingo's EOD endpoint.

    Tiingo returns a JSON array rather than the object-shaped payloads used by
    the other providers, so the generic cache layer deliberately accepts any
    JSON value.  Adjusted close is the default because the radar is primarily
    comparing ETFs and should not treat ordinary distributions as artificial
    price drops.
    """
    tiingo_config = config.get("tiingo", {}) if isinstance(config.get("tiingo", {}), dict) else {}
    base_url = str(tiingo_config.get("base_url", "https://api.tiingo.com")).rstrip("/")
    source_id = str(item.get("source_id") or item.get("symbol") or "").strip()
    if not source_id:
        raise RuntimeError(f"Tiingo sem ticker para {item.get('symbol', 'ativo')}")
    lookback = max(30, int(config.get("lookback_days", 900)))
    end_date = dt.date.today()
    start_date = end_date - dt.timedelta(days=max(lookback * 2, 365))
    query = urllib.parse.urlencode({
        "startDate": start_date.isoformat(),
        "endDate": (end_date + dt.timedelta(days=1)).isoformat(),
        "resampleFreq": "daily",
        "format": "json",
    })
    encoded = urllib.parse.quote(source_id, safe=".-_")
    headers = {"Authorization": f"Token {api_key}", "Accept": "application/json"}
    payload = cached_http_json(f"{base_url}/tiingo/daily/{encoded}/prices?{query}", config, "tiingo", headers)
    cache_marker = _cache_marker(payload)
    if isinstance(payload, dict):
        if isinstance(payload.get("_radar_data"), list):
            payload_data = payload["_radar_data"]
        else:
            message = payload.get("detail") or payload.get("error") or payload.get("message") or "resposta sem série diária"
            raise RuntimeError(f"Tiingo não devolveu {item.get('symbol', source_id)}: {message}")
    else:
        payload_data = payload
    if not isinstance(payload_data, list):
        raise RuntimeError(f"Tiingo não devolveu uma série válida para {item.get('symbol', source_id)}")
    use_adjusted = bool(tiingo_config.get("use_adjusted_close", True))
    rows: list[dict[str, Any]] = []
    for value in payload_data:
        if not isinstance(value, dict):
            continue
        try:
            date_value = str(value.get("date", ""))[:10]
            close_key = "adjClose" if use_adjusted and value.get("adjClose") is not None else "close"
            close = float(value[close_key])
            volume_key = "adjVolume" if use_adjusted and value.get("adjVolume") is not None else "volume"
            volume = float(value.get(volume_key, 0.0) or 0.0)
            if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", date_value) or not math.isfinite(close) or close <= 0:
                continue
        except (KeyError, TypeError, ValueError):
            continue
        rows.append({
            "date": date_value,
            "symbol": item["symbol"],
            "sector": item["sector"],
            "close": close,
            "volume": volume,
            "currency": str(item.get("currency") or config.get("currency", "USD")),
            "source": "tiingo",
            "source_id": source_id,
            **cache_marker,
        })
    if not rows:
        raise RuntimeError(f"Tiingo não devolveu histórico para {item.get('symbol', source_id)}")
    return sorted(rows, key=lambda row: row["date"])[-lookback:]


def yahoo_period_window(lookback_days: int, now: dt.datetime | None = None) -> tuple[int, int]:
    """Return a stable UTC-day window so repeated runs reuse Yahoo cache."""
    current = now or dt.datetime.now(dt.timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=dt.timezone.utc)
    current = current.astimezone(dt.timezone.utc)
    period2_dt = dt.datetime.combine(current.date() + dt.timedelta(days=1), dt.time.min, tzinfo=dt.timezone.utc)
    period1_dt = period2_dt - dt.timedelta(days=max(int(lookback_days) * 2, 365))
    return int(period1_dt.timestamp()), int(period2_dt.timestamp())


def fetch_yahoo_finance(item: dict[str, Any], config: dict[str, Any]) -> list[dict[str, Any]]:
    """Fetch daily OHLCV history for global stocks and UCITS listings.

    This is a no-key fallback for portfolio instruments that are not reliably
    listed in Alpha Vantage.  It is still treated as an external source: the
    UI labels it and the report records the source, while on-demand analysis
    avoids spending the paid provider quota on every imported position.
    """
    source_id = str(item.get("source_id") or item.get("symbol") or "").strip()
    if not source_id:
        raise RuntimeError(f"Yahoo Finance sem símbolo para {item.get('symbol', 'ativo')}")
    lookback = max(30, int(config.get("lookback_days", 900)))
    period1, period2 = yahoo_period_window(lookback)
    query = urllib.parse.urlencode({
        "period1": period1,
        "period2": period2,
        "interval": "1d",
        "events": "history",
        "includeAdjustedClose": "true",
    })
    encoded = urllib.parse.quote(source_id, safe=".-")
    payload = cached_http_json(f"https://query1.finance.yahoo.com/v8/finance/chart/{encoded}?{query}", config, "yahoo_finance")
    cache_marker = _cache_marker(payload)
    chart = payload.get("chart", {}) if isinstance(payload, dict) else {}
    error = chart.get("error") if isinstance(chart, dict) else None
    if error:
        message = error.get("description") if isinstance(error, dict) else error
        raise RuntimeError(f"Yahoo Finance não devolveu {item.get('symbol', source_id)}: {message}")
    results = chart.get("result", []) if isinstance(chart, dict) else []
    result = results[0] if results else {}
    timestamps = result.get("timestamp", []) if isinstance(result, dict) else []
    quote = ((result.get("indicators", {}) or {}).get("quote", []) or [{}])[0] if isinstance(result, dict) else {}
    closes = quote.get("close", []) if isinstance(quote, dict) else []
    volumes = quote.get("volume", []) if isinstance(quote, dict) else []
    meta = result.get("meta", {}) if isinstance(result, dict) else {}
    currency = str(meta.get("currency") or item.get("currency") or config.get("currency", "USD"))
    rows: list[dict[str, Any]] = []
    for index, timestamp in enumerate(timestamps):
        try:
            close = float(closes[index])
            if not math.isfinite(close) or close <= 0:
                continue
            date_value = dt.datetime.fromtimestamp(int(timestamp), tz=dt.timezone.utc).date().isoformat()
            volume = float(volumes[index] or 0.0) if index < len(volumes) else 0.0
        except (IndexError, TypeError, ValueError, OverflowError):
            continue
        rows.append({
            "date": date_value,
            "symbol": item["symbol"],
            "sector": item["sector"],
            "close": close,
            "volume": volume,
            "currency": currency,
            "source": "yahoo_finance",
            "source_id": source_id,
            **cache_marker,
        })
    if not rows:
        raise RuntimeError(f"Yahoo Finance não devolveu histórico para {item.get('symbol', source_id)}")
    return sorted(rows, key=lambda row: row["date"])[-lookback:]


def fetch_coinmarketcap_batch(items: list[dict[str, Any]], config: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    """Fetch several crypto histories in one bundled CoinMarketCap request."""
    api_key = os.environ.get("COINMARKETCAP_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("defina COINMARKETCAP_API_KEY")
    items = [item for item in items if isinstance(item, dict)]
    if not items:
        return {}
    cmc_config = config.get("coinmarketcap", {})
    source_ids = list(dict.fromkeys(str(item.get("source_id", "")) for item in items))
    if any(not source_id.isdigit() for source_id in source_ids):
        raise RuntimeError("CoinMarketCap precisa de IDs numéricos")
    lookback = max(1, int(config.get("lookback_days", 900)))
    max_history_days = max(1, int(cmc_config.get("max_history_days", 365)))
    query = urllib.parse.urlencode({
        "id": ",".join(source_ids),
        "count": min(lookback, max_history_days),
        "interval": "daily",
        "convert": "USD",
    })
    base_url = str(cmc_config.get("base_url", "https://pro-api.coinmarketcap.com")).rstrip("/")
    headers = {"Accept": "application/json", "X-CMC_PRO_API_KEY": api_key}
    payload = cached_http_json(f"{base_url}/v3/cryptocurrency/quotes/historical?{query}", config, "coinmarketcap", headers)
    cache_marker = _cache_marker(payload)
    status = payload.get("status") or {}
    if status.get("error_code") not in (None, 0):
        message = status.get("error_message") or f"erro {status.get('error_code')}"
        raise RuntimeError(f"CoinMarketCap não devolveu o lote: {message}")
    data = payload.get("data")
    assets: dict[str, dict[str, Any]] = {}
    candidates = data if isinstance(data, list) else data.values() if isinstance(data, dict) and "quotes" not in data else [data] if isinstance(data, dict) else []
    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        if candidate.get("id") is not None:
            assets[str(candidate["id"])] = candidate
        if candidate.get("symbol"):
            assets[str(candidate["symbol"]).upper()] = candidate
    if isinstance(data, dict) and "quotes" not in data:
        for key, candidate in data.items():
            if isinstance(candidate, dict):
                assets.setdefault(str(key), candidate)
    result: dict[str, list[dict[str, Any]]] = {}
    for item in items:
        source_id = str(item.get("source_id", ""))
        asset = assets.get(source_id) or assets.get(str(item.get("symbol", "")).upper()) or {}
        rows: list[dict[str, Any]] = []
        for quote in asset.get("quotes", []) if isinstance(asset, dict) else []:
            try:
                timestamp = str(quote.get("timestamp") or quote.get("time_close") or "")
                date_value = dt.datetime.fromisoformat(timestamp.replace("Z", "+00:00")).date().isoformat()
                usd = quote["quote"]["USD"]
                close = float(usd["price"])
                volume = float(usd.get("volume_24h", 0.0) or 0.0)
            except (KeyError, TypeError, ValueError):
                continue
            rows.append({"date": date_value, "symbol": item["symbol"], "sector": item["sector"], "close": close, "volume": volume, "currency": "USD", "source": "coinmarketcap", "source_id": source_id, **cache_marker})
        result[str(item["symbol"])] = sorted(rows, key=lambda row: row["date"])[-lookback:]
    return result


def fetch_coinmarketcap(item: dict[str, Any], config: dict[str, Any]) -> list[dict[str, Any]]:
    """Fetch one crypto history through the same bundled path used by full runs."""
    rows = fetch_coinmarketcap_batch([item], config).get(str(item.get("symbol", "")), [])
    if not rows:
        raise RuntimeError(f"CoinMarketCap não devolveu histórico para {item.get('symbol', 'ativo')}")
    return rows


def _news_ticker_map(config: dict[str, Any]) -> dict[str, str]:
    mapping: dict[str, str] = {}
    for item in config.get("universe", []):
        ticker = item.get("news_ticker")
        if not ticker:
            ticker = f"CRYPTO:{item['symbol']}" if item.get("provider") == "coinmarketcap" else item.get("source_id", item["symbol"])
        mapping[ticker.upper()] = item["symbol"]
    return mapping


def news_request_count(config: dict[str, Any]) -> int:
    """Count the Alpha Vantage news requests the configured ticker groups need."""
    news_config = config.get("news", {}) if isinstance(config.get("news", {}), dict) else {}
    if str(news_config.get("provider", "alpha_vantage")).lower() != "alpha_vantage":
        return 0
    ticker_map = _news_ticker_map(config)
    configured = [str(value).upper() for value in news_config.get("query_tickers", [])]
    tickers = [value for value in configured if value in ticker_map] or sorted(ticker_map)
    if not tickers:
        return 0
    market_tickers = [ticker for ticker in tickers if not ticker.startswith("CRYPTO:")]
    crypto_tickers = [ticker for ticker in tickers if ticker.startswith("CRYPTO:")]
    return sum(bool(group) for group in (market_tickers, crypto_tickers))


def _news_date(value: str) -> str:
    token = (value or "")[:15]
    try:
        return dt.datetime.strptime(token, "%Y%m%dT%H%M").date().isoformat()
    except ValueError:
        return ""


def fetch_news_sentiment(config: dict[str, Any], api_key: str) -> tuple[dict[str, float], dict[str, Any]]:
    news_config = config.get("news", {})
    ticker_map = _news_ticker_map(config)
    configured = [str(value).upper() for value in news_config.get("query_tickers", [])]
    tickers = [value for value in configured if value in ticker_map] or sorted(ticker_map)
    if not tickers:
        return {}, {"symbol": "NEWS", "source": "alpha_vantage", "rows": 0, "status": "ERRO", "message": "não há tickers configurados"}
    since = dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=float(news_config.get("lookback_hours", 72)))
    # Keep the cache key stable within an hour so repeated validations do not
    # spend another Alpha Vantage request just because the current minute changed.
    since = since.replace(minute=0, second=0, microsecond=0)
    # Alpha Vantage can reject a mixed ETF/crypto ticker list even though the
    # documentation shows mixed examples. Keep the two universes separate and
    # merge the returned articles before calculating sentiment.
    crypto_tickers = [ticker for ticker in tickers if ticker.startswith("CRYPTO:")]
    market_tickers = [ticker for ticker in tickers if not ticker.startswith("CRYPTO:")]
    ticker_groups = [group for group in (market_tickers, crypto_tickers) if group]
    feed: list[dict[str, Any]] = []
    news_cache_marker: dict[str, Any] = {}
    for ticker_group in ticker_groups:
        query = urllib.parse.urlencode({
            "function": "NEWS_SENTIMENT",
            "tickers": ",".join(ticker_group),
            "sort": "LATEST",
            "limit": int(news_config.get("limit", 100)),
            "apikey": api_key,
        })
        payload = cached_http_json(f"https://www.alphavantage.co/query?{query}", config, "news")
        news_cache_marker = news_cache_marker or _cache_marker(payload)
        group_feed = payload.get("feed")
        if group_feed is None:
            message = payload.get("Note") or payload.get("Information") or "resposta sem feed de notícias"
            raise RuntimeError(f"Alpha Vantage NEWS_SENTIMENT: {message}")
        feed.extend(group_feed)
    score_values: dict[str, list[tuple[float, float]]] = {}
    dates: list[str] = []
    for article in feed:
        article_date = _news_date(str(article.get("time_published", "")))
        if article_date and article_date < since.date().isoformat():
            continue
        if article_date:
            dates.append(article_date)
        for item in article.get("ticker_sentiment", []):
            symbol = ticker_map.get(str(item.get("ticker", "")).upper())
            if not symbol:
                continue
            try:
                score = float(item.get("ticker_sentiment_score", 0.0))
                relevance = max(float(item.get("relevance_score", 0.0)), 0.01)
            except (TypeError, ValueError):
                continue
            score_values.setdefault(symbol, []).append((score, relevance))
    scores: dict[str, float] = {}
    for symbol, values in score_values.items():
        total_weight = sum(weight for _, weight in values)
        sentiment = sum(score * weight for score, weight in values) / total_weight if total_weight else 0.0
        scores[symbol] = round(clamp(50.0 + sentiment * 50.0), 2)
    latest = max(dates) if dates else ""
    quality = {
        "symbol": "NEWS",
        "source": "alpha_vantage",
        "rows": len(feed),
        "status": "ATRASADO" if news_cache_marker else "OK",
        "latest_date": latest,
        "message": f"{len(feed)} artigos; {len(scores)} símbolos com sentimento" if not news_cache_marker else f"cache antigo usado após falha do provider; {len(feed)} artigos; {len(scores)} símbolos com sentimento",
        **news_cache_marker,
    }
    return scores, quality


def _macro_score(series_data: dict[str, list[dict[str, Any]]]) -> float:
    scores: list[float] = []
    vix = series_data.get("VIXCLS", [])
    if vix:
        scores.append(clamp(90.0 - float(vix[-1]["value"]) * 2.0))
    spread = series_data.get("T10Y2Y", [])
    if spread:
        scores.append(clamp(50.0 + float(spread[-1]["value"]) * 120.0))
    dollar = series_data.get("DTWEXBGS", [])
    if len(dollar) >= 20:
        change = float(dollar[-1]["value"]) / float(dollar[-20]["value"]) - 1.0
        scores.append(score_return(-change, scale=0.03))
    return round(statistics.mean(scores), 2) if scores else 50.0


def fetch_fred_macro(config: dict[str, Any], api_key: str) -> tuple[float, dict[str, list[dict[str, Any]]], list[dict[str, Any]]]:
    macro_config = config.get("macro", {})
    start = dt.date.today() - dt.timedelta(days=max(int(config.get("lookback_days", 900)), 365))
    series_data: dict[str, list[dict[str, Any]]] = {}
    quality: list[dict[str, Any]] = []
    for series in macro_config.get("series", []):
        series_id = str(series["id"]).upper()
        query = urllib.parse.urlencode({
            "api_key": api_key,
            "file_type": "json",
            "series_id": series_id,
            "observation_start": start.isoformat(),
            "sort_order": "asc",
        })
        try:
            headers = {"Authorization": f"Bearer {api_key}"}
            payload = cached_http_json(f"https://api.stlouisfed.org/fred/series/observations?{query}", config, "fred", headers)
            observations: list[dict[str, Any]] = []
            for item in payload.get("observations", []):
                try:
                    value = float(item["value"])
                except (KeyError, TypeError, ValueError):
                    continue
                observations.append({"date": item["date"], "value": value})
            series_data[series_id] = observations
            cache_marker = _cache_marker(payload)
            quality.append({
                "symbol": f"FRED:{series_id}",
                "source": "fred",
                "rows": len(observations),
                "status": "ATRASADO" if cache_marker else ("OK" if observations else "ERRO"),
                "latest_date": observations[-1]["date"] if observations else "",
                "message": "cache antigo usado após falha do provider" if cache_marker else ("" if observations else "sem observações numéricas"),
                **cache_marker,
            })
        except Exception as exc:  # noqa: BLE001 - one macro series must not hide the others
            quality.append({"symbol": f"FRED:{series_id}", "source": "fred", "rows": 0, "status": "ERRO", "message": safe_error_message(exc)})
    return _macro_score(series_data), series_data, quality


def _selected_universe(config: dict[str, Any], active_symbols: set[str] | None = None) -> list[dict[str, Any]]:
    """Return the configured universe or one explicit live-refresh cohort."""
    universe = config.get("universe", []) if isinstance(config.get("universe", []), list) else []
    if active_symbols is None:
        return [item for item in universe if isinstance(item, dict)]
    return [item for item in universe if isinstance(item, dict) and str(item.get("symbol", "")).upper() in active_symbols]


def configured_provider_fallbacks(config: dict[str, Any], provider: str) -> list[str]:
    """Return explicitly configured price-provider fallbacks in priority order."""
    fallback_config = config.get("provider_fallbacks", {}) if isinstance(config.get("provider_fallbacks", {}), dict) else {}
    raw = fallback_config.get(str(provider).lower(), [])
    if isinstance(raw, str):
        raw = [raw]
    if not isinstance(raw, list):
        return []
    supported = {"alpha_vantage", "tiingo", "yahoo_finance"}
    return list(dict.fromkeys(str(value).strip().lower() for value in raw if str(value).strip().lower() in supported and str(value).strip().lower() != str(provider).lower()))


def provider_requires_key(provider: str) -> str | None:
    return {
        "alpha_vantage": "ALPHAVANTAGE_API_KEY",
        "tiingo": "TIINGO_API_KEY",
        "coinmarketcap": "COINMARKETCAP_API_KEY",
    }.get(str(provider).lower())


def fetch_price_history_with_fallback(item: dict[str, Any], config: dict[str, Any], alpha_key: str, tiingo_key: str) -> tuple[list[dict[str, Any]], str, list[dict[str, str]]]:
    """Fetch one history, using only explicit fallbacks and preserving provenance."""
    requested = str(item.get("provider", "alpha_vantage")).lower()
    candidates = [requested, *configured_provider_fallbacks(config, requested)]
    failures: list[dict[str, str]] = []
    for candidate in candidates:
        try:
            candidate_item = {**item, "provider": candidate}
            if candidate == "alpha_vantage":
                if not alpha_key:
                    raise RuntimeError("defina ALPHAVANTAGE_API_KEY")
                fetched = fetch_alpha_vantage(candidate_item, alpha_key, config)
            elif candidate == "tiingo":
                if not tiingo_key:
                    raise RuntimeError("defina TIINGO_API_KEY")
                fetched = fetch_tiingo(candidate_item, tiingo_key, config)
            elif candidate == "yahoo_finance":
                fetched = fetch_yahoo_finance(candidate_item, config)
            else:
                raise RuntimeError(f"provider não suportado no modo live: {candidate}")
            if not fetched:
                raise RuntimeError("resposta sem linhas")
            return fetched, candidate, failures
        except Exception as exc:  # noqa: BLE001 - retain the primary failure for the quality report
            failures.append({"provider": candidate, "message": safe_error_message(exc)})
    detail = "; ".join(f"{item['provider']}: {item['message']}" for item in failures)
    raise RuntimeError(detail or f"nenhum provider disponível para {item.get('symbol', 'ativo')}")


def fetch_live_data(config: dict[str, Any], active_symbols: set[str] | None = None, previous_payload: dict[str, Any] | None = None) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    quality: list[dict[str, Any]] = []
    context: dict[str, Any] = {"news_scores": {}, "macro_score": 50.0, "macro_series": {}, "news_available": False, "macro_available": False}
    alpha_key = os.environ.get("ALPHAVANTAGE_API_KEY", "").strip()
    tiingo_key = os.environ.get("TIINGO_API_KEY", "").strip()
    universe = _selected_universe(config, active_symbols)
    coinmarketcap_items = [item for item in universe if str(item.get("provider", "")).lower() == "coinmarketcap"]
    coinmarketcap_rows: dict[str, list[dict[str, Any]]] = {}
    coinmarketcap_error: str | None = None
    if coinmarketcap_items:
        try:
            coinmarketcap_rows = fetch_coinmarketcap_batch(coinmarketcap_items, config)
        except Exception as exc:  # noqa: BLE001 - expose the batch failure per symbol
            coinmarketcap_error = safe_error_message(exc)
    for item in universe:
        try:
            requested_provider = str(item.get("provider", "alpha_vantage")).lower()
            if requested_provider != "coinmarketcap":
                fetched, used_provider, fallback_failures = fetch_price_history_with_fallback(item, config, alpha_key, tiingo_key)
                rows.extend(fetched)
                cache_fallback = next((row for row in fetched if row.get("cache_status") == "stale_fallback"), None)
                fallback_used = used_provider != requested_provider
                provenance = f"fallback {requested_provider} -> {used_provider}" if fallback_used else ""
                if fallback_failures:
                    provenance = f"{provenance}; falha primária: {fallback_failures[0]['message']}" if provenance else fallback_failures[0]["message"]
                if cache_fallback:
                    provenance = f"{provenance}; cache antigo usado após falha do provider" if provenance else "cache antigo usado após falha do provider"
                quality.append({"symbol": item["symbol"], "source": used_provider, "rows": len(fetched), "status": "ATRASADO" if cache_fallback else "OK", "message": provenance, "provider_requested": requested_provider, "provider_used": used_provider, "fallback_used": fallback_used, **({"cache_status": "stale_fallback", "cache_age_seconds": cache_fallback.get("cache_age_seconds")} if cache_fallback else {})})
                continue
            provider = item.get("provider", "alpha_vantage")
            if provider == "coinmarketcap":
                if coinmarketcap_error:
                    raise RuntimeError(coinmarketcap_error)
                fetched = coinmarketcap_rows.get(str(item.get("symbol", "")), [])
                if not fetched:
                    raise RuntimeError(f"CoinMarketCap não devolveu histórico para {item.get('symbol', 'ativo')}")
            elif provider == "alpha_vantage":
                if not alpha_key:
                    raise RuntimeError("defina ALPHAVANTAGE_API_KEY")
                fetched = fetch_alpha_vantage(item, alpha_key, config)
            elif provider == "tiingo":
                if not tiingo_key:
                    raise RuntimeError("defina TIINGO_API_KEY")
                fetched = fetch_tiingo(item, tiingo_key, config)
            elif provider == "yahoo_finance":
                fetched = fetch_yahoo_finance(item, config)
            else:
                raise RuntimeError(f"provider não suportado no modo live: {provider}")
            rows.extend(fetched)
            cache_fallback = next((row for row in fetched if row.get("cache_status") == "stale_fallback"), None)
            quality.append({"symbol": item["symbol"], "source": fetched[0]["source"] if fetched else provider, "rows": len(fetched), "status": "ATRASADO" if cache_fallback else ("OK" if fetched else "ERRO"), "message": "cache antigo usado após falha do provider" if cache_fallback else ("" if fetched else "resposta sem linhas"), **({"cache_status": "stale_fallback", "cache_age_seconds": cache_fallback.get("cache_age_seconds")} if cache_fallback else {})})
        except Exception as exc:  # noqa: BLE001 - one bad provider must be visible, not hide other assets
            quality.append({"symbol": item["symbol"], "source": item.get("provider", ""), "rows": 0, "status": "ERRO", "message": safe_error_message(exc)})
    if config.get("news", {}).get("provider") == "alpha_vantage":
        if alpha_key:
            try:
                context["news_scores"], news_quality = fetch_news_sentiment(config, alpha_key)
                context["news_available"] = news_quality.get("status") == "OK"
                quality.append(news_quality)
            except Exception as exc:  # noqa: BLE001
                quality.append({"symbol": "NEWS", "source": "alpha_vantage", "rows": 0, "status": "ERRO", "message": safe_error_message(exc)})
        else:
            quality.append({"symbol": "NEWS", "source": "alpha_vantage", "rows": 0, "status": "ERRO", "message": "defina ALPHAVANTAGE_API_KEY para notícias"})
    fred_key = os.environ.get("FRED_API_KEY", "").strip()
    if config.get("macro", {}).get("provider") == "fred":
        if fred_key:
            try:
                context["macro_score"], context["macro_series"], macro_quality = fetch_fred_macro(config, fred_key)
                context["macro_available"] = bool(macro_quality) and all(row.get("status") == "OK" for row in macro_quality)
                quality.extend(macro_quality)
            except Exception as exc:  # noqa: BLE001
                quality.append({"symbol": "MACRO", "source": "fred", "rows": 0, "status": "ERRO", "message": safe_error_message(exc)})
        else:
            quality.append({"symbol": "MACRO", "source": "fred", "rows": 0, "status": "ERRO", "message": "defina FRED_API_KEY para macro"})
    # Fetch the benchmark even if all sector requests failed. This keeps the
    # quality report honest and isolates a sector error from the benchmark gate.
    benchmark_config = config.get("benchmark", {}) if isinstance(config.get("benchmark", {}), dict) else {}
    benchmark_provider = str(benchmark_config.get("provider", "alpha_vantage")).lower()
    global_item = {
        "symbol": "GLOBAL",
        "sector": "Benchmark global",
        "provider": benchmark_provider,
        "source_id": str(benchmark_config.get("source_id", "SPY")),
    }
    try:
        requested_benchmark_provider = benchmark_provider
        benchmark_rows, benchmark_used_provider, benchmark_fallback_failures = fetch_price_history_with_fallback(global_item, config, alpha_key, tiingo_key)
        benchmark_provider = benchmark_used_provider
        rows.extend(benchmark_rows)
        global_rows = [r for r in rows if r["symbol"] == "GLOBAL"]
        global_fallback = next((row for row in global_rows if row.get("cache_status") == "stale_fallback"), None)
        quality.append({"symbol": "GLOBAL", "source": benchmark_provider, "rows": len(global_rows), "status": "ATRASADO" if global_fallback else "OK", "message": "cache antigo usado após falha do provider" if global_fallback else "", **({"cache_status": "stale_fallback", "cache_age_seconds": global_fallback.get("cache_age_seconds")} if global_fallback else {})})
        if quality and quality[-1].get("symbol") == "GLOBAL":
            quality[-1].update({"provider_requested": requested_benchmark_provider, "provider_used": benchmark_used_provider, "fallback_used": benchmark_used_provider != requested_benchmark_provider})
            if benchmark_fallback_failures:
                quality[-1]["message"] = f"fallback {requested_benchmark_provider} -> {benchmark_used_provider}; falha primária: {benchmark_fallback_failures[0]['message']}"
    except Exception as exc:  # noqa: BLE001
        quality.append({"symbol": "GLOBAL", "source": benchmark_provider, "rows": 0, "status": "ERRO", "message": safe_error_message(exc)})
    if active_symbols is not None:
        previous = previous_payload if isinstance(previous_payload, dict) else {}
        previous_live = str(previous.get("meta", {}).get("mode", "")).lower() == "live"
        previous_history = previous.get("history", []) if previous_live and isinstance(previous.get("history", []), list) else []
        active_set = {str(item.get("symbol", "")).upper() for item in universe}
        stale_items = [item for item in config.get("universe", []) if isinstance(item, dict) and str(item.get("symbol", "")).upper() not in active_set]
        stale_symbols = {str(item.get("symbol", "")).upper() for item in stale_items}
        stale_rows = [row for row in previous_history if isinstance(row, dict) and str(row.get("symbol", "")).upper() in stale_symbols]
        rows.extend(stale_rows)
        previous_quality = {str(item.get("symbol", "")).upper(): item for item in previous.get("quality", []) if isinstance(item, dict)}
        for item in stale_items:
            symbol = str(item.get("symbol", "")).upper()
            count = sum(1 for row in stale_rows if str(row.get("symbol", "")).upper() == symbol)
            if count:
                prior = previous_quality.get(symbol, {})
                quality.append({"symbol": symbol, "source": prior.get("source", item.get("provider", "")), "rows": count, "status": "ATRASADO", "message": "fora da coorte atual; ultima leitura local reutilizada", "cache_status": "cohort_fallback"})
            else:
                quality.append({"symbol": symbol, "source": item.get("provider", ""), "rows": 0, "status": "FORA_DA_COORTE", "message": "ainda não visitado; será incluído numa ronda futura"})
    return rows, quality, context


def effective_provider_for_plan(config: dict[str, Any], provider: str) -> str:
    """Mirror runtime fallback routing in the no-network pre-flight."""
    requested = str(provider).lower()
    key_name = provider_requires_key(requested)
    primary_unavailable = bool(key_name and not os.environ.get(key_name, "").strip()) or bool(_provider_cooldown_remaining(requested))
    if not primary_unavailable:
        return requested
    for fallback in configured_provider_fallbacks(config, requested):
        fallback_key = provider_requires_key(fallback)
        if fallback_key and not os.environ.get(fallback_key, "").strip():
            continue
        if _provider_cooldown_remaining(fallback):
            continue
        return fallback
    return requested


def _live_request_specs(config: dict[str, Any], active_symbols: set[str] | None = None) -> list[tuple[str, str]]:
    """Build the exact credential-free cache identities used by a full live run."""
    specs: list[tuple[str, str]] = []
    universe = _selected_universe(config, active_symbols)
    alpha_config = config.get("alpha_vantage", {}) if isinstance(config.get("alpha_vantage", {}), dict) else {}
    outputsize = str(alpha_config.get("outputsize", "compact")).lower()
    if outputsize not in {"compact", "full"}:
        outputsize = "compact"
    for item in universe:
        provider = effective_provider_for_plan(config, str(item.get("provider", "alpha_vantage")))
        if provider == "alpha_vantage":
            symbol = str(item.get("source_id") or item.get("symbol") or "")
            query = urllib.parse.urlencode({"function": "TIME_SERIES_DAILY", "symbol": symbol, "outputsize": outputsize, "apikey": "__redacted__"})
            specs.append(("alpha_vantage", f"https://www.alphavantage.co/query?{query}"))
        elif provider == "tiingo" and (item.get("source_id") or item.get("symbol")):
            tiingo = config.get("tiingo", {}) if isinstance(config.get("tiingo", {}), dict) else {}
            base_url = str(tiingo.get("base_url", "https://api.tiingo.com")).rstrip("/")
            end_date = dt.date.today()
            start_date = end_date - dt.timedelta(days=max(int(config.get("lookback_days", 900)) * 2, 365))
            query = urllib.parse.urlencode({"startDate": start_date.isoformat(), "endDate": (end_date + dt.timedelta(days=1)).isoformat(), "resampleFreq": "daily", "format": "json"})
            source_id = urllib.parse.quote(str(item.get("source_id") or item.get("symbol")), safe=".-_")
            specs.append(("tiingo", f"{base_url}/tiingo/daily/{source_id}/prices?{query}"))
        elif provider == "yahoo_finance" and (item.get("source_id") or item.get("symbol")):
            period1, period2 = yahoo_period_window(max(30, int(config.get("lookback_days", 900))))
            query = urllib.parse.urlencode({"period1": period1, "period2": period2, "interval": "1d", "events": "history", "includeAdjustedClose": "true"})
            source_id = urllib.parse.quote(str(item.get("source_id") or item.get("symbol")), safe=".-")
            specs.append(("yahoo_finance", f"https://query1.finance.yahoo.com/v8/finance/chart/{source_id}?{query}"))
    crypto_items = [item for item in universe if str(item.get("provider", "")).lower() == "coinmarketcap"]
    if crypto_items:
        ids = ",".join(dict.fromkeys(str(item.get("source_id", "")) for item in crypto_items))
        cmc = config.get("coinmarketcap", {}) if isinstance(config.get("coinmarketcap", {}), dict) else {}
        count = min(max(1, int(config.get("lookback_days", 900))), max(1, int(cmc.get("max_history_days", 365))))
        query = urllib.parse.urlencode({"id": ids, "count": count, "interval": "daily", "convert": "USD"})
        base_url = str(cmc.get("base_url", "https://pro-api.coinmarketcap.com")).rstrip("/")
        specs.append(("coinmarketcap", f"{base_url}/v3/cryptocurrency/quotes/historical?{query}"))
    benchmark = config.get("benchmark", {}) if isinstance(config.get("benchmark", {}), dict) else {}
    benchmark_provider = effective_provider_for_plan(config, str(benchmark.get("provider", "alpha_vantage")))
    benchmark_symbol = str(benchmark.get("source_id", "SPY"))
    if benchmark_provider == "tiingo":
        tiingo = config.get("tiingo", {}) if isinstance(config.get("tiingo", {}), dict) else {}
        base_url = str(tiingo.get("base_url", "https://api.tiingo.com")).rstrip("/")
        end_date = dt.date.today()
        start_date = end_date - dt.timedelta(days=max(int(config.get("lookback_days", 900)) * 2, 365))
        query = urllib.parse.urlencode({"startDate": start_date.isoformat(), "endDate": (end_date + dt.timedelta(days=1)).isoformat(), "resampleFreq": "daily", "format": "json"})
        encoded = urllib.parse.quote(benchmark_symbol, safe=".-_")
        specs.append(("tiingo", f"{base_url}/tiingo/daily/{encoded}/prices?{query}"))
    elif benchmark_provider == "yahoo_finance":
        period1, period2 = yahoo_period_window(max(30, int(config.get("lookback_days", 900))))
        query = urllib.parse.urlencode({"period1": period1, "period2": period2, "interval": "1d", "events": "history", "includeAdjustedClose": "true"})
        encoded = urllib.parse.quote(benchmark_symbol, safe=".-_")
        specs.append(("yahoo_finance", f"https://query1.finance.yahoo.com/v8/finance/chart/{encoded}?{query}"))
    else:
        benchmark_query = urllib.parse.urlencode({"function": "TIME_SERIES_DAILY", "symbol": benchmark_symbol, "outputsize": outputsize, "apikey": "__redacted__"})
        specs.append(("alpha_vantage", f"https://www.alphavantage.co/query?{benchmark_query}"))
    news = config.get("news", {}) if isinstance(config.get("news", {}), dict) else {}
    if str(news.get("provider", "")).lower() == "alpha_vantage":
        ticker_map = _news_ticker_map(config)
        configured = [str(value).upper() for value in news.get("query_tickers", [])]
        tickers = [value for value in configured if value in ticker_map] or sorted(ticker_map)
        groups = [[ticker for ticker in tickers if not ticker.startswith("CRYPTO:")], [ticker for ticker in tickers if ticker.startswith("CRYPTO:")]]
        for group in (group for group in groups if group):
            query = urllib.parse.urlencode({"function": "NEWS_SENTIMENT", "tickers": ",".join(group), "sort": "LATEST", "limit": int(news.get("limit", 100)), "apikey": "__redacted__"})
            specs.append(("news", f"https://www.alphavantage.co/query?{query}"))
    macro = config.get("macro", {}) if isinstance(config.get("macro", {}), dict) else {}
    if str(macro.get("provider", "")).lower() == "fred":
        start = dt.date.today() - dt.timedelta(days=max(int(config.get("lookback_days", 900)), 365))
        for series in macro.get("series", []) if isinstance(macro.get("series", []), list) else []:
            if not isinstance(series, dict) or not series.get("id"):
                continue
            query = urllib.parse.urlencode({"api_key": "__redacted__", "file_type": "json", "series_id": str(series["id"]).upper(), "observation_start": start.isoformat(), "sort_order": "asc"})
            specs.append(("fred", f"https://api.stlouisfed.org/fred/series/observations?{query}"))
    return specs


def live_network_plan(config: dict[str, Any], active_symbols: set[str] | None = None) -> dict[str, Any]:
    """Estimate live cost and local protections without touching the network."""
    provider_counts: dict[str, int] = {}
    namespaces: set[str] = set()
    required_keys: set[str] = set()
    universe = _selected_universe(config, active_symbols)
    for item in universe:
        provider = str(item.get("provider", "alpha_vantage")).lower()
        if provider == "alpha_vantage":
            if not any(fallback == "yahoo_finance" for fallback in configured_provider_fallbacks(config, provider)):
                required_keys.add("ALPHAVANTAGE_API_KEY")
        elif provider == "tiingo":
            if not any(fallback == "yahoo_finance" for fallback in configured_provider_fallbacks(config, provider)):
                required_keys.add("TIINGO_API_KEY")
        elif provider == "coinmarketcap":
            required_keys.add("COINMARKETCAP_API_KEY")
    if str(config.get("news", {}).get("provider", "")).lower() == "alpha_vantage":
        required_keys.add("ALPHAVANTAGE_API_KEY")
    macro = config.get("macro", {}) if isinstance(config.get("macro", {}), dict) else {}
    if str(macro.get("provider", "")).lower() == "fred":
        required_keys.add("FRED_API_KEY")
    benchmark_provider = str((config.get("benchmark", {}) if isinstance(config.get("benchmark", {}), dict) else {}).get("provider", "alpha_vantage")).lower()
    if benchmark_provider == "alpha_vantage":
        if not any(fallback == "yahoo_finance" for fallback in configured_provider_fallbacks(config, benchmark_provider)):
            required_keys.add("ALPHAVANTAGE_API_KEY")
    elif benchmark_provider == "tiingo":
        if not any(fallback == "yahoo_finance" for fallback in configured_provider_fallbacks(config, benchmark_provider)):
            required_keys.add("TIINGO_API_KEY")
    request_specs = _live_request_specs(config, active_symbols)
    unique_request_specs = list(dict.fromkeys(request_specs))
    for namespace, _url in request_specs:
        provider_counts[namespace] = provider_counts.get(namespace, 0) + 1
        namespaces.add(namespace)

    planned_by_bucket: dict[str, int] = {}
    for provider, count in provider_counts.items():
        bucket = _provider_bucket(provider)
        planned_by_bucket[bucket] = planned_by_bucket.get(bucket, 0) + count
    stats = read_cache_stats()
    today = dt.datetime.now(dt.timezone.utc).date().isoformat()
    fresh_files: dict[str, int] = {}
    for namespace in sorted(namespaces):
        ttl = _cache_ttl(config, namespace)
        cache_root = DATA_DIR / "cache" / namespace
        count = 0
        if cache_root.is_dir():
            for cache_file in cache_root.glob("*.json"):
                try:
                    if dt.datetime.now().timestamp() - cache_file.stat().st_mtime <= ttl:
                        count += 1
                except OSError:
                    continue
        fresh_files[namespace] = count
    fresh_request_counts: dict[str, int] = {}
    unique_provider_counts: dict[str, int] = {}
    for namespace, _url in unique_request_specs:
        unique_provider_counts[namespace] = unique_provider_counts.get(namespace, 0) + 1
    for namespace, url in unique_request_specs:
        if _cache_request_is_fresh(config, namespace, url):
            fresh_request_counts[namespace] = fresh_request_counts.get(namespace, 0) + 1
    estimated_by_provider = {
        provider: max(0, unique_provider_counts.get(provider, 0) - fresh_request_counts.get(provider, 0))
        for provider in unique_provider_counts
    }
    estimated_by_bucket: dict[str, int] = {}
    avoided_by_bucket: dict[str, int] = {}
    for provider, count in provider_counts.items():
        bucket = _provider_bucket(provider)
        estimated_by_bucket[bucket] = estimated_by_bucket.get(bucket, 0) + estimated_by_provider.get(provider, count)
        avoided_by_bucket[bucket] = avoided_by_bucket.get(bucket, 0) + fresh_request_counts.get(provider, 0)
    daily_rows: list[dict[str, Any]] = []
    network_config = config.get("network", {}) if isinstance(config.get("network", {}), dict) else {}
    budgets = network_config.get("daily_call_budgets", {})
    budgets = budgets if isinstance(budgets, dict) else {}
    reserves = network_config.get("daily_call_reserves", {})
    reserves = reserves if isinstance(reserves, dict) else {}
    daily_calls = stats.get("daily_calls", {}) if isinstance(stats, dict) else {}
    for bucket in sorted(set(planned_by_bucket) | {str(key).lower() for key in budgets}):
        usage = daily_calls.get(bucket, {}) if isinstance(daily_calls, dict) and isinstance(daily_calls.get(bucket, {}), dict) else {}
        used = int(usage.get("calls", 0)) if usage.get("date") == today else 0
        raw_limit = budgets.get(bucket)
        try:
            limit = None if raw_limit is None or str(raw_limit).strip().lower() in {"", "none", "unlimited"} else max(0, int(raw_limit))
        except (TypeError, ValueError):
            limit = None
        remaining = None if limit is None else max(0, limit - used)
        planned = estimated_by_bucket.get(bucket, 0)
        raw_reserve = reserves.get(bucket, 0)
        try:
            reserve = max(0, int(raw_reserve))
        except (TypeError, ValueError):
            reserve = 0
        if limit is not None:
            reserve = min(reserve, limit)
        safe_remaining = max(0, remaining - reserve) if remaining is not None else None
        daily_rows.append({"provider": bucket, "used_today": used, "limit": limit, "remaining": remaining, "planned": planned, "gross_planned": planned_by_bucket.get(bucket, 0), "cache_avoided": avoided_by_bucket.get(bucket, 0), "reserve": reserve, "safe_remaining": safe_remaining, "shortfall": max(0, planned - safe_remaining) if safe_remaining is not None else 0})
    quota_advice: dict[str, Any] = {}
    alpha_row = next((row for row in daily_rows if row.get("provider") == "alpha_vantage"), None)
    if alpha_row and alpha_row.get("limit") is not None:
        alpha_market_requests = unique_provider_counts.get("alpha_vantage", 0)
        alpha_news_requests = unique_provider_counts.get("news", 0)
        alpha_safe_headroom = int(alpha_row.get("safe_remaining") or 0)
        safe_full_refreshes = max(0, alpha_safe_headroom // (alpha_market_requests + alpha_news_requests)) if alpha_market_requests else 0
        safe_full_refreshes_with_daily_news_cache = max(0, (alpha_safe_headroom - alpha_news_requests) // alpha_market_requests) if alpha_market_requests else 0
        max_market_requests = max(0, alpha_safe_headroom - alpha_news_requests)
        max_asset_requests = max(0, max_market_requests - 1)
        rotation_days = max(1, math.ceil(alpha_market_requests / max_market_requests)) if max_market_requests else None
        if max_market_requests == 0:
            recommendation = "Sem margem segura para uma ronda nova; usa cache e aguarda o reset UTC."
        elif int(alpha_row.get("planned", 0)) > alpha_safe_headroom:
            recommendation = f"Usa rotação: uma coorte segura comporta até {max_asset_requests} ativos Alpha além do benchmark."
        else:
            recommendation = f"A ronda prevista cabe com margem; mantém {int(alpha_row.get('reserve', 0))} chamadas para retries."
        quota_advice["alpha_vantage"] = {
            "limit": alpha_row.get("limit"),
            "used_today": alpha_row.get("used_today", 0),
            "remaining_before_plan": alpha_row.get("remaining"),
            "reserve": alpha_row.get("reserve", 0),
            "safe_headroom": alpha_safe_headroom,
            "market_requests_per_full_refresh": alpha_market_requests,
            "news_requests_per_full_refresh": alpha_news_requests,
            "safe_full_refreshes_with_news": safe_full_refreshes,
            "safe_full_refreshes_with_news_once_daily": safe_full_refreshes_with_daily_news_cache,
            "max_market_requests_in_safe_cohort": max_market_requests,
            "max_assets_in_safe_cohort": max_asset_requests,
            "estimated_rotation_days": rotation_days,
            "recommendation": recommendation,
        }
    cooldowns = stats.get("cooldowns", {}) if isinstance(stats, dict) else {}
    active_cooldowns = []
    if isinstance(cooldowns, dict):
        for provider, item in cooldowns.items():
            if not isinstance(item, dict):
                continue
            try:
                remaining = max(0, int(dt.datetime.fromisoformat(str(item.get("until", "")).replace("Z", "+00:00")).timestamp() - dt.datetime.now(dt.timezone.utc).timestamp()))
            except (TypeError, ValueError, OverflowError):
                remaining = 0
            if remaining:
                active_cooldowns.append({"provider": provider, "remaining_seconds": remaining, "reason": item.get("reason", "")})
    missing_keys = sorted(name for name in required_keys if not os.environ.get(name, "").strip())
    blocked_reasons = []
    if missing_keys:
        blocked_reasons.append(f"chaves em falta: {', '.join(missing_keys)}")
    if any(row["shortfall"] for row in daily_rows):
        blocked_reasons.append("orçamento diário insuficiente")
    if active_cooldowns:
        blocked_reasons.append("provider em cooldown local")
    return {
        "mode": "live",
        "network_allowed": not blocked_reasons,
        "planned_calls_by_provider": dict(sorted(provider_counts.items())),
        "planned_calls_by_quota_bucket": dict(sorted(planned_by_bucket.items())),
        "estimated_total_calls": sum(provider_counts.values()),
        "estimated_network_calls": sum(estimated_by_provider.values()),
        "deduplicated_requests": len(request_specs) - len(unique_request_specs),
        "estimated_network_calls_by_provider": dict(sorted(estimated_by_provider.items())),
        "estimated_network_calls_by_quota_bucket": dict(sorted(estimated_by_bucket.items())),
        "cache_avoided_calls": sum(fresh_request_counts.values()),
        "cache_avoided_calls_by_provider": dict(sorted(fresh_request_counts.items())),
        "fresh_cache_files_by_namespace": fresh_files,
        "daily_budgets": daily_rows,
        "quota_advice": quota_advice,
        "cooldowns": active_cooldowns,
        "keys": [{"name": name, "configured": name not in missing_keys} for name in sorted(required_keys)],
        "missing_keys": missing_keys,
        "blocked_reasons": blocked_reasons,
        "message": "Nenhuma chamada foi feita; este é apenas um plano local." if not blocked_reasons else f"Bloqueado antes da rede: {'; '.join(blocked_reasons)}.",
    }


def grouped_rows(rows: Iterable[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        grouped.setdefault(row["symbol"], []).append(row)
    for values in grouped.values():
        values.sort(key=lambda row: row["date"])
    return grouped


def pct_change(values: list[float], periods: int) -> float | None:
    if len(values) <= periods:
        return None
    return values[-1] / values[-1 - periods] - 1


def mean_or(values: Iterable[float], fallback: float = 50.0) -> float:
    clean = [value for value in values if value is not None and math.isfinite(value)]
    return statistics.mean(clean) if clean else fallback


def clamp(value: float, low: float = 0.0, high: float = 100.0) -> float:
    return max(low, min(high, value))


def score_return(value: float | None, scale: float = 0.6) -> float:
    if value is None:
        return 50.0
    return clamp(50.0 + (value / scale) * 50.0)


def signal_for_index(symbol: str, index: int, grouped: dict[str, list[dict[str, Any]]], config: dict[str, Any], context: dict[str, Any] | None = None) -> dict[str, Any]:
    context = context or {}
    values = grouped[symbol][: index + 1]
    closes = [float(row["close"]) for row in values]
    volumes = [float(row.get("volume", 0)) for row in values]
    latest = values[-1]
    windows = [pct_change(closes, window) for window in (5, 20, 60, 120)]
    momentum = mean_or(score_return(value) for value in windows)
    benchmark = grouped.get("GLOBAL", [])[: index + 1]
    benchmark_closes = [float(row["close"]) for row in benchmark]
    relative_changes = []
    for window in (20, 60):
        own = pct_change(closes, window)
        base = pct_change(benchmark_closes, window)
        relative_changes.append((own or 0.0) - (base or 0.0) if own is not None and base is not None else None)
    relative_strength = mean_or(score_return(value, scale=0.5) for value in relative_changes)
    ma50 = statistics.mean(closes[-50:]) if len(closes) >= 50 else None
    ma200 = statistics.mean(closes[-200:]) if len(closes) >= 200 else None
    trend_bits = []
    if ma50 is not None:
        trend_bits.append(70.0 if closes[-1] >= ma50 else 30.0)
    if ma200 is not None:
        trend_bits.append(75.0 if closes[-1] >= ma200 else 25.0)
    if len(closes) >= 30:
        slope = closes[-1] / closes[-30] - 1
        trend_bits.append(score_return(slope, scale=0.3))
    trend = mean_or(trend_bits)
    breadth = 50.0  # One representative per theme in MVP; constitutent breadth comes later.
    volume_z = 0.0
    if len(volumes) >= 21 and statistics.pstdev(volumes[-21:-1]) > 0:
        baseline = statistics.mean(volumes[-21:-1])
        volume_z = (volumes[-1] - baseline) / statistics.pstdev(volumes[-21:-1])
    volume_score = clamp(50.0 + volume_z * 10.0)
    news = float(context.get("news_scores", {}).get(symbol, 50.0))
    macro = float(context.get("macro_score", 50.0))
    daily_returns = [closes[pos] / closes[pos - 1] - 1 for pos in range(max(1, len(closes) - 20), len(closes))]
    vol20 = statistics.pstdev(daily_returns) * math.sqrt(252) if len(daily_returns) > 1 else 0.0
    drawdown = 1 - closes[-1] / max(closes)
    risk_penalty = clamp(max(0.0, (vol20 - 0.2) * 60.0) + max(0.0, drawdown - 0.15) * 80.0, 0.0, 30.0)
    weights = config["weights"]
    score = clamp(
        momentum * weights["momentum"]
        + relative_strength * weights["relative_strength"]
        + trend * weights["trend"]
        + breadth * weights["breadth"]
        + volume_score * weights["volume"]
        + news * weights["news"]
        + macro * weights["macro"]
        - risk_penalty
    )
    components = [momentum, relative_strength, trend, breadth, volume_score, news, macro]
    agreement = clamp(100.0 - statistics.pstdev(components) * 0.8)
    data_points = len(closes)
    confidence = clamp(0.6 * agreement + 0.4 * min(100.0, data_points / 200.0 * 100.0))
    thresholds = config["thresholds"]
    if data_points < 200:
        action = "Não agir"
    elif confidence < thresholds["min_confidence"]:
        action = "Não agir"
    elif score >= thresholds["buy_score"]:
        action = "Considerar compra"
    elif score >= thresholds["hold_score"]:
        action = "Manter/observar"
    else:
        action = "Reduzir/evitar"
    drivers = []
    for label, value in [("momentum", momentum), ("força relativa", relative_strength), ("tendência", trend), ("volume", volume_score)]:
        drivers.append((value, label))
    drivers.sort(reverse=True)
    positives = ", ".join(label for value, label in drivers[:2] if value >= 60) or "sem confirmação forte"
    negatives = ", ".join(label for value, label in drivers[-2:] if value <= 45) or "risco dentro do limite"
    return {
        "date": latest["date"],
        "sector": latest["sector"],
        "symbol": symbol,
        "price": round(closes[-1], 4),
        "momentum": round(momentum, 2),
        "relative_strength": round(relative_strength, 2),
        "trend": round(trend, 2),
        "breadth": round(breadth, 2),
        "volume": round(volume_score, 2),
        "news": round(news, 2),
        "macro": round(macro, 2),
        "risk_penalty": round(risk_penalty, 2),
        "score": round(score, 2),
        "confidence": round(confidence, 2),
        "action": action,
        "volatility_annual": round(vol20, 4),
        "drawdown": round(drawdown, 4),
        "data_points": data_points,
        "source": latest.get("source", ""),
        "notes": f"A favor: {positives}. A vigiar: {negatives}.",
    }


def latest_signals(rows: list[dict[str, Any]], config: dict[str, Any], context: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    grouped = grouped_rows(rows)
    signals = []
    for symbol in sorted(grouped):
        if symbol == "GLOBAL":
            continue
        signals.append(signal_for_index(symbol, len(grouped[symbol]) - 1, grouped, config, context))
    return sorted(signals, key=lambda row: row["score"], reverse=True)


def guard_signals(signals: list[dict[str, Any]], mode: str, benchmark_available: bool, context_available: bool = True) -> list[dict[str, Any]]:
    """Block live actions when benchmark or configured news/macro context is absent."""
    if mode == "live" and (not benchmark_available or not context_available):
        for signal in signals:
            signal["action"] = "Não agir"
            reasons = []
            if not benchmark_available:
                reasons.append("mercado de comparação indisponível")
            if not context_available:
                reasons.append("notícias/ambiente económico indisponíveis")
            signal["notes"] = f"{signal['notes']} {'; '.join(reasons).capitalize()}; ação bloqueada."
    return signals


def metric_summary(equity: list[float], period_days: int, wins: int, observations: int, turnover: float = 0.0) -> dict[str, float]:
    if not equity:
        return {"total_return": 0.0, "cagr": 0.0, "max_drawdown": 0.0, "sharpe": 0.0, "win_rate": 0.0, "observations": 0, "turnover": 0.0}
    total_return = equity[-1] - 1.0
    years = max(period_days / 252.0, 1 / 252.0)
    cagr = equity[-1] ** (1 / years) - 1 if equity[-1] > 0 else -1.0
    peak = 1.0
    max_drawdown = 0.0
    for value in equity:
        peak = max(peak, value)
        max_drawdown = min(max_drawdown, value / peak - 1)
    returns = [equity[index] / equity[index - 1] - 1 for index in range(1, len(equity)) if equity[index - 1] > 0]
    sharpe = statistics.mean(returns) / statistics.pstdev(returns) * math.sqrt(252 / 5) if len(returns) > 2 and statistics.pstdev(returns) > 0 else 0.0
    return {"total_return": total_return, "cagr": cagr, "max_drawdown": max_drawdown, "sharpe": sharpe, "win_rate": wins / observations if observations else 0.0, "observations": observations, "turnover": turnover}


def backtest(rows: list[dict[str, Any]], config: dict[str, Any], start_index: int | None = None, end_index: int | None = None) -> dict[str, Any]:
    grouped = grouped_rows(rows)
    assets = [symbol for symbol in grouped if symbol != "GLOBAL"]
    if not assets or "GLOBAL" not in grouped:
        return {
            "strategy": metric_summary([], 0, 0, 0),
            "benchmark": metric_summary([], 0, 0, 0),
            "assumptions": {},
            "rows": [],
        }
    common_dates = sorted(set(row["date"] for row in grouped[assets[0]]))
    min_length = min(len(grouped[symbol]) for symbol in assets + ["GLOBAL"])
    strategy_equity = [1.0]
    benchmark_equity = [1.0]
    strategy_rows = []
    wins = benchmark_wins = 0
    observations = 0
    total_turnover = 0.0
    previous_picks: set[str] = set()
    step = int(config.get("rebalance_every_days", 5))
    forward = int(config.get("forward_days", 5))
    backtest_config = config.get("backtest", {})
    signal_delay = max(0, int(backtest_config.get("signal_delay_days", 1)))
    trading_cost_rate = max(0.0, float(backtest_config.get("commission_bps", 0.0)) + float(backtest_config.get("slippage_bps", 0.0))) / 10000.0
    first_index = max(200, int(start_index or 0))
    last_index = min_length - signal_delay - forward
    if end_index is not None:
        last_index = min(last_index, int(end_index))
    for index in range(first_index, last_index, step):
        picks = []
        for symbol in assets:
            signal = signal_for_index(symbol, index, grouped, config)
            if signal["score"] >= config["thresholds"]["buy_score"] and signal["confidence"] >= config["thresholds"]["min_confidence"]:
                picks.append(symbol)
        future_returns = []
        for symbol in assets:
            series = grouped[symbol]
            entry_index = index + signal_delay
            exit_index = entry_index + forward
            if exit_index < len(series):
                future_returns.append((symbol, series[exit_index]["close"] / series[entry_index]["close"] - 1))
        if not future_returns:
            continue
        selected = [value for symbol, value in future_returns if symbol in picks]
        gross_strategy_return = statistics.mean(selected) if selected else 0.0
        current_picks = set(picks)
        union = previous_picks | current_picks
        turnover = len(previous_picks ^ current_picks) / max(1, len(union))
        total_turnover += turnover
        strategy_cost = trading_cost_rate * turnover if turnover else 0.0
        strategy_return = gross_strategy_return - strategy_cost
        benchmark_return = statistics.mean(value for _, value in future_returns)
        strategy_equity.append(strategy_equity[-1] * (1 + strategy_return))
        benchmark_equity.append(benchmark_equity[-1] * (1 + benchmark_return))
        wins += int(strategy_return > 0)
        benchmark_wins += int(benchmark_return > 0)
        observations += 1
        strategy_rows.append({
            "date": grouped[assets[0]][index]["date"],
            "selected": ", ".join(picks),
            "turnover": round(turnover, 6),
            "gross_strategy_return": round(gross_strategy_return, 6),
            "strategy_cost": round(strategy_cost, 6),
            "strategy_return": round(strategy_return, 6),
            "benchmark_return": round(benchmark_return, 6),
            "strategy_equity": round(strategy_equity[-1], 6),
            "benchmark_equity": round(benchmark_equity[-1], 6),
        })
        previous_picks = current_picks
    period_days = max(1, len(strategy_rows) * step)
    return {
        "strategy": metric_summary(strategy_equity, period_days, wins, observations, total_turnover),
        "benchmark": metric_summary(benchmark_equity, period_days, benchmark_wins, observations),
        "assumptions": {
            "signal_delay_days": signal_delay,
            "commission_bps": float(backtest_config.get("commission_bps", 0.0)),
            "slippage_bps": float(backtest_config.get("slippage_bps", 0.0)),
            "turnover_measure": "soma da fração de ativos que entra ou sai em cada rebalanceamento",
            "execution": "entrada no preço de fecho após o atraso configurado; custos aplicados sobre a fração de ativos alterada",
        },
        "rows": strategy_rows,
    }


def walk_forward_backtest(rows: list[dict[str, Any]], config: dict[str, Any]) -> dict[str, Any]:
    """Evaluate consecutive out-of-sample windows without changing parameters.

    The current radar has fixed parameters rather than a fitted model. We still
    split the history into train-sized warmups and unseen test windows so the
    report shows how stable the rule is across different market periods.
    """
    grouped = grouped_rows(rows)
    assets = [symbol for symbol in grouped if symbol != "GLOBAL"]
    if not assets or "GLOBAL" not in grouped:
        return {"train_days": 400, "test_days": 100, "folds": [], "status": "sem dados"}
    min_length = min(len(grouped[symbol]) for symbol in assets + ["GLOBAL"])
    train_days = int(config.get("backtest", {}).get("walk_forward_train_days", 400))
    test_days = int(config.get("backtest", {}).get("walk_forward_test_days", 100))
    folds = []
    start = max(200, train_days)
    while start < min_length - 5:
        result = backtest(rows, config, start_index=start, end_index=min_length if test_days <= 0 else min(start + test_days, min_length))
        if result["strategy"]["observations"]:
            folds.append({
                "test_start": grouped[assets[0]][start]["date"],
                "test_end": grouped[assets[0]][min(start + max(1, test_days) - 1, min_length - 1)]["date"],
                "strategy": result["strategy"],
                "benchmark": result["benchmark"],
            })
        start += max(1, test_days)
    status = "ok" if folds else "amostra insuficiente"
    return {"train_days": train_days, "test_days": test_days, "folds": folds, "status": status}


def quality_rows(rows: list[dict[str, Any]], config: dict[str, Any], provider_quality: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped = grouped_rows(rows)
    provider_by_symbol = {row["symbol"]: row for row in provider_quality}
    universe = [{"symbol": "GLOBAL", "provider": "alpha_vantage"}]
    universe.extend(config["universe"])
    today = dt.date.today()
    result: list[dict[str, Any]] = []
    for item in sorted(universe, key=lambda value: value["symbol"]):
        symbol = item["symbol"]
        values = grouped.get(symbol, [])
        provider_row = provider_by_symbol.get(symbol, {})
        latest_date = values[-1]["date"] if values else ""
        date_counts: dict[str, int] = {}
        invalid_dates = 0
        invalid_prices = 0
        parsed_dates: list[dt.date] = []
        for value in values:
            date_value = str(value.get("date", ""))
            date_counts[date_value] = date_counts.get(date_value, 0) + 1
            try:
                parsed_dates.append(dt.date.fromisoformat(date_value))
            except ValueError:
                invalid_dates += 1
            try:
                close = float(value.get("close"))
                if not math.isfinite(close) or close <= 0:
                    invalid_prices += 1
            except (TypeError, ValueError):
                invalid_prices += 1
        duplicate_dates = sum(count - 1 for count in date_counts.values() if count > 1)
        parsed_dates.sort()
        gap_count = sum(1 for left, right in zip(parsed_dates, parsed_dates[1:]) if (right - left).days > 7)
        age_days: int | None = None
        if latest_date:
            try:
                age_days = (today - dt.date.fromisoformat(latest_date)).days
            except ValueError:
                age_days = None
        cache_fallback = any(value.get("cache_status") == "stale_fallback" for value in values)
        provider_status = str(provider_row.get("status", "")).upper()
        if provider_status == "FORA_DA_COORTE":
            status = "FORA_DA_COORTE"
        elif provider_status == "ERRO":
            status = "ERRO"
        elif not values:
            status = "ERRO"
        elif age_days is not None and age_days < 0:
            status = "ERRO"
        elif provider_row.get("status") == "ATRASADO" or cache_fallback:
            status = "ATRASADO"
        elif age_days is not None and age_days > 5:
            status = "ATRASADO"
        else:
            status = "OK"
        issues: list[str] = []
        if duplicate_dates:
            issues.append(f"{duplicate_dates} data(s) duplicada(s)")
        if gap_count:
            issues.append(f"{gap_count} lacuna(s) superior(es) a 7 dias")
        if invalid_dates:
            issues.append(f"{invalid_dates} data(s) inválida(s)")
        if invalid_prices:
            issues.append(f"{invalid_prices} preço(s) inválido(s)")
        if issues:
            status = "ERRO"
        base_message = provider_row.get("message", "") or ("data futura; verificar relógio/fonte" if age_days is not None and age_days < 0 else (f"último dado: {latest_date}" if latest_date else "sem dados"))
        if cache_fallback and "cache antigo" not in base_message.lower():
            base_message = f"cache antigo usado após falha do provider; {base_message}"
        message = "; ".join([base_message, *issues]) if issues else base_message
        result.append({
            "symbol": symbol,
            "source": values[0].get("source", item.get("provider", "")) if values else provider_row.get("source", item.get("provider", "")),
            "provider_requested": provider_row.get("provider_requested", ""),
            "provider_used": provider_row.get("provider_used", ""),
            "fallback_used": bool(provider_row.get("fallback_used", False)),
            "rows": len(values),
            "status": status,
            "age_days": age_days,
            "duplicate_dates": duplicate_dates,
            "gap_count": gap_count,
            "invalid_prices": invalid_prices,
            "cache_status": "stale_fallback" if cache_fallback else "",
            "message": message if message else ("data futura; verificar relógio/fonte" if age_days is not None and age_days < 0 else "sem dados"),
        })
    known_symbols = {row["symbol"] for row in result}
    macro_max_age = {
        f"FRED:{str(series.get('id', '')).upper()}": int(series.get("max_age_days", 5))
        for series in config.get("macro", {}).get("series", [])
        if series.get("id")
    }
    for provider_row in provider_quality:
        symbol = provider_row.get("symbol", "")
        if not symbol or symbol in known_symbols:
            continue
        latest_date = provider_row.get("latest_date", "")
        age_days: int | None = None
        if latest_date:
            try:
                age_days = (today - dt.date.fromisoformat(latest_date)).days
            except ValueError:
                age_days = None
        status = provider_row.get("status", "ERRO")
        max_age = macro_max_age.get(symbol, 5) if symbol.startswith("FRED:") else 5
        if status == "OK" and age_days is not None and age_days > max_age:
            status = "ATRASADO"
        if provider_row.get("cache_status") == "stale_fallback":
            status = "ATRASADO"
        message = provider_row.get("message", "") or (f"último dado: {latest_date}" if latest_date else "sem dados")
        if provider_row.get("cache_status") == "stale_fallback" and "cache antigo" not in message.lower():
            message = f"cache antigo usado após falha do provider; {message}"
        result.append({
            "symbol": symbol,
            "source": provider_row.get("source", ""),
            "provider_requested": provider_row.get("provider_requested", ""),
            "provider_used": provider_row.get("provider_used", ""),
            "fallback_used": bool(provider_row.get("fallback_used", False)),
            "rows": provider_row.get("rows", 0),
            "status": status,
            "age_days": age_days,
            "duplicate_dates": 0,
            "gap_count": 0,
            "invalid_prices": 0,
            "cache_status": provider_row.get("cache_status", ""),
            "message": message,
        })
    return result


def _atomic_write_text(destination: Path, content: str) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f"{destination.name}.{os.getpid()}.tmp")
    try:
        temporary.write_text(content, encoding="utf-8")
        temporary.replace(destination)
    finally:
        temporary.unlink(missing_ok=True)


def _atomic_write_bytes(destination: Path, content: bytes) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f"{destination.name}.{os.getpid()}.tmp")
    try:
        temporary.write_bytes(content)
        temporary.replace(destination)
    finally:
        temporary.unlink(missing_ok=True)


def write_json(payload: dict[str, Any], destination: Path) -> None:
    _atomic_write_text(destination, json.dumps(payload, ensure_ascii=False, indent=2))


def load_previous_payload(destination: Path) -> dict[str, Any]:
    """Read the last snapshot without making a failed run destroy the baseline."""
    try:
        with destination.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
        return payload if isinstance(payload, dict) else {}
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        return {}


def build_alerts(previous: dict[str, Any], current: dict[str, Any]) -> dict[str, Any]:
    """Create explainable daily transitions, never orders."""
    previous_mode = previous.get("meta", {}).get("mode")
    current_mode = current.get("meta", {}).get("mode")
    previous_signals = {row.get("symbol"): row for row in previous.get("signals", []) if row.get("symbol")}
    events: list[dict[str, Any]] = []
    factor_labels = {
        "momentum": "momentum",
        "relative_strength": "força relativa",
        "trend": "tendência",
        "breadth": "amplitude",
        "volume": "volume",
        "news": "notícias",
        "macro": "macro",
    }

    def factor_reason(old: dict[str, Any], new: dict[str, Any]) -> str:
        movements = []
        for key, label in factor_labels.items():
            try:
                delta = float(new.get(key, 50.0)) - float(old.get(key, 50.0))
            except (TypeError, ValueError):
                continue
            if abs(delta) >= 3.0:
                movements.append((abs(delta), delta, label))
        movements.sort(reverse=True)
        if not movements:
            return "sem fator dominante identificado"
        _, delta, label = movements[0]
        direction = "subiu" if delta > 0 else "desceu"
        detail = f"{label} {direction} {abs(delta):.1f} pontos"
        if len(movements) > 1:
            _, second_delta, second_label = movements[1]
            second_direction = "subiu" if second_delta > 0 else "desceu"
            detail += f"; {second_label} {second_direction} {abs(second_delta):.1f}"
        return detail

    def factor_details(old: dict[str, Any], new: dict[str, Any]) -> dict[str, Any]:
        movements: list[tuple[float, float, str]] = []
        for key, label in factor_labels.items():
            try:
                delta = float(new.get(key, 50.0)) - float(old.get(key, 50.0))
            except (TypeError, ValueError):
                continue
            if abs(delta) >= 3.0:
                movements.append((abs(delta), delta, label))
        movements.sort(reverse=True)
        if not movements:
            return {"dominant_factor": "", "dominant_factor_delta": None, "dominant_factor_direction": ""}
        _, delta, label = movements[0]
        return {"dominant_factor": label, "dominant_factor_delta": round(delta, 2), "dominant_factor_direction": "subiu" if delta > 0 else "desceu"}
    comparable = bool(previous_signals) and previous_mode == current_mode
    if comparable:
        for signal in current.get("signals", []):
            symbol = signal.get("symbol")
            if not symbol:
                continue
            old = previous_signals.get(symbol)
            if not old:
                events.append({"type": "NEW_ASSET", "symbol": symbol, "from_action": "", "to_action": signal.get("action", ""), "score_delta": None, "reason": "ativo apareceu no universo atual"})
                continue
            score_delta = round(float(signal.get("score", 0.0)) - float(old.get("score", 0.0)), 2)
            action_changed = signal.get("action") != old.get("action")
            confidence_drop = float(signal.get("confidence", 0.0)) <= float(old.get("confidence", 0.0)) - 15.0
            if action_changed:
                events.append({"type": "ACTION_CHANGE", "symbol": symbol, "from_action": old.get("action", ""), "to_action": signal.get("action", ""), "score_delta": score_delta, "reason": f"a ação mudou de estado; {factor_reason(old, signal)}"})
            elif abs(score_delta) >= 10.0:
                events.append({"type": "SCORE_MOVE", "symbol": symbol, "from_action": old.get("action", ""), "to_action": signal.get("action", ""), "score_delta": score_delta, "reason": f"a pontuação mudou pelo menos 10 pontos; {factor_reason(old, signal)}"})
            if confidence_drop:
                events.append({"type": "CONFIDENCE_DROP", "symbol": symbol, "from_action": old.get("action", ""), "to_action": signal.get("action", ""), "score_delta": score_delta, "reason": "a confiança caiu pelo menos 15 pontos"})
    if comparable:
        current_signals = {row.get("symbol"): row for row in current.get("signals", []) if row.get("symbol")}
        for event in events:
            old = previous_signals.get(event.get("symbol"))
            new = current_signals.get(event.get("symbol"))
            if old and new:
                event.update(factor_details(old, new))
    return {
        "as_of": current.get("meta", {}).get("as_of", ""),
        "mode": current_mode,
        "previous_as_of": previous.get("meta", {}).get("as_of", "") if comparable else "",
        "comparable": comparable,
        "events": events,
        "note": "Eventos informativos; não são ordens nem previsões de lucro.",
    }


def append_signal_history(payload: dict[str, Any], destination: Path) -> None:
    """Append one compact snapshot per date/mode for later audit."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    key = (payload.get("meta", {}).get("mode", ""), payload.get("meta", {}).get("as_of", ""))
    existing_keys: set[tuple[str, str]] = set()
    if destination.exists():
        try:
            for line in destination.read_text(encoding="utf-8").splitlines()[-5000:]:
                item = json.loads(line)
                existing_keys.add((item.get("mode", ""), item.get("as_of", "")))
        except (OSError, json.JSONDecodeError):
            existing_keys = set()
    if key in existing_keys:
        return
    with destination.open("a", encoding="utf-8") as handle:
        for signal in payload.get("signals", []):
            handle.write(json.dumps({
                "as_of": payload.get("meta", {}).get("as_of", ""),
                "generated_at": payload.get("meta", {}).get("generated_at", ""),
                "mode": payload.get("meta", {}).get("mode", ""),
                "symbol": signal.get("symbol", ""),
                "sector": signal.get("sector", ""),
                "score": signal.get("score", 0.0),
                "confidence": signal.get("confidence", 0.0),
                "action": signal.get("action", ""),
                "price": signal.get("price", 0.0),
                "risk_penalty": signal.get("risk_penalty", 0.0),
                "source": signal.get("source", ""),
            }, ensure_ascii=False) + "\n")


def append_signal_outcomes(history_path: Path, outcomes_path: Path, rows: list[dict[str, Any]], horizons: Iterable[int] = (5, 20)) -> int:
    """Evaluate completed signal horizons using only data after the signal date."""
    if not history_path.exists():
        return 0
    history: list[dict[str, Any]] = []
    for line in history_path.read_text(encoding="utf-8").splitlines()[-5000:]:
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(item, dict):
            history.append(item)
    existing: set[tuple[int, str, str, str, int, str, float]] = set()
    if outcomes_path.exists():
        for line in outcomes_path.read_text(encoding="utf-8").splitlines()[-10000:]:
            try:
                item = json.loads(line)
                if int(item.get("outcome_version", 1)) != 2:
                    continue
                existing.add((2, str(item.get("mode", "")), str(item.get("as_of", "")), str(item.get("symbol", "")), int(item.get("horizon", 0)), str(item.get("source", "")), round(float(item.get("signal_price", 0.0)), 8)))
            except (json.JSONDecodeError, TypeError, ValueError):
                continue
    grouped = grouped_rows(rows)
    created: list[dict[str, Any]] = []
    for signal in history:
        symbol = str(signal.get("symbol", ""))
        series = grouped.get(symbol, [])
        if not symbol or not series:
            continue
        positions = {str(row.get("date", "")): index for index, row in enumerate(series)}
        start_index = positions.get(str(signal.get("as_of", "")))
        if start_index is None:
            continue
        try:
            start_price = float(signal.get("price", 0.0))
        except (TypeError, ValueError):
            continue
        if start_price <= 0:
            continue
        for horizon in horizons:
            horizon = int(horizon)
            source = str(signal.get("source", "")) or str(series[start_index].get("source", ""))
            key = (2, str(signal.get("mode", "")), str(signal.get("as_of", "")), symbol, horizon, source, round(start_price, 8))
            target_index = start_index + horizon
            if horizon <= 0 or key in existing or target_index >= len(series):
                continue
            try:
                future_price = float(series[target_index]["close"])
            except (KeyError, TypeError, ValueError):
                continue
            created.append({
                "outcome_version": 2,
                "mode": signal.get("mode", ""),
                "as_of": signal.get("as_of", ""),
                "symbol": symbol,
                "sector": signal.get("sector", ""),
                "action": signal.get("action", ""),
                "score": signal.get("score", 0.0),
                "confidence": signal.get("confidence", 0.0),
                "horizon": horizon,
                "target_date": series[target_index].get("date", ""),
                "signal_price": start_price,
                "target_price": future_price,
                "forward_return": round(future_price / start_price - 1.0, 6),
                "source": source,
            })
    if created:
        outcomes_path.parent.mkdir(parents=True, exist_ok=True)
        with outcomes_path.open("a", encoding="utf-8") as handle:
            for item in created:
                handle.write(json.dumps(item, ensure_ascii=False) + "\n")
    return len(created)


def write_csv(rows: list[dict[str, Any]], destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f"{destination.name}.{os.getpid()}.tmp")
    try:
        with temporary.open("w", encoding="utf-8", newline="") as handle:
            if rows:
                writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
                writer.writeheader()
                writer.writerows(rows)
        temporary.replace(destination)
    finally:
        temporary.unlink(missing_ok=True)


def summarize_outcomes(outcomes_path: Path, mode: str, horizons: Iterable[int]) -> dict[str, Any]:
    """Summarize observed forward returns without turning them into predictions."""
    records: list[dict[str, Any]] = []
    if outcomes_path.exists():
        for line in outcomes_path.read_text(encoding="utf-8").splitlines()[-10000:]:
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(item, dict) and str(item.get("mode", "")) == str(mode):
                try:
                    if int(item.get("outcome_version", 1) or 1) != 2:
                        continue
                    item["horizon"] = int(item.get("horizon", 0))
                    item["forward_return"] = float(item.get("forward_return"))
                except (TypeError, ValueError):
                    continue
                if item["horizon"] > 0 and math.isfinite(item["forward_return"]):
                    records.append(item)

    wanted_horizons = sorted({int(value) for value in horizons if int(value) > 0})

    def metrics(items: list[dict[str, Any]]) -> dict[str, Any]:
        returns = [float(item["forward_return"]) for item in items]
        return {
            "records": len(returns),
            "positive_rate": round(sum(value > 0 for value in returns) / len(returns), 4) if returns else None,
            "average_return": round(statistics.mean(returns), 6) if returns else None,
            "median_return": round(statistics.median(returns), 6) if returns else None,
        }

    by_horizon: dict[str, Any] = {}
    by_symbol_items: dict[str, dict[str, list[dict[str, Any]]]] = {}
    for horizon in wanted_horizons:
        horizon_items = [item for item in records if item["horizon"] == horizon]
        by_horizon[str(horizon)] = metrics(horizon_items)
        for item in horizon_items:
            symbol = str(item.get("symbol", "")).upper()
            if symbol:
                by_symbol_items.setdefault(symbol, {}).setdefault(str(horizon), []).append(item)
    by_symbol = {
        symbol: {horizon: metrics(items) for horizon, items in horizon_items.items()}
        for symbol, horizon_items in by_symbol_items.items()
    }
    return {
        "mode": mode,
        "records": len(records),
        "by_horizon": by_horizon,
        "by_symbol": by_symbol,
        "note": "Medição descritiva de retornos posteriores observados; não é taxa de acerto, previsão ou garantia.",
    }


def summarize_sectors(signals: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Aggregate the current snapshot by sector for reports and dashboards."""
    grouped: dict[str, list[dict[str, Any]]] = {}
    for signal in signals:
        sector = str(signal.get("sector", "Sem setor")).strip() or "Sem setor"
        grouped.setdefault(sector, []).append(signal)
    summary: list[dict[str, Any]] = []
    for sector, items in grouped.items():
        scores = [float(item.get("score")) for item in items if isinstance(item.get("score"), (int, float))]
        buy_signals = sum("compra" in str(item.get("action", "")).lower() for item in items)
        summary.append({
            "sector": sector,
            "signals": len(items),
            "average_score": round(statistics.mean(scores), 1) if scores else None,
            "buy_signals": buy_signals,
        })
    return sorted(summary, key=lambda item: item["average_score"] if item["average_score"] is not None else -1, reverse=True)


def _decision_watch_factors(signal: dict[str, Any]) -> list[str]:
    """Name the weakest normalized components that keep a signal below the gate."""
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


def summarize_decision_round(signals: list[dict[str, Any]], thresholds: dict[str, Any] | None = None) -> dict[str, Any]:
    """Explain the current action gate in a compact, report-friendly shape."""
    thresholds = thresholds or {}
    try:
        buy_score = float(thresholds.get("buy_score", 80))
    except (TypeError, ValueError):
        buy_score = 80.0
    buy_candidates = [item for item in signals if "compra" in str(item.get("action", "")).lower()]
    near_entry = [
        item for item in signals
        if buy_score - 25 <= float(item.get("score", -1) or -1) < buy_score
        and int(item.get("data_points", 0) or 0) >= 200
    ]
    near_entry.sort(key=lambda item: float(item.get("score", 0) or 0), reverse=True)
    action_counts: dict[str, int] = {}
    for item in signals:
        action = str(item.get("action", "Sem leitura"))
        action_counts[action] = action_counts.get(action, 0) + 1
    if buy_candidates:
        status = "para investigar"
        headline = f"{len(buy_candidates)} sinal(is) atingiu/atingiram o limiar de compra"
    else:
        status = "sem entrada confirmada"
        headline = f"Nenhum sinal atingiu o limiar de compra ({buy_score:.1f}/100)"
    return {
        "status": status,
        "headline": headline,
        "buy_score": round(buy_score, 2),
        "buy_candidates": [str(item.get("symbol", "")) for item in buy_candidates],
        "near_entry_candidates": [
            {
                "symbol": str(item.get("symbol", "")),
                "score": float(item.get("score", 0) or 0),
                "action": str(item.get("action", "")),
                "gap_to_buy": round(max(0.0, buy_score - float(item.get("score", 0) or 0)), 2),
                "watch_factors": _decision_watch_factors(item),
            }
            for item in near_entry[:5]
        ],
        "highest_score": max((float(item.get("score", 0) or 0) for item in signals), default=None),
        "action_counts": action_counts,
    }


def write_report(payload: dict[str, Any], destination: Path) -> None:
    signals = payload["signals"]
    strategy = payload["backtest"]["strategy"]
    benchmark = payload["backtest"]["benchmark"]
    weights = payload.get("config", {}).get("weights", {})
    thresholds = payload.get("config", {}).get("thresholds", {})
    fallback_rows = [row for row in payload.get("quality", []) if isinstance(row, dict) and row.get("fallback_used")]
    fallback_summary = ", ".join(f"{row.get('symbol', '')} ({row.get('provider_requested', 'provider')} -> {row.get('provider_used', row.get('source', 'alternativa'))})" for row in fallback_rows)
    network_plan = payload.get("network_plan", {}) if isinstance(payload.get("network_plan", {}), dict) else {}
    portfolio_monitor = network_plan.get("portfolio_monitor", {}) if isinstance(network_plan.get("portfolio_monitor", {}), dict) else {}
    monitor_symbols = portfolio_monitor.get("selected_symbols", []) if isinstance(portfolio_monitor.get("selected_symbols", []), list) else []
    lines = [
        "# Radar diário de momentum setorial",
        "",
        f"**Data:** {payload['meta']['as_of']}  ",
        f"**Modo:** {payload['meta']['mode']}  ",
        f"**Fonte:** {payload['meta']['source_note']}",
        f"**Contexto:** notícias para {payload['meta'].get('news_score_symbols', 0)} símbolos; ambiente económico {payload['meta'].get('macro_score', 50.0):.1f}/100",
        *([f"**Fallback de provider:** {fallback_summary}"] if fallback_rows else []),
        *([f"**Coorte:** {', '.join(payload['meta'].get('cohort', {}).get('active_symbols', []))} · {len(payload['meta'].get('cohort', {}).get('stale_symbols', []))} ativos com última leitura local"] if payload['meta'].get('cohort', {}).get('rotated') else []),
        *([f"**Monitorização da carteira:** {len(monitor_symbols)} posições prioritárias recolhidas para supervisão; excluídas do paper trading."] if monitor_symbols else []),
        "",
        "> [!warning] Uso responsável",
        "> Este relatório é uma ferramenta de pesquisa. Não prevê o mercado, não garante lucro e não envia ordens.",
        "",
        "## Sinais de hoje",
        "",
        "| # | Setor | Símbolo | Pontuação | Confiança | Ação | Risco |",
        "|---:|---|---|---:|---:|---|---:|",
    ]
    context_warnings: list[str] = []
    if not payload["meta"].get("benchmark_available", True):
        context_warnings.extend([
            "> [!danger] Mercado de comparação em falta",
            "> O mercado de comparação não chegou; as ações foram bloqueadas para evitar sinais sem contexto.",
            "",
        ])
    if payload["meta"].get("mode") == "live" and payload["meta"].get("news_score_symbols", 0) == 0:
        context_warnings.extend([
            "> [!warning] Notícias sem pontuação",
            "> Não houve sentimento de notícias utilizável; o fator foi mantido neutro em 50.",
            "",
        ])
    if payload["meta"].get("mode") == "live" and not payload["meta"].get("context_available", True):
        context_warnings.extend([
            "> [!danger] Contexto live incompleto",
            "> Notícias ou ambiente económico estão indisponíveis; as ações foram bloqueadas até a validação passar.",
            "",
        ])
    lines[10:10] = context_warnings
    for number, signal in enumerate(signals, 1):
        lines.append(f"| {number} | {signal['sector']} | {signal['symbol']} | {signal['score']:.1f} | {signal['confidence']:.1f} | {signal['action']} | {signal['risk_penalty']:.1f} |")
    cohort = payload.get("meta", {}).get("cohort", {}) if isinstance(payload.get("meta", {}), dict) else {}
    if isinstance(cohort, dict) and cohort.get("rotated"):
        quality_counts: dict[str, int] = {}
        for quality_row in payload.get("quality", []):
            status = str(quality_row.get("status", "Sem estado"))
            quality_counts[status] = quality_counts.get(status, 0) + 1
        active_count = len(cohort.get("active_symbols", [])) if isinstance(cohort.get("active_symbols", []), list) else 0
        stale_count = len(cohort.get("stale_symbols", [])) if isinstance(cohort.get("stale_symbols", []), list) else 0
        sector_text = ", ".join(str(item) for item in cohort.get("sector_coverage", [])) or "sem setores adicionais"
        rotation_index = cohort.get("rotation_index")
        round_index = int(rotation_index) + 1 if rotation_index is not None else 1
        round_total = cohort.get("rotation_rounds") or "?"
        next_rotation_index = cohort.get("next_rotation_index")
        if next_rotation_index is None:
            next_rotation_summary = "Proxima coorte automatica: nao agendada; a cobertura atual foi definida manualmente ou pela carteira."
        else:
            next_rotation_summary = (
                f"Proxima coorte automatica: {int(next_rotation_index) + 1}/{round_total} "
                f"em {cohort.get('next_rotation_date') or 'apos a proxima execucao manual'}."
            )
        lines.extend([
            "",
            "## Cobertura desta ronda",
            next_rotation_summary,
            "",
            f"**Perfil:** {cohort.get('profile', 'expanded')} · **Coorte:** {round_index}/{round_total} · **Ativos recolhidos:** {active_count} · **Ativos fora desta ronda:** {stale_count}",
            f"**Setores representados:** {sector_text}.",
            f"**Qualidade:** OK {quality_counts.get('OK', 0)} · atrasados {quality_counts.get('ATRASADO', 0)} · fora da coorte {quality_counts.get('FORA_DA_COORTE', 0)} · erros {quality_counts.get('ERRO', 0)}.",
            "Fora da coorte significa que o ativo aguarda uma ronda futura; não é uma falha do provider nem uma recomendação de compra/venda.",
        ])
    decision = payload.get("decision_round", summarize_decision_round(signals, thresholds))
    near_entry = decision.get("near_entry_candidates", []) if isinstance(decision, dict) else []
    candidates = decision.get("buy_candidates", []) if isinstance(decision, dict) else []
    near_text = ", ".join(
        f"{item.get('symbol')} ({float(item.get('score', 0)):.1f}; faltam {float(item.get('gap_to_buy', max(0.0, float(decision.get('buy_score', thresholds.get('buy_score', 80)) or 80) - float(item.get('score', 0) or 0)))):.1f}; vigiar {', '.join(item.get('watch_factors', []))})"
        for item in near_entry
    ) if near_entry else "nenhum"
    candidate_text = ", ".join(str(item) for item in candidates) if candidates else "nenhum"
    lines.extend([
        "",
        "## Decisão desta ronda",
        "",
        f"**Estado:** {decision.get('headline', 'sem diagnóstico')}",
        f"**Candidatos a investigar:** {candidate_text}",
        f"**Em observação perto do limiar:** {near_text}",
        "Esta secção descreve o filtro atual; não é uma ordem, uma probabilidade de lucro nem uma garantia.",
    ])
    sector_summary = payload.get("sector_summary", summarize_sectors(signals))
    if sector_summary:
        lines.extend([
            "",
            "## Pulso por setor",
            "",
            "Resumo do snapshot atual; não é uma previsão nem uma recomendação independente.",
            "",
            "| Setor | Sinais | Score médio | Sinais de compra |",
            "|---|---:|---:|---:|",
        ])
        for item in sector_summary:
            average = "—" if item.get("average_score") is None else f"{float(item['average_score']):.1f}"
            lines.append(f"| {item.get('sector', 'Sem setor')} | {int(item.get('signals', 0))} | {average} | {int(item.get('buy_signals', 0))} |")
    alerts = payload.get("alerts", {})
    lines.extend(["", "## Alertas desde a última execução", ""])
    if not alerts.get("comparable"):
        lines.append("Não há snapshot anterior comparável no mesmo modo; esta execução serve como linha de base.")
    elif not alerts.get("events"):
        lines.append("Nenhuma transição relevante: ações e pontuações mantiveram-se dentro dos limiares definidos.")
    else:
        lines.extend(["| Tipo | Símbolo | Estado anterior | Estado atual | Variação do Score | Fator dominante | Motivo |", "|---|---|---|---|---:|---|---|"])
        for event in alerts["events"]:
            delta = "" if event.get("score_delta") is None else f"{event['score_delta']:+.1f}"
            factor_delta = event.get("dominant_factor_delta")
            factor = event.get("dominant_factor", "")
            if factor and factor_delta is not None:
                factor = f"{factor} ({float(factor_delta):+.1f})"
            lines.append(f"| {event['type']} | {event['symbol']} | {event.get('from_action', '')} | {event.get('to_action', '')} | {delta} | {factor} | {event.get('reason', '')} |")
    outcomes = payload.get("outcomes", {})
    lines.extend([
        "",
        "## Auditoria de sinais",
        "",
        f"Foram acrescentados {int(outcomes.get('new_records', 0))} resultados posteriores nesta execução. As janelas são medidas em observações disponíveis, não em dias de calendário.",
        "O retorno posterior é uma medição descritiva do que aconteceu depois do sinal; não é uma probabilidade de lucro nem uma garantia.",
    ])
    lines.extend([
        "",
        "## Leitura rápida",
        "",
    ])
    outcome_summary = outcomes.get("summary", {}) if isinstance(outcomes, dict) else {}
    lines.extend(["", "### Resultados observados por janela", ""])
    if not outcome_summary.get("records"):
        lines.append("Ainda não há resultados posteriores suficientes para esta modalidade.")
    else:
        lines.extend([
            "Os números abaixo descrevem apenas os sinais já fechados neste modo e não incorporam custos de execução, impostos ou slippage.",
            "",
            "| Janela | Registos | Retorno positivo | Média | Mediana |",
            "|---:|---:|---:|---:|---:|",
        ])
        for horizon, summary in outcome_summary.get("by_horizon", {}).items():
            if not summary.get("records"):
                continue
            positive = "—" if summary.get("positive_rate") is None else f"{summary['positive_rate']:.1%}"
            average = "—" if summary.get("average_return") is None else f"{summary['average_return']:.2%}"
            median = "—" if summary.get("median_return") is None else f"{summary['median_return']:.2%}"
            lines.append(f"| {horizon} observações | {summary['records']} | {positive} | {average} | {median} |")
        lines.extend(["", f"> {outcome_summary.get('note', 'Leitura descritiva; não é uma previsão.')}"])
    cache_stats = payload.get("cache_stats", {}) if isinstance(payload, dict) else {}
    network_usage = payload.get("network_usage", {}) if isinstance(payload, dict) else {}
    if isinstance(network_usage, dict):
        lines.extend([
            "",
            "### Esta execução",
            "",
            f"Chamadas externas efetivamente tentadas: **{int(network_usage.get('outbound_calls', 0))}**.",
            "Este número vem do ledger local por bucket UTC; respostas em cache não entram como chamadas externas.",
        ])
        calls_by_bucket = network_usage.get("outbound_calls_by_bucket", {})
        if isinstance(calls_by_bucket, dict) and calls_by_bucket:
            lines.append(" · ".join(f"{bucket}: {int(count)}" for bucket, count in sorted(calls_by_bucket.items())))
    network_plan = payload.get("network_plan", {}) if isinstance(payload, dict) else {}
    if isinstance(network_plan, dict) and payload.get("meta", {}).get("mode") == "live":
        lines.extend([
            f"Estimativa antes da execução: **{int(network_plan.get('estimated_total_calls', 0))}** chamadas brutas; **{int(network_plan.get('estimated_network_calls', 0))}** chamadas novas após cache fresco.",
            f"Chamadas evitadas pelo cache fresco: **{int(network_plan.get('cache_avoided_calls', 0))}**.",
        ])
        if int(network_plan.get("deduplicated_requests", 0)):
            lines.append(f"Pedidos duplicados deduplicados antes da rede: **{int(network_plan.get('deduplicated_requests', 0))}**.")
    advice = network_plan.get("quota_advice", {}).get("alpha_vantage", {}) if isinstance(network_plan.get("quota_advice", {}), dict) else {}
    if isinstance(advice, dict) and advice:
        lines.extend([
            "",
            "### Cadencia segura sugerida",
            "",
            str(advice.get("recommendation", "Consulta o pre-flight antes de uma nova recolha.")),
            f"Margem reservada: **{int(advice.get('reserve', 0))}** chamadas Alpha Vantage; coorte segura: ate **{int(advice.get('max_assets_in_safe_cohort', 0))}** ativos alem do benchmark; rotacao estimada: **{advice.get('estimated_rotation_days') or '—'}** dia(s).",
        ])
    cache_namespaces = cache_stats.get("namespaces", {}) if isinstance(cache_stats, dict) else {}
    if cache_namespaces:
        lines.extend([
            "",
            "## Eficiência do cache e quota",
            "",
            "Os contadores abaixo não guardam URLs, parâmetros ou chaves. Hits são respostas locais; misses são pedidos que chegaram ao provider; erros são respostas falhadas.",
            "",
            "| Namespace | Hits | Misses | Erros | Bypass | Fallback antigo |",
            "|---|---:|---:|---:|---:|---:|",
        ])
        for namespace, stats in sorted(cache_namespaces.items()):
            lines.append(f"| {namespace} | {int(stats.get('hits', 0))} | {int(stats.get('misses', 0))} | {int(stats.get('errors', 0))} | {int(stats.get('bypass', 0))} | {int(stats.get('stale_fallbacks', 0))} |")
    daily_calls = cache_stats.get("daily_calls", {}) if isinstance(cache_stats, dict) else {}
    network_config = payload.get("config", {}).get("network", {}) if isinstance(payload.get("config", {}), dict) else {}
    daily_budgets = network_config.get("daily_call_budgets", {}) if isinstance(network_config, dict) else {}
    daily_reserves = network_config.get("daily_call_reserves", {}) if isinstance(network_config, dict) else {}
    if isinstance(daily_calls, dict) or isinstance(daily_budgets, dict):
        today = dt.datetime.now(dt.timezone.utc).date().isoformat()
        buckets = set(str(key).lower() for key in daily_calls) | set(str(key).lower() for key in daily_budgets)
        rows = []
        for bucket in sorted(item for item in buckets if item):
            usage = daily_calls.get(bucket, {}) if isinstance(daily_calls.get(bucket, {}), dict) else {}
            used = int(usage.get("calls", 0)) if usage.get("date") == today else 0
            raw_limit = daily_budgets.get(bucket)
            try:
                limit = "—" if raw_limit is None or str(raw_limit).strip().lower() in {"", "none", "unlimited"} else str(max(0, int(raw_limit)))
            except (TypeError, ValueError):
                limit = "—"
            remaining = "—" if limit == "—" else str(max(0, int(limit) - used))
            raw_reserve = daily_reserves.get(bucket, 0) if isinstance(daily_reserves, dict) else 0
            try:
                reserve = max(0, int(raw_reserve))
            except (TypeError, ValueError):
                reserve = 0
            safe_remaining = "—" if remaining == "—" else str(max(0, int(remaining) - reserve))
            rows.append(f"| {bucket} | {used} | {limit} | {remaining} | {reserve} | {safe_remaining} |")
        if rows:
            lines.extend(["", "### Orçamento diário local", "", f"Data UTC: {today}. A contagem inclui pedidos externos efetivamente tentados; respostas em cache não consomem orçamento. A margem segura exclui a reserva operacional.", "", "| Provider | Usadas | Limite | Restantes | Reserva | Margem segura |", "|---|---:|---:|---:|---:|---:|"])
            lines.extend(rows)
    for signal in signals[:3]:
        lines.append(f"- **{signal['symbol']} / {signal['sector']}:** {signal['action']}. {signal['notes']}")
    lines.extend([
        "",
        "## Guia de leitura",
        "",
        "Este quadro traduz os números do radar para linguagem simples. O radar organiza sinais; não prevê o futuro nem substitui uma decisão de investimento.",
        "",
        "### Pontuação e ação",
        "",
        "| Termo | O que significa |",
        "|---|---|",
        "| Pontuação (Score) | Nota de 0 a 100 que combina os indicadores abaixo. Quanto maior, mais sinais apontam na mesma direção. |",
        f"| Confiança | Mede a consistência entre os indicadores e a quantidade de histórico disponível. O mínimo configurado é {thresholds.get('min_confidence', 55):.1f}. Não é a probabilidade de lucro. |",
        "| Risco | Penalização de 0 a 30 aplicada à pontuação quando a volatilidade ou a queda desde o pico são elevadas. Quanto maior, mais risco o modelo detetou. |",
        "| Considerar compra | A pontuação atingiu o limite configurado, atualmente {0:.1f}. É um sinal para investigar, não uma ordem. |".format(thresholds.get("buy_score", 80)),
        "| Manter/observar | A pontuação fica entre o limite de manutenção e o de compra. Pede acompanhamento. |",
        "| Reduzir/evitar | A pontuação ficou abaixo do limite de manutenção. O modelo vê pouco impulso neste momento. |",
        "| Não agir | Faltam dados, mercado de comparação ou contexto suficiente para confiar no sinal. |",
        "",
        "### Indicadores que formam a pontuação",
        "",
        "| Indicador | Explicação | Peso atual |",
        "|---|---|---:|",
        f"| Impulso do preço | Mede se o movimento recente ganhou ou perdeu força. | {weights.get('momentum', 0):.0%} |",
        f"| Comparação com o mercado | Compara o desempenho do ativo com um grupo de referência. | {weights.get('relative_strength', 0):.0%} |",
        f"| Direção do preço | Verifica se o preço construiu uma direção consistente. | {weights.get('trend', 0):.0%} |",
        f"| Amplitude (breadth) | Mede quantos componentes confirmam o movimento. No MVP há um representante por tema, por isso fica neutra em 50. | {weights.get('breadth', 0):.0%} |",
        f"| Atividade de negociação | Compara a atividade recente com o normal do próprio ativo. Volume alto não distingue sozinho compras de vendas. | {weights.get('volume', 0):.0%} |",
        f"| Clima das notícias | Resume as notícias recentes de 0 a 100. 50 é neutro. | {weights.get('news', 0):.0%} |",
        f"| Ambiente económico | Resume se inflação, juros e moeda ajudam ou dificultam este tipo de ativo. | {weights.get('macro', 0):.0%} |",
        "",
        "### Termos do backtest",
        "",
        "| Termo | O que significa |",
        "|---|---|",
        "| Mercado de comparação | Grupo de referência. O mercado global ajuda a comparar o ativo; a carteira equiponderada do teste dá o mesmo peso a cada tema. |",
        "| Retorno total | Quanto a carteira simulada teria ganho ou perdido no período, antes de custos e impostos. |",
        "| CAGR | Crescimento médio anualizado. Converte o resultado do período numa taxa anual equivalente; não é uma promessa de retorno anual. |",
        "| Drawdown máximo | Maior queda da carteira simulada desde um pico até ao fundo seguinte. Mostra a pior perda durante o caminho. |",
        "| Sharpe | Compara o retorno obtido com a variação desse retorno. Um valor maior costuma indicar melhor retorno para o risco assumido, mas depende do período analisado. |",
        "| Observações | Número de rebalanceamentos usados no backtest. Mais observações ajudam, mas não eliminam o risco de o futuro ser diferente. |",
        "| Qualidade dos dados | Mostra se cada fonte respondeu, quantas linhas trouxe e quão recente é o último dado. |",
        "",
        "## Backtest walk-forward",
        "",
        f"- Estratégia: retorno total {strategy['total_return']:.1%}, CAGR {strategy['cagr']:.1%}, drawdown máximo {strategy['max_drawdown']:.1%}, Sharpe {strategy['sharpe']:.2f}.",
        f"- Mercado de comparação equilibrado: retorno total {benchmark['total_return']:.1%}, CAGR {benchmark['cagr']:.1%}, drawdown máximo {benchmark['max_drawdown']:.1%}, Sharpe {benchmark['sharpe']:.2f}.",
        f"- Execução simulada: atraso de {int(payload['backtest'].get('assumptions', {}).get('signal_delay_days', 0))} dia(s), comissão {float(payload['backtest'].get('assumptions', {}).get('commission_bps', 0.0)):.1f} bps e slippage {float(payload['backtest'].get('assumptions', {}).get('slippage_bps', 0.0)):.1f} bps quando há posição.",
        f"- Observações: {int(strategy['observations'])}. O resultado histórico não valida lucro futuro.",
        f"- Validação por períodos separados: {len(payload['backtest'].get('walk_forward', {}).get('folds', []))} janelas fora da amostra; estado {payload['backtest'].get('walk_forward', {}).get('status', 'indisponível')}.",
        "",
        "## Qualidade dos dados",
        "",
        "| Símbolo | Fonte | Linhas | Estado | Idade (dias) | Mensagem |",
        "|---|---|---:|---|---:|---|",
    ])
    for row in payload["quality"]:
        age = "" if row.get("age_days") is None else row["age_days"]
        raw_symbol = str(row.get("symbol", ""))
        quality_symbol = "Contexto económico" if raw_symbol.startswith("FRED:") or raw_symbol == "MACRO" else "Notícias" if raw_symbol == "NEWS" else "Mercado de comparação" if raw_symbol == "GLOBAL" else raw_symbol
        quality_source = "Contexto económico" if str(row.get("source", "")).lower() == "fred" else "Notícias" if str(row.get("source", "")).lower() == "alpha_vantage" and raw_symbol == "NEWS" else row.get("source", "")
        lines.append(f"| {quality_symbol} | {quality_source} | {row['rows']} | {row['status']} | {age} | {row['message']} |")
    lines.extend([
        "",
        "## Fontes",
        "",
        "- https://www.alphavantage.co/documentation/",
        "- https://coinmarketcap.com/api/documentation/guides/get-historical-price-data",
        "- https://query1.finance.yahoo.com/v8/finance/chart/",
        "- https://fred.stlouisfed.org/docs/api/fred/series_observations.html",
    ])
    try:
        from src.action_commentary import commentary_entries, commentary_markdown
    except ModuleNotFoundError:
        from action_commentary import commentary_entries, commentary_markdown
    lines.extend(["", commentary_markdown(commentary_entries(payload)), ""])
    _atomic_write_text(destination, "\n".join(lines) + "\n")


def archive_daily_report(payload: dict[str, Any], output_dir: Path) -> tuple[Path, Path]:
    """Keep one dated Markdown/PDF copy of the generated daily report."""
    as_of = str(payload.get("meta", {}).get("as_of", "snapshot"))
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", as_of):
        as_of = "snapshot"
    archive_dir = output_dir / "reports"
    archive_dir.mkdir(parents=True, exist_ok=True)
    markdown_path = archive_dir / f"radar-diario-{as_of}.md"
    current_report = output_dir / "relatorio-momentum.md"
    _atomic_write_text(markdown_path, current_report.read_text(encoding="utf-8"))
    try:
        from src.pdf_report import build_daily_pdf
    except ModuleNotFoundError:
        from pdf_report import build_daily_pdf

    pdf_path = archive_dir / f"radar-diario-{as_of}.pdf"
    _atomic_write_bytes(pdf_path, build_daily_pdf(payload))
    return markdown_path, pdf_path


def main() -> int:
    parser = argparse.ArgumentParser(description="Radar diário de momentum setorial")
    parser.add_argument("--mode", choices=["demo", "live"], default=None, help="modo de dados; demo não usa rede")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--output-dir", type=Path, default=OUTPUT_DIR)
    parser.add_argument("--plan-only", action="store_true", help="mostrar custo live, cache, chaves e orçamento sem fazer chamadas")
    parser.add_argument("--symbols", default="", help="coorte live opcional, separada por vírgulas; os restantes ativos usam a última leitura live local")
    parser.add_argument("--price-provider", choices=["alpha_vantage", "tiingo", "yahoo_finance"], default="", help="override opcional para os ativos e benchmark que usam Alpha Vantage")
    parser.add_argument("--universe-profile", choices=["core", "expanded"], default="core", help="perfil de cobertura; expanded acrescenta ativos price-only e aumenta o custo live")
    parser.add_argument("--cohort-size", type=int, default=15, help="número de ativos adicionais por ronda no perfil expanded; core não é afetado")
    parser.add_argument("--cohort-index", type=int, default=-1, help="índice opcional da coorte; por defeito roda automaticamente por data UTC")
    parser.add_argument("--monitor-portfolio", action="store_true", help="monitorizar posicoes prioritarias live sem ordens")
    parser.add_argument("--portfolio-monitor-limit", type=int, default=None, help="limite opcional de posicoes monitorizadas live")
    args = parser.parse_args()
    config = load_config(args.config)
    apply_universe_profile(config, args.universe_profile)
    portfolio_monitor_symbols: set[str] = set()
    portfolio_monitor = {"enabled": False, "selected_symbols": [], "reserve_calls": 0}
    if args.monitor_portfolio and (args.mode or config.get("mode", "demo")) == "live":
        portfolio_monitor_symbols, portfolio_monitor = prepare_portfolio_monitor(config, args.portfolio_monitor_limit, args.output_dir / "momentum_data.json")
    if args.price_provider:
        for item in config.get("universe", []):
            if isinstance(item, dict) and str(item.get("provider", "")).lower() == "alpha_vantage":
                item["provider"] = args.price_provider
        benchmark = config.setdefault("benchmark", {})
        if isinstance(benchmark, dict):
            benchmark["provider"] = args.price_provider
    previous_payload = load_previous_payload(args.output_dir / "momentum_data.json")
    mode = args.mode or config.get("mode", "demo")
    requested_symbols = {value.strip().upper() for value in str(args.symbols).split(",") if value.strip()}
    known_symbols = {str(item.get("symbol", "")).upper() for item in config.get("universe", []) if isinstance(item, dict)}
    unknown_symbols = sorted(requested_symbols - known_symbols)
    if unknown_symbols:
        raise RuntimeError(f"coorte contém símbolos que não estão no universo: {', '.join(unknown_symbols)}")
    is_primary_output = args.output_dir.resolve() == OUTPUT_DIR.resolve()
    if is_primary_output and should_skip_weekend_run(config, mode, requested_symbols):
        result = {
            "mode": mode,
            "skipped": True,
            "reason": "fim de semana; a ronda completa foi adiada para preservar quota",
            "estimated_network_calls": 0,
            "hint": "usa --symbols BTC,ETH para uma leitura cripto explícita",
        }
        print(json.dumps(result, ensure_ascii=False, indent=2 if args.plan_only else None))
        return 0
    cohort_plan: dict[str, Any] = {"profile": args.universe_profile, "index": 0, "size": 0, "selected_additions": [], "sector_coverage": []}
    if requested_symbols:
        active_symbols = requested_symbols
        cohort_plan = {**cohort_plan, "manual": True, "selected_additions": sorted(requested_symbols)}
    elif mode == "live" and args.universe_profile == "expanded":
        active_symbols, cohort_plan = select_rotating_cohort(config, args.universe_profile, args.cohort_size, None if args.cohort_index < 0 else args.cohort_index)
    else:
        active_symbols = None
    fitted_network_plan: dict[str, Any] | None = None
    if portfolio_monitor_symbols:
        base_symbols = {str(item.get("symbol", "")).upper() for item in config.get("universe", []) if isinstance(item, dict)} - portfolio_monitor_symbols
        active_symbols = (active_symbols or base_symbols) | portfolio_monitor_symbols
        active_symbols, portfolio_monitor, fitted_network_plan = fit_portfolio_monitor_to_budget(config, active_symbols, portfolio_monitor)
        portfolio_monitor_symbols = set(portfolio_monitor.get("selected_symbols", []))
        cohort_plan = {**cohort_plan, "portfolio_monitor_symbols": sorted(portfolio_monitor_symbols)}
    if args.plan_only:
        plan = (fitted_network_plan or live_network_plan(config, active_symbols)) if mode == "live" else {"mode": "demo", "network_allowed": True, "estimated_total_calls": 0, "message": "Modo demo: nenhuma chamada externa seria feita."}
        plan["cohort"] = cohort_plan
        plan["portfolio_monitor"] = portfolio_monitor
        print(json.dumps(plan, ensure_ascii=False, indent=2))
        return 0
    cache_stats_before = read_cache_stats()
    network_plan = (fitted_network_plan or live_network_plan(config, active_symbols)) if mode == "live" else {"mode": "demo", "estimated_total_calls": 0, "estimated_network_calls": 0, "cache_avoided_calls": 0}
    network_plan["portfolio_monitor"] = portfolio_monitor
    if mode == "live" and not network_plan.get("network_allowed", False):
        reasons = "; ".join(str(value) for value in network_plan.get("blocked_reasons", []) if str(value)) or "pre-flight local não autorizou a rede"
        raise RuntimeError(f"ronda live bloqueada antes de qualquer chamada: {reasons}")
    if mode == "demo":
        rows = generate_demo_data(config)
        provider_quality: list[dict[str, Any]] = []
        context: dict[str, Any] = {"news_scores": {}, "macro_score": 50.0, "macro_series": {}, "news_available": True, "macro_available": True}
        source_note = "dados sintéticos determinísticos para validação do MVP"
    else:
        rows, provider_quality, context = fetch_live_data(config, active_symbols, previous_payload)
        source_note = "dados recolhidos por APIs configuradas; confirme timestamps e licenças"
        if args.universe_profile != "core":
            source_note += f"; perfil de universo {args.universe_profile}"
        if args.universe_profile == "expanded":
            source_note += f"; coorte {cohort_plan.get('index', 0) + 1}/{cohort_plan.get('rounds', 1)}"
        if active_symbols is not None:
            source_note += "; coorte ativa — os restantes ativos usam a última leitura live local"
    if not rows:
        raise RuntimeError("não existem dados para calcular sinais")
    signals = latest_signals(rows, config, context)
    benchmark_available = any(row["symbol"] == "GLOBAL" for row in rows)
    context_available = mode == "demo" or not config.get("require_context_for_action", True) or (context.get("news_available", False) and context.get("macro_available", False))
    signals = guard_signals(signals, mode, benchmark_available, context_available)
    bt = backtest(rows, config)
    bt["walk_forward"] = walk_forward_backtest(rows, config)
    quality = quality_rows(rows, config, provider_quality)
    latest_date = max(row["date"] for row in rows)
    date_values = sorted({row["date"] for row in rows})
    walk_forward_window = int(config.get("backtest", {}).get("walk_forward_train_days", 400)) + int(config.get("backtest", {}).get("walk_forward_test_days", 100))
    evaluation_buffer = max([int(value) for value in config.get("evaluation_horizons", [5, 20])] or [20]) + 20
    history_window = max(181, walk_forward_window + evaluation_buffer)
    history_start = date_values[max(0, len(date_values) - history_window)]
    history = [row for row in rows if row["date"] >= history_start]
    payload = {
        "meta": {
            "as_of": latest_date,
            "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
            "mode": mode,
            "source_note": source_note + ("; benchmark GLOBAL ausente: ações bloqueadas" if not benchmark_available else ""),
            "benchmark_available": benchmark_available,
            "context_available": context_available,
            "news_score_symbols": len(context.get("news_scores", {})),
            "macro_score": context.get("macro_score", 50.0),
            "currency": config.get("currency", "USD"),
            "version": "0.1.0",
            "cohort": {
                "profile": cohort_plan.get("profile", args.universe_profile),
                "rotation_index": cohort_plan.get("index", 0),
                "rotation_rounds": cohort_plan.get("rounds"),
                "selected_additions": cohort_plan.get("selected_additions", []),
                "sector_coverage": cohort_plan.get("sector_coverage", []),
                "active_symbols": sorted(active_symbols) if active_symbols is not None else [],
                "rotated": active_symbols is not None,
                "automatic": bool(cohort_plan.get("automatic", False)),
                "rotation_date": cohort_plan.get("rotation_date"),
                "next_rotation_index": cohort_plan.get("next_index"),
                "next_rotation_date": cohort_plan.get("next_rotation_date"),
                "stale_symbols": sorted({str(item.get("symbol", "")).upper() for item in config.get("universe", []) if isinstance(item, dict)} - (active_symbols or set())),
            },
        },
        "config": config,
        "signals": signals,
        "decision_round": summarize_decision_round(signals, config.get("thresholds", {})),
        "backtest": bt,
        "quality": quality,
        "context": context,
        "history": history,
        "network_plan": network_plan,
    }
    payload["alerts"] = build_alerts(previous_payload, payload)
    payload["sector_summary"] = summarize_sectors(signals)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    append_signal_history(payload, args.output_dir / "signal-history.jsonl")
    outcomes_path = args.output_dir / "signal-outcomes.jsonl"
    new_outcomes = append_signal_outcomes(
        args.output_dir / "signal-history.jsonl",
        outcomes_path,
        rows,
        config.get("evaluation_horizons", [5, 20]),
    )
    outcomes_path.touch(exist_ok=True)
    outcome_horizons = list(config.get("evaluation_horizons", [5, 20]))
    payload["outcomes"] = {
        "new_records": new_outcomes,
        "horizons": outcome_horizons,
        "summary": summarize_outcomes(outcomes_path, mode, outcome_horizons),
    }
    cache_stats_after = read_cache_stats()
    payload["network_usage"] = cache_stats_delta(cache_stats_before, cache_stats_after)
    payload["cache_stats"] = cache_stats_after
    payload["artifact_status"] = {
        "core": "completed",
        "report": "pending",
        "updated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "error": "",
    }
    write_json(payload, args.output_dir / "momentum_data.json")
    write_csv(signals, args.output_dir / "signals.csv")
    write_json(payload["alerts"], args.output_dir / "alerts.json")
    try:
        write_report(payload, args.output_dir / "relatorio-momentum.md")
        archive_daily_report(payload, args.output_dir)
    except Exception as exc:  # noqa: BLE001 - core data stays usable by paper/workbook
        payload["artifact_status"].update({
            "report": "failed",
            "updated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
            "error": safe_error_message(exc),
        })
        print(f"AVISO: relatório não gerado: {safe_error_message(exc)}", file=sys.stderr)
    else:
        payload["artifact_status"].update({
            "report": "completed",
            "updated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        })
    write_json(payload, args.output_dir / "momentum_data.json")
    print(json.dumps({"mode": mode, "as_of": latest_date, "signals": len(signals), "output_dir": str(args.output_dir)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:  # noqa: BLE001 - CLI prints a concise actionable error
        print(f"ERRO: {exc}", file=sys.stderr)
        raise SystemExit(1)
