"""Deterministic, snapshot-only report commentary; never executes decisions."""

from __future__ import annotations

import math
import re
import datetime as dt
from typing import Any


COMMENTARY_TITLE = "Como agiria nesta situação"
COMMENTARY_NOTE = "Leitura condicional do snapshot, até 150 palavras por ativo. Confirma preço, custos e adequação ao teu prazo antes de decidir; não é uma ordem."


def finite(value: Any) -> float | None:
    try:
        result = float(value)
        return result if math.isfinite(result) else None
    except (TypeError, ValueError):
        return None


def action_commentary(asset: dict[str, Any], signal: dict[str, Any] | None,
                      quality: dict[str, Any] | None, meta: dict[str, Any],
                      position: dict[str, Any] | None = None) -> str:
    """Explain the existing action, without inventing prices or allocation rules."""
    symbol = re.sub(r"[^A-Za-z0-9._-]", "", str(asset.get("symbol", "")))[:20] or "Este ativo"
    signal, quality = signal or {}, quality or {}
    score = finite(signal.get("score"))
    date = str(signal.get("date") or meta.get("as_of") or "")[:10]
    dated = f" Na leitura de {date}," if re.fullmatch(r"\d{4}-\d{2}-\d{2}", date) else " Nesta leitura,"
    action = str(signal.get("action", "")).casefold()
    status = str(quality.get("status", "")).upper()
    # Match the engine's five-calendar-day asset freshness rule, including
    # cached/on-demand signals whose stored quality label may still say OK.
    try:
        age = (dt.date.fromisoformat(str(meta.get("as_of", ""))[:10]) - dt.date.fromisoformat(date)).days
    except ValueError:
        age = None
    stale_date = age is not None and age > 5
    invalid_date = age is None or age < 0
    sentences = [f"{symbol}:{dated} " + (f"o score é {score:.1f}/100." if score is not None and 0 <= score <= 100 else "não tenho um score válido.")]
    blocked = not signal or score is None or not 0 <= score <= 100 or status != "OK" or quality.get("cache_status") == "stale_fallback" or stale_date or invalid_date
    demo = str(meta.get("mode", "")).lower() != "live"
    incomplete = meta.get("context_available") is False or meta.get("benchmark_available") is False
    if demo:
        sentences.append("Usaria este cenário apenas para testar a ferramenta; não tomaria decisões reais com dados de demonstração ou modo não confirmado.")
    elif blocked:
        reason = "a fonte está atrasada" if status == "ATRASADO" or quality.get("cache_status") == "stale_fallback" or stale_date else "faltam dados ou confirmação da fonte"
        sentences.append(f"Não abriria nem reforçaria uma posição porque {reason}. Confirmaria a cotação e a qualidade antes de interpretar o sinal.")
    elif "não agir" in action or "nao agir" in action or incomplete:
        sentences.append("Esperaria: o modelo não autoriza agir ou falta contexto para confirmar a leitura. Verificaria o histórico, a confiança e as fontes antes de reconsiderar.")
    elif "reduzir" in action or "evitar" in action:
        sentences.append("Sem posição, evitaria entrar agora. Se já tivesse posição, reveria a tese e ponderaria reduzir se o risco excedesse o meu limite; não venderia só por causa do score.")
    elif "compra" in action:
        sentences.append("Estudaria uma entrada faseada, depois de confirmar cotação, custos e risco aceitável. Se já tivesse posição, verificaria a concentração antes de reforçar; um sinal favorável não justifica aumentar exposição por si só.")
    elif "manter" in action or "observar" in action or "aguardar" in action:
        sentences.append("Se já tivesse posição, manteria sob revisão enquanto a tese e o risco continuassem aceitáveis. Sem posição, aguardaria confirmação antes de entrar.")
    else:
        sentences.append("Esperaria por uma ação explícita e dados confirmados antes de abrir ou reforçar posição.")
    if not blocked and not demo:
        factors = [(finite(signal.get(key)), label) for key, label in (("momentum", "impulso"), ("relative_strength", "força relativa"), ("trend", "tendência"), ("volume", "volume"))]
        factors = sorted((value, label) for value, label in factors if value is not None and 0 <= value <= 100)
        if factors:
            value, label = factors[0]
            sentences.append(f"Vigiaria {label} ({value:.1f}/100), o fator mais fraco desta leitura; uma deterioração levaria a rever a decisão.")
    if position is not None:
        # Use only the already-normalized acquisition result; never compare currencies here.
        cost = position.get("acquisition_analysis") or {}
        pnl = finite(cost.get("pnl_pct")) if cost.get("available") else None
        if pnl is not None and not blocked:
            sentences.append(f"Face ao custo registado, a variação é {pnl:+.1%}; não compraria para recuperar perdas nem venderia apenas por estar em lucro.")
        else:
            sentences.append("Confirmaria o custo e o valor atual da posição na corretora antes de avaliar o resultado.")
    sentences.append("Reavaliaria com uma nova leitura confirmada, respeitando o prazo escolhido e o limite de perda definido antes da operação.")
    # Preserve whole sentences and the final review condition when variants grow.
    while len(" ".join(sentences).split()) > 150 and len(sentences) > 3:
        sentences.pop(-2)
    return " ".join(sentences)


def commentary_entries(state: dict[str, Any], *, portfolio_only: bool = False) -> list[tuple[str, str]]:
    signals = {str(x.get("symbol", "")).upper(): x for x in state.get("signals", [])}
    quality = {str(x.get("symbol", "")).upper(): x for x in state.get("quality", [])}
    positions = {str(x.get("symbol", "")).upper(): x for x in state.get("portfolio", {}).get("positions", [])}
    symbols = list(positions if portfolio_only else signals)
    if not portfolio_only:
        symbols.extend(s for s in quality if s not in symbols and s not in {"GLOBAL", "MACRO", "NEWS"} and not s.startswith("FRED:"))
    return [(s, action_commentary({"symbol": s}, signals.get(s), quality.get(s), state.get("meta", {}), positions.get(s))) for s in symbols if s]


def commentary_markdown(entries: list[tuple[str, str]]) -> str:
    return "\n".join([f"## {COMMENTARY_TITLE}", "", COMMENTARY_NOTE, "", *[f"### {symbol}\n\n{text}\n" for symbol, text in entries]])
