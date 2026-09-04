"""Plain-language interpretations for the radar's 0-100 indicators."""

from __future__ import annotations

from typing import Any


def _number(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def acquisition_analysis(
    average_cost: Any,
    current_price: Any,
    market_action: str | None = None,
    asset_name: str = "este ativo",
    currency: str = "",
) -> dict[str, Any]:
    """Translate a position's cost basis into a plain-language reading.

    This is deliberately separate from the market signal: a loss does not
    automatically mean sell, and a profit does not automatically mean hold.
    The returned text explains the distance to break-even and how it should be
    read alongside the asset-level radar action.
    """
    cost = _number(average_cost)
    current = _number(current_price)
    result: dict[str, Any] = {
        "available": False,
        "average_cost": cost,
        "current_price": current,
        "pnl_pct": None,
        "pnl_per_unit": None,
        "break_even_recovery_pct": None,
        "level": "Sem preço de compra",
        "band": "indisponível",
        "meaning": "O preço médio de compra não está disponível; não é possível medir ganho ou perda desta posição.",
        "action": "Confirma o preço de compra na corretora antes de interpretar o resultado.",
    }
    if cost <= 0 or current <= 0:
        return result

    pnl_pct = current / cost - 1.0
    pnl_per_unit = current - cost
    result.update({
        "available": True,
        "pnl_pct": pnl_pct,
        "pnl_per_unit": pnl_per_unit,
        "break_even_recovery_pct": (cost / current - 1.0) if current < cost else 0.0,
    })
    if pnl_pct <= -0.20:
        level, band = "Muito abaixo do custo", "-20% ou menos"
        meaning = f"{asset_name} vale menos 20% ou mais do que o teu preço médio de compra. Para voltar ao ponto de equilíbrio precisa de recuperar cerca de {(cost / current - 1.0) * 100:.1f}% a partir daqui."
    elif pnl_pct <= -0.05:
        level, band = "Abaixo do custo", "-20% a -5%"
        meaning = f"{asset_name} está abaixo do teu preço médio de compra. A perda atual não prova, sozinha, que a tese ficou errada."
    elif pnl_pct < 0.05:
        level, band = "Perto do custo", "-5% a +5%"
        meaning = f"{asset_name} está perto do teu preço médio de compra; pequenas oscilações ainda podem mudar o resultado."
    elif pnl_pct < 0.20:
        level, band = "Acima do custo", "+5% a +20%"
        meaning = f"{asset_name} está acima do teu preço médio de compra, mas ainda não é uma margem muito grande depois de custos e impostos."
    else:
        level, band = "Muito acima do custo", "+20% ou mais"
        meaning = f"{asset_name} está 20% ou mais acima do teu preço médio de compra; existe ganho acumulado que pode ser protegido com uma decisão faseada."

    market_action_text = str(market_action or "").lower()
    if "reduzir" in market_action_text or "evitar" in market_action_text:
        action = "O radar de mercado está fraco; se reduzires, a decisão pode proteger capital ou limitar perdas, mas não vendas apenas para recuperar o preço de compra."
    elif "compra" in market_action_text:
        action = "O radar de mercado está favorável; uma perda atual, por si só, não invalida a posição, mas qualquer reforço deve ser faseado."
    else:
        action = "O radar de mercado não dá um sinal forte; manter, reduzir ou reforçar depende também do teu prazo e do tamanho desta posição."
    result.update({"level": level, "band": band, "meaning": meaning, "action": action, "currency": currency})
    return result


def _row(value: float, band: str, level: str, meaning: str, action: str) -> dict[str, Any]:
    return {
        "value": round(value, 2),
        "band": band,
        "level": level,
        "meaning": meaning,
        "action": action,
    }


def metric_reading(metric: str, raw_value: Any) -> dict[str, Any]:
    """Return a beginner-friendly band, meaning and practical next step."""
    key = str(metric or "").strip().lower().replace(" ", "_")
    value = _number(raw_value)

    if key in {"score", "momentum", "trend", "macro", "news", "volume", "breadth"}:
        if value < 40:
            level, meaning, action = "Fraco", "Pouco apoio neste fator.", "Não agir só por este indicador."
            band = "0-39"
        elif value < 60:
            level, meaning, action = "Moderado / neutro", "Sinais mistos; não há impulso claro.", "Esperar confirmação de outros fatores."
            band = "40-59"
        elif value < 80:
            level, meaning, action = "Favorável", "Este fator ajuda a leitura do ativo.", "Pode justificar investigação, confirmando o risco."
            band = "60-79"
        else:
            level, meaning, action = "Muito forte", "Este fator está claramente positivo.", "Investigar uma entrada faseada; não é uma ordem automática."
            band = "80-100"
        if key == "momentum":
            meaning = {"Fraco": "O preço perdeu impulso.", "Moderado / neutro": "O preço não mostra impulso claro.", "Favorável": "O preço ganhou impulso recente.", "Muito forte": "O preço tem impulso recente muito forte."}[level]
        elif key == "trend":
            meaning = {"Fraco": "A direção recente é fraca ou descendente.", "Moderado / neutro": "A direção ainda está indecisa.", "Favorável": "A direção recente é positiva.", "Muito forte": "A direção é positiva em várias janelas."}[level]
        elif key == "volume":
            meaning = {"Fraco": "Negociou menos do que o normal.", "Moderado / neutro": "Negociou perto do normal.", "Favorável": "Houve mais atividade do que o normal.", "Muito forte": "Houve atividade fora do normal; pode confirmar ou aumentar a volatilidade."}[level]
        elif key == "news":
            meaning = {"Fraco": "As notícias recentes são negativas.", "Moderado / neutro": "As notícias são neutras ou pouco decisivas.", "Favorável": "As notícias recentes ajudam a narrativa.", "Muito forte": "As notícias são muito positivas, mas podem refletir hype."}[level]
        elif key == "macro":
            meaning = {"Fraco": "O ambiente macro dificulta entradas.", "Moderado / neutro": "O ambiente macro está misto.", "Favorável": "O ambiente macro ajuda este tipo de ativo.", "Muito forte": "O ambiente macro é muito favorável, mas pode mudar."}[level]
        elif key == "breadth":
            meaning = {"Fraco": "Poucos componentes confirmam o movimento.", "Moderado / neutro": "A confirmação entre componentes é mista.", "Favorável": "A maioria dos componentes confirma o movimento.", "Muito forte": "Quase todos os componentes confirmam o movimento."}[level]
        return _row(value, band, level, meaning, action)

    if key == "relative_strength":
        if value < 40:
            return _row(value, "0-39", "Abaixo do mercado", "O ativo está a ficar para trás do mercado de comparação.", "Não comprar apenas porque o preço subiu.")
        if value < 60:
            return _row(value, "40-59", "Parecido com o mercado", "O ativo acompanha o mercado de comparação sem vantagem clara.", "Esperar uma vantagem mais evidente.")
        if value < 80:
            return _row(value, "60-79", "Acima do mercado", "O ativo está a superar o mercado de comparação.", "Investigar se a vantagem tem confirmação.")
        return _row(value, "80-100", "Muito acima do mercado", "O ativo está a superar claramente o mercado de comparação.", "Investigar entrada faseada e risco de excesso de subida.")

    if key in {"risk", "risk_penalty"}:
        if value < 5:
            return _row(value, "0-4.9", "Baixo", "Pouca penalização por instabilidade ou queda recente.", "O risco técnico não é o principal problema neste momento.")
        if value < 12:
            return _row(value, "5-11.9", "Moderado", "Há alguma instabilidade ou queda a vigiar.", "Usar uma posição pequena e confirmar o horizonte.")
        if value < 20:
            return _row(value, "12-19.9", "Elevado", "A volatilidade ou a queda recente já pesa na decisão.", "Evitar uma entrada grande e exigir confirmação.")
        return _row(value, "20-30", "Muito elevado", "O ativo esteve instável ou caiu bastante.", "Não agir até o risco baixar ou a tese ficar muito bem justificada.")

    if key == "confidence":
        if value < 50:
            return _row(value, "0-49", "Baixa", "Os fatores discordam ou há pouco histórico.", "Tratar o sinal como frágil.")
        if value < 70:
            return _row(value, "50-69", "Média", "Há algum apoio, mas ainda existem dúvidas.", "Acompanhar e confirmar antes de aumentar posição.")
        if value < 85:
            return _row(value, "70-84", "Boa", "Os fatores são relativamente consistentes.", "Ainda confirmar dados, risco e prazo.")
        return _row(value, "85-100", "Alta", "Os fatores e o histórico estão bastante alinhados.", "Ajuda a decisão, mas não garante retorno.")

    if key == "drawdown":
        percentage = value * 100.0 if abs(value) <= 1.0 else value
        if percentage < 5:
            return _row(value, "0-4.9%", "Pequeno", "Está perto do pico recente.", "A queda recente não é o principal alerta.")
        if percentage < 15:
            return _row(value, "5-14.9%", "Moderado", "Caiu de forma visível desde o pico.", "Confirmar se a queda é normal para este ativo.")
        if percentage < 30:
            return _row(value, "15-29.9%", "Elevado", "Está bastante abaixo do pico recente.", "Evitar perseguir uma recuperação sem confirmação.")
        return _row(value, "30% ou mais", "Muito elevado", "A queda desde o pico é profunda.", "Tratar como alerta principal e reduzir o tamanho da posição.")

    if key == "cagr":
        percentage = value * 100.0 if abs(value) <= 1.0 else value
        if percentage < 0:
            return _row(value, "abaixo de 0%", "Negativo", "O backtest perdeu valor por ano em média.", "Não usar este histórico como argumento de compra.")
        if percentage < 5:
            return _row(value, "0-4.9%", "Baixo", "O crescimento anual histórico foi pequeno.", "Comparar com inflação e benchmark.")
        if percentage < 10:
            return _row(value, "5-9.9%", "Moderado", "O crescimento anual histórico foi razoável.", "Verificar custos, período e estabilidade.")
        return _row(value, "10% ou mais", "Forte", "O crescimento anual histórico foi alto.", "Confirmar que não depende de um único período.")

    if key == "sharpe":
        if value < 0:
            return _row(value, "abaixo de 0", "Fraco", "O retorno histórico não compensou a variação.", "Não confiar no resultado sem investigar o backtest.")
        if value < 0.5:
            return _row(value, "0-0.49", "Baixo", "O retorno foi pequeno face à variação.", "Tratar o resultado como pouco convincente.")
        if value < 1:
            return _row(value, "0.5-0.99", "Razoável", "Houve alguma compensação pelo risco.", "Comparar com o benchmark e com custos.")
        if value < 2:
            return _row(value, "1-1.99", "Bom", "O retorno histórico compensou melhor a variação.", "Confirmar a amostra e evitar extrapolar.")
        return _row(value, "2 ou mais", "Muito bom", "O resultado histórico parece forte face à variação.", "Verificar overfitting antes de confiar.")

    return _row(value, "sem faixa", "Sem interpretação", "O radar ainda não tem uma legenda para este parâmetro.", "Consultar a nota técnica antes de agir.")


def compact_reading(metric: str, value: Any) -> str:
    reading = metric_reading(metric, value)
    return f"{reading['level']}: {reading['meaning']}"


def display_metric_name(metric: str) -> str:
    """Use words a non-specialist recognises while retaining the technical key."""
    return {
        "momentum": "Impulso do preço",
        "relative_strength": "Comparação com o mercado",
        "trend": "Direção do preço",
        "breadth": "Confirmação do movimento",
        "volume": "Atividade de negociação",
        "news": "Clima das notícias",
        "macro": "Ambiente económico",
        "score": "Pontuação geral",
        "confidence": "Consistência dos sinais",
        "risk_penalty": "Risco técnico",
        "drawdown": "Queda desde o pico",
    }.get(str(metric or "").strip().lower(), str(metric))


def personalized_metric_reading(
    metric: str,
    raw_value: Any,
    asset: dict[str, Any] | None = None,
    signal: dict[str, Any] | None = None,
    context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Explain why a value matters for this particular asset.

    We only describe evidence present in the snapshot.  In particular, high
    volume is not labelled as panic selling unless price/news evidence also
    points that way; the volume series alone cannot identify who was buying or
    selling.
    """
    asset = asset or {}
    signal = signal or {}
    context = context or {}
    key = str(metric or "").strip().lower().replace(" ", "_")
    value = _number(raw_value)
    reading = metric_reading(key, value)
    name = str(asset.get("name") or asset.get("symbol") or "Este ativo")
    symbol = str(asset.get("symbol") or "este ativo")
    sector = str(asset.get("sector") or "este tipo de ativo")
    momentum = _number(signal.get("momentum"), 50.0)
    trend = _number(signal.get("trend"), 50.0)
    relative = _number(signal.get("relative_strength"), 50.0)
    news = _number(signal.get("news"), 50.0)

    if key == "momentum":
        if value < 40:
            text = f"O preço de {name} perdeu força recentemente; comprar agora seria tentar adivinhar uma recuperação."
        elif value < 60:
            text = f"O preço de {name} não mostra um impulso claro. Neste setor ({sector.lower()}), ainda não há uma direção suficientemente convincente."
        elif value < 80:
            text = f"O preço de {name} ganhou força nas últimas janelas. É um sinal de interesse, mas precisa de confirmação da direção e do risco."
        else:
            text = f"{name} tem um impulso muito forte. Isso pode ser tendência saudável ou entusiasmo excessivo; não perseguir a subida sem limites."
    elif key == "relative_strength":
        if value < 40:
            text = f"{name} está a render menos do que o mercado usado para comparação. Mesmo que esteja a subir, está a ficar para trás."
        elif value < 60:
            text = f"{name} acompanha o mercado sem uma vantagem clara. Ainda não há motivo para o preferir só por desempenho relativo."
        else:
            text = f"{name} está a comportar-se melhor do que o mercado de comparação. Confirma se essa vantagem aparece também na direção e nas notícias."
    elif key == "trend":
        if value < 40:
            text = f"A direção recente de {name} é fraca ou descendente; uma subida isolada pode ser apenas um ressalto."
        elif value < 60:
            text = f"A direção de {name} está indecisa. O preço ainda não construiu uma sequência suficientemente clara para uma entrada confortável."
        else:
            text = f"A direção de {name} é positiva em várias janelas. É melhor confirmação quando o impulso também acompanha."
    elif key == "breadth":
        text = f"Este valor mede se as partes que representam {name} ou o seu tema confirmam o movimento. {reading['meaning']}"
    elif key == "volume":
        if value < 40:
            text = f"{name} teve pouca atividade de negociação face ao seu padrão recente; qualquer movimento pode ser menos confiável."
        elif value < 60:
            text = f"A atividade de negociação de {name} está perto do normal. O volume não acrescenta uma confirmação forte neste momento."
        elif value < 80:
            text = f"A atividade de negociação de {name} está acima do seu normal. Há mais negociação neste ativo, mas o volume sozinho não diz se predominam compras ou vendas."
        else:
            text = f"{name} está a negociar muito acima do seu padrão. Como o impulso está em {momentum:.1f} e a direção em {trend:.1f}, o movimento pode incluir interesse e vendas nervosas; o radar não consegue chamar isto de panic sell sem dados adicionais."
    elif key == "news":
        if value >= 60:
            text = f"As notícias associadas a {name} estão a ajudar a narrativa neste snapshot. Notícias positivas podem trazer interesse, mas também hype."
        elif value < 40:
            text = f"As notícias associadas a {name} estão a pesar contra o ativo. Uma notícia não decide sozinha, mas aumenta a necessidade de esperar confirmação."
        else:
            text = f"As notícias associadas a {name} estão neutras ou pouco decisivas; não há uma história forte a empurrar o preço."
    elif key == "macro":
        text = f"O ambiente económico atual é {reading['level'].lower()} para {name} e para ativos de {sector.lower()}. Isto é contexto, não uma previsão do próximo preço."
    elif key == "score":
        text = f"A pontuação junta os sinais observados especificamente em {name}; não é uma probabilidade de lucro."
    elif key == "confidence":
        text = f"A consistência dos sinais de {name} é {reading['level'].lower()}. Mede acordo entre fatores e histórico, não certeza."
    elif key in {"risk", "risk_penalty"}:
        text = f"O risco técnico de {name} está {reading['level'].lower()}; a posição deve ser dimensionada para suportar oscilações deste ativo."
    elif key == "drawdown":
        text = f"{name} está {reading['meaning'].lower()} em relação ao seu pico recente. Uma queda grande pode criar oportunidade, mas também pode ser sinal de deterioração."
    else:
        text = f"{display_metric_name(key)} de {name}: {reading['meaning']}"

    reading = dict(reading)
    reading["display_name"] = display_metric_name(key)
    reading["personalized_meaning"] = text
    reading["context_note"] = f"Leitura específica de {symbol}; não é uma explicação genérica para todos os ativos."
    return reading
