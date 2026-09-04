"""Shared score translation for the paper ledger and local dashboard.

The scores are evidence lenses, not forecasts or price targets. Keeping the
calculation here prevents the UI and paper experiment from silently drifting.
"""

from __future__ import annotations

from typing import Any


def _number(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def build_horizon_views(signal: dict[str, Any], context: dict[str, Any] | None = None) -> dict[str, Any]:
    context = context if isinstance(context, dict) else {}

    def clamp(value: float) -> float:
        return max(0.0, min(100.0, value))

    momentum = _number(signal.get("momentum"), 50.0)
    relative = _number(signal.get("relative_strength"), 50.0)
    trend = _number(signal.get("trend"), 50.0)
    volume = _number(signal.get("volume"), 50.0)
    news = _number(signal.get("news"), 50.0)
    macro = _number(signal.get("macro"), _number(context.get("macro_score"), 50.0))
    risk = _number(signal.get("risk_penalty"), 0.0)
    series = context.get("macro_series", {}) if isinstance(context, dict) else {}
    inflation_expectation = None
    inflation_yoy = None
    t5_series = series.get("T5YIFR", []) if isinstance(series, dict) else []
    cpi_series = series.get("CPIAUCSL", []) if isinstance(series, dict) else []
    if t5_series:
        inflation_expectation = _number(t5_series[-1].get("value"), 0.0)
    if len(cpi_series) >= 13:
        latest_cpi = _number(cpi_series[-1].get("value"), 0.0)
        prior_cpi = _number(cpi_series[-13].get("value"), 0.0)
        if prior_cpi > 0:
            inflation_yoy = (latest_cpi / prior_cpi - 1.0) * 100.0
    inflation_label = "sem dados de inflação"
    if inflation_expectation is not None:
        inflation_label = f"inflação esperada {inflation_expectation:.1f}%"
    elif inflation_yoy is not None:
        inflation_label = f"inflação anual {inflation_yoy:.1f}%"

    views = {
        "short": {
            "label": "Tático · 1–5 dias",
            "score": clamp(momentum * 0.35 + volume * 0.25 + news * 0.22 + trend * 0.18 - risk * 0.8),
            "focus": "notícias, atividade de negociação e impulso recente",
        },
        "medium": {
            "label": "Swing · 1–6 meses",
            "score": clamp(momentum * 0.28 + relative * 0.28 + trend * 0.27 + macro * 0.17 - risk * 0.6),
            "focus": "direção do preço, comparação com o mercado e ambiente económico",
        },
        "long": {
            "label": "Longo prazo · 5–10 anos",
            "score": clamp(trend * 0.28 + relative * 0.24 + macro * 0.22 + (100.0 - risk * 2.0) * 0.16 + (100.0 - abs(macro - 50.0)) * 0.10),
            "focus": inflation_label,
        },
    }
    for view in views.values():
        value = view["score"]
        if value >= 75:
            action = "Entrada faseada"
        elif value >= 60:
            action = "Acompanhar / entrada pequena"
        elif value >= 45:
            action = "Esperar confirmação"
        else:
            action = "Não agir"
        view["score"] = round(value, 1)
        view["action"] = action
    views["context"] = {
        "inflation_label": inflation_label,
        "inflation_expectation": inflation_expectation,
        "inflation_yoy": inflation_yoy,
        "macro_score": round(macro, 1),
    }
    return views
