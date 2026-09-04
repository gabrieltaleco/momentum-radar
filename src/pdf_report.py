"""Small dependency-free PDF renderer for one radar asset report."""

from __future__ import annotations

import datetime as dt
import re
import unicodedata
from pathlib import Path
from typing import Any

try:
    from src.metric_explanations import acquisition_analysis, display_metric_name, metric_reading, personalized_metric_reading
except ModuleNotFoundError:
    from metric_explanations import acquisition_analysis, display_metric_name, metric_reading, personalized_metric_reading


PAGE_WIDTH = 595
PAGE_HEIGHT = 842
INK = (0.09, 0.15, 0.18)
MUTED = (0.40, 0.48, 0.50)
ORANGE = (0.90, 0.35, 0.18)
GREEN = (0.18, 0.55, 0.43)
PALE = (0.94, 0.96, 0.95)
LINE = (0.82, 0.87, 0.85)


def ascii_text(value: Any) -> str:
    text = "" if value is None else str(value)
    if any(marker in text for marker in ("Ã", "Â", "â")):
        try:
            text = text.encode("latin-1").decode("utf-8")
        except (UnicodeEncodeError, UnicodeDecodeError):
            pass
    replacements = {
        "→": " -> ",
        "←": " <- ",
        "↓": " download ",
        "⇄": " comparar ",
        "·": " / ",
        "–": "-",
        "—": "-",
        "≥": ">=",
        "≤": "<=",
        "✓": "OK",
    }
    for original, replacement in replacements.items():
        text = text.replace(original, replacement)
    text = unicodedata.normalize("NFKD", text)
    text = "".join(character for character in text if not unicodedata.combining(character))
    return re.sub(r"\s+", " ", text.encode("ascii", "replace").decode("ascii")).strip()


def clip(value: Any, length: int) -> str:
    """Return short, PDF-safe text without cutting the layout."""
    text = ascii_text(value).replace("|", "/").strip()
    return text if len(text) <= length else text[: max(1, length - 3)] + "..."


def concise_quality_message(item: dict[str, Any]) -> str:
    """Keep provider errors readable and away from the PDF footer."""
    message = ascii_text(item.get("message", "verificar fonte"))
    lowered = message.lower()
    if "http 404" in lowered or "no data found" in lowered:
        return "Ticker sem dados no provider; confirmar simbolo e bolsa."
    if "http 429" in lowered or "rate limit" in lowered:
        return "Provider limitou pedidos; usar cache e aguardar o reset."
    if len(message) > 120:
        return message[:117].rstrip() + "..."
    return message


def escape_pdf(value: Any) -> bytes:
    text = ascii_text(value).replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
    return text.encode("latin-1", "replace")


def wrap(value: Any, max_chars: int) -> list[str]:
    text = ascii_text(value).strip()
    if not text:
        return [""]
    words = text.split()
    lines: list[str] = []
    current = ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if current and len(candidate) > max_chars:
            lines.append(current)
            current = word
        else:
            current = candidate
    if current:
        lines.append(current)
    return lines


def wrapped_end_y(y: float, value: Any, width: float, size: float, leading: float) -> float:
    """Return the cursor immediately below a wrapped text block."""
    max_chars = max(12, int(width / max(4.2, size * 0.48)))
    return y - len(wrap(value, max_chars)) * leading


class Page:
    def __init__(self, number: int):
        self.number = number
        self.commands: list[bytes] = []

    def color(self, rgb: tuple[float, float, float]) -> None:
        self.commands.append(f"{rgb[0]:.3f} {rgb[1]:.3f} {rgb[2]:.3f} rg".encode())

    def box(self, x: float, y: float, width: float, height: float, rgb: tuple[float, float, float], radius: float = 0) -> None:
        self.color(rgb)
        if radius:
            self.commands.append(f"{x:.1f} {y:.1f} {width:.1f} {height:.1f} re f".encode())
        else:
            self.commands.append(f"{x:.1f} {y:.1f} {width:.1f} {height:.1f} re f".encode())

    def rule(self, x: float, y: float, width: float, rgb: tuple[float, float, float] = LINE) -> None:
        self.color(rgb)
        self.commands.append(f"{x:.1f} {y:.1f} m {x + width:.1f} {y:.1f} l 0.7 w S".encode())

    def text(self, x: float, y: float, value: Any, size: float = 10, bold: bool = False, rgb: tuple[float, float, float] = INK) -> None:
        self.color(rgb)
        font = "/F2" if bold else "/F1"
        self.commands.append(b"BT " + font.encode() + f" {size:.1f} Tf {x:.1f} {y:.1f} Td (".encode() + escape_pdf(value) + b") Tj ET")

    def wrapped(self, x: float, y: float, value: Any, width: float, size: float = 9, leading: float = 13, rgb: tuple[float, float, float] = MUTED, bold: bool = False) -> float:
        max_chars = max(12, int(width / max(4.2, size * 0.48)))
        cursor = y
        for line in wrap(value, max_chars):
            self.text(x, cursor, line, size, bold, rgb)
            cursor -= leading
        return wrapped_end_y(y, value, width, size, leading)


def metric(page: Page, x: float, y: float, label: str, value: Any, width: float = 150) -> None:
    page.text(x, y, label.upper(), 7.5, False, MUTED)
    page.text(x, y - 16, value, 13, True, INK)
    page.rule(x, y - 25, width)


def append_commentary_pages(pages: list[Page], entries: list[tuple[str, str]], meta: dict[str, Any]) -> None:
    """Paginate full commentary without shrinking or truncating paragraphs."""
    try:
        from src.action_commentary import COMMENTARY_NOTE
    except ModuleNotFoundError:
        from action_commentary import COMMENTARY_NOTE
    cursor = 0.0
    for symbol, text in entries:
        height = 48 + (680 - wrapped_end_y(680, text, PAGE_WIDTH - 116, 9, 13))
        if cursor - height < 65:
            page = Page(len(pages) + 1)
            pages.append(page)
            page.box(0, 0, PAGE_WIDTH, PAGE_HEIGHT, (0.98, 0.99, 0.98))
            page.box(0, PAGE_HEIGHT - 126, PAGE_WIDTH, 126, INK)
            page.text(46, PAGE_HEIGHT - 45, "RADAR / LEITURA POR ATIVO", 8, False, (0.55, 0.66, 0.65))
            page.text(46, PAGE_HEIGHT - 80, "Como agiria nesta situacao", 22, True, (0.96, 0.98, 0.96))
            page.text(46, PAGE_HEIGHT - 104, "Ate 150 palavras por ativo / regras locais / sem ordens", 8.5, False, (0.70, 0.78, 0.77))
            cursor = page.wrapped(46, 688, COMMENTARY_NOTE, PAGE_WIDTH - 92, 8, 11, MUTED) - 22
            page.rule(46, 47, PAGE_WIDTH - 92)
            page.text(46, 28, f"radar / snapshot {meta.get('as_of', '-')} / pagina {len(pages)}", 7, False, MUTED)
        page.box(46, cursor - height, PAGE_WIDTH - 92, height, PALE)
        page.text(58, cursor - 19, symbol, 10, True, ORANGE)
        page.wrapped(58, cursor - 38, text, PAGE_WIDTH - 116, 9, 13, INK)
        cursor -= height + 16


def build_asset_pdf(catalog_item: dict[str, Any], signal: dict[str, Any] | None, quality: dict[str, Any], meta: dict[str, Any], context: dict[str, Any], output_path: Path | None = None, position: dict[str, Any] | None = None, journal_note: str = "", outcome_summary: dict[str, Any] | None = None, alert_events: list[dict[str, Any]] | None = None) -> bytes:
    pages: list[Page] = []
    page = Page(1)
    pages.append(page)
    left = 46
    usable = PAGE_WIDTH - 92
    cursor = PAGE_HEIGHT - 48

    page.box(0, 0, PAGE_WIDTH, PAGE_HEIGHT, (0.98, 0.99, 0.98))
    page.box(0, PAGE_HEIGHT - 170, PAGE_WIDTH, 170, INK)
    page.text(left, cursor, "RADAR / RELATORIO DE ATIVO", 8, False, (0.55, 0.66, 0.65))
    page.text(left, cursor - 37, catalog_item.get("symbol", "Ativo"), 31, True, (0.96, 0.98, 0.96))
    page.text(left, cursor - 62, catalog_item.get("name", ""), 11, False, (0.70, 0.78, 0.77))
    page.text(left, cursor - 87, f"{catalog_item.get('type', 'Ativo')}  /  {catalog_item.get('sector', 'Sem setor')}", 8.5, False, (0.70, 0.78, 0.77))
    page.text(PAGE_WIDTH - left - 126, cursor - 4, "SNAPSHOT", 7.5, False, (0.55, 0.66, 0.65))
    page.text(PAGE_WIDTH - left - 126, cursor - 22, meta.get("as_of", "-"), 11, True, (0.96, 0.98, 0.96))
    page.text(PAGE_WIDTH - left - 126, cursor - 42, f"modo {meta.get('mode', '-')}", 8.5, False, (0.70, 0.78, 0.77))
    cursor = PAGE_HEIGHT - 205

    page.text(left, cursor, "DECISAO POR HORIZONTE", 8, True, ORANGE)
    cursor -= 22
    horizons = (signal or {}).get("horizons", {})
    cards = [("short", "TATICO / 1-5 DIAS"), ("medium", "SWING / 1-6 MESES"), ("long", "LONGO / 5-10 ANOS")]
    card_gap = 9
    card_width = (usable - 2 * card_gap) / 3
    for index, (key, label) in enumerate(cards):
        x = left + index * (card_width + card_gap)
        view = horizons.get(key, {}) if isinstance(horizons, dict) else {}
        page.box(x, cursor - 83, card_width, 83, PALE)
        page.text(x + 10, cursor - 17, label, 7, False, MUTED)
        page.text(x + 10, cursor - 39, view.get("action", "Sem leitura"), 9.5, True, INK)
        page.text(x + 10, cursor - 59, f"score {float(view.get('score', 0) or 0):.1f}/100", 9, False, ORANGE)
        page.wrapped(x + 10, cursor - 74, view.get("focus", "Contexto indisponivel"), card_width - 20, 7.5, 9, MUTED)
    cursor -= 111

    if signal:
        score_value = float(signal.get("score", 0) or 0)
        score_reading = metric_reading("score", score_value)
        confidence_value = float(signal.get("confidence", 0) or 0)
        confidence_reading = metric_reading("confidence", confidence_value)
        risk_value = float(signal.get("risk_penalty", 0) or 0)
        risk_reading = metric_reading("risk_penalty", risk_value)
        drawdown_value = float(signal.get("drawdown", 0) or 0)
        drawdown_reading = metric_reading("drawdown", drawdown_value)
        page.text(left, cursor, "LEITURA DO RADAR", 8, True, ORANGE)
        cursor -= 21
        page.box(left, cursor - 66, usable, 66, INK)
        page.text(left + 14, cursor - 22, signal.get("action", "Sem acao"), 17, True, (1.0, 0.68, 0.52))
        page.wrapped(left + 14, cursor - 43, signal.get("notes", "Sem explicacao adicional."), usable - 155, 7.5, 9, (0.70, 0.78, 0.77))
        page.text(PAGE_WIDTH - left - 93, cursor - 20, f"{score_value:.1f}", 23, True, (0.96, 0.98, 0.96))
        page.text(PAGE_WIDTH - left - 93, cursor - 42, f"{score_reading['level']} / 100", 7.5, False, (0.55, 0.66, 0.65))
        page.text(left + 14, cursor - 59, f"Confianca {confidence_value:.1f}: {confidence_reading['level']}  |  Risco {risk_value:.1f}/30: {risk_reading['level']}  |  Drawdown {drawdown_value:.1%}: {drawdown_reading['level']}", 7.2, False, (0.70, 0.78, 0.77))
        cursor -= 95
        page.text(left, cursor, "FATORES", 8, True, ORANGE)
        cursor -= 18
        factors = [("Impulso do preco", "momentum"), ("Comparacao com o mercado", "relative_strength"), ("Direcao do preco", "trend"), ("Atividade de negociacao", "volume"), ("Clima das noticias", "news"), ("Ambiente economico", "macro")]
        for index, (label, key) in enumerate(factors):
            col = index % 2
            row = index // 2
            x = left + col * (usable / 2)
            y = cursor - row * 29
            value = float(signal.get(key, 0) or 0)
            reading = personalized_metric_reading(key, value, catalog_item, signal, context)
            compact_level = {
                "Abaixo do mercado": "Abaixo",
                "Parecido com o mercado": "Parecido",
                "Acima do mercado": "Acima",
                "Muito acima do mercado": "Muito acima",
                "Moderado / neutro": "Moderado",
            }.get(reading["level"], reading["level"])
            page.text(x, y, f"{label}: {compact_level}", 7.6, False, MUTED)
            page.text(x + 180, y, f"{value:.1f}", 8.5, True, INK)
            page.box(x, y - 11, 98, 4, LINE)
            page.box(x, y - 11, max(0, min(98, value * 0.98)), 4, ORANGE)
        cursor -= 102
    else:
        page.text(left, cursor, "ESTADO DA ANALISE", 8, True, ORANGE)
        cursor -= 21
        page.box(left, cursor - 76, usable, 76, PALE)
        page.text(left + 14, cursor - 25, "Sem dados no snapshot atual", 14, True, INK)
        page.wrapped(left + 14, cursor - 45, "Este ativo existe no catalogo, mas ainda nao tem uma leitura recolhida. Nao agir antes de o configurar e analisar live.", usable - 28, 8.5, 12, MUTED)
        cursor -= 106

    if position:
        cost = position.get("acquisition_analysis") or acquisition_analysis(
            position.get("avg_cost"),
            (signal or {}).get("price"),
            (signal or {}).get("action"),
            catalog_item.get("name", catalog_item.get("symbol", "este ativo")),
            position.get("currency", ""),
        )
        page.text(left, cursor, "A TUA COMPRA", 8, True, ORANGE)
        cursor -= 17
        page.box(left, cursor - 68, usable, 68, PALE)
        if cost.get("available"):
            pnl_pct = float(cost.get("pnl_pct", 0) or 0)
            page.text(left + 12, cursor - 19, f"Preco medio {float(position.get('avg_cost', 0) or 0):.6g} {position.get('currency', meta.get('currency', 'USD'))}", 8.5, True, INK)
            page.text(left + 180, cursor - 19, f"Resultado por unidade {pnl_pct:+.1%}", 8.5, True, ORANGE if pnl_pct < 0 else GREEN)
            page.wrapped(left + 12, cursor - 37, cost.get("meaning", ""), usable - 24, 7.5, 9, MUTED)
            page.wrapped(left + 12, cursor - 56, f"Radar + compra: {cost.get('action', '')}", usable - 24, 7.2, 9, INK)
        else:
            page.wrapped(left + 12, cursor - 22, cost.get("meaning", "Preço de compra indisponível."), usable - 24, 8, 11, MUTED)
        cursor -= 88

    if journal_note:
        page.text(left, cursor, "NOTA PESSOAL", 8, True, ORANGE)
        cursor -= 17
        page.box(left, cursor - 46, usable, 46, PALE)
        page.wrapped(left + 12, cursor - 20, journal_note, usable - 24, 8, 11, MUTED)
        cursor -= 66

    if outcome_summary:
        page.text(left, cursor, "EVIDENCIA HISTORICA", 8, True, ORANGE)
        cursor -= 17
        page.box(left, cursor - 56, usable, 56, PALE)
        page.text(left + 12, cursor - 17, "Outcomes fechados deste simbolo", 8.5, True, INK)
        row_y = cursor - 32
        for horizon, outcome in list(outcome_summary.items())[:3]:
            positive = "-" if outcome.get("positive_rate") is None else f"{float(outcome['positive_rate']):.1%}"
            average = "-" if outcome.get("average_return") is None else f"{float(outcome['average_return']):.2%}"
            page.text(left + 12, row_y, f"{horizon} obs.  |  {outcome.get('records', 0)} registos  |  positivo {positive}  |  media {average}", 7.4, False, MUTED)
            row_y -= 10
        cursor -= 76

    page.text(left, cursor, "CONTEXTO E QUALIDADE", 8, True, ORANGE)
    cursor -= 22
    metric(page, left, cursor, "Ambiente economico", f"{float(context.get('macro_score', meta.get('macro_score', 50)) or 50):.1f}/100")
    metric(page, left + 180, cursor, "Mercado de comparacao", "Disponivel" if meta.get("benchmark_available") else "Em falta")
    metric(page, left + 360, cursor, "Fonte do ativo", quality.get("status", "Sem dados"))
    cursor -= 59
    inflation = ((signal or {}).get("horizons", {}) or {}).get("context", {}).get("inflation_label", "sem leitura de inflacao")
    page.wrapped(left, cursor, f"Contexto de entrada: {inflation}. Este quadro nao estima um preco futuro; mostra a qualidade relativa da entrada em cada prazo.", usable, 8.5, 12, MUTED)
    cursor -= 42
    # Keep the responsible-use note in the reserved footer area. The previous
    # fixed cursor could place wrapped lines on top of the page footer when
    # optional sections (position, journal, outcomes) were present.
    note_cursor = max(58, cursor + 18)
    page.rule(left, note_cursor + 17, usable)
    page.wrapped(left, note_cursor, "Uso responsavel: este relatorio organiza dados de mercado e nao constitui recomendacao financeira nem ordem. Confirma timestamps, custos, impostos, liquidez e adequacao ao teu perfil.", usable, 7.2, 8.5, MUTED)
    page.text(left, 26, f"radar / gerado {dt.datetime.now().strftime('%Y-%m-%d %H:%M')}  |  pagina 1", 7, False, MUTED)

    # Page 2 is written for this asset, not copied from a generic glossary.
    page = Page(2)
    pages.append(page)
    page.box(0, 0, PAGE_WIDTH, PAGE_HEIGHT, (0.98, 0.99, 0.98))
    page.box(0, PAGE_HEIGHT - 132, PAGE_WIDTH, 132, INK)
    page.text(left, PAGE_HEIGHT - 49, "RADAR / GUIA DESTE ATIVO", 8, False, (0.55, 0.66, 0.65))
    page.text(left, PAGE_HEIGHT - 84, "Porque aparecem estes valores?", 24, True, (0.96, 0.98, 0.96))
    page.wrapped(left, PAGE_HEIGHT - 105, f"Estas frases explicam os sinais observados em {catalog_item.get('name', catalog_item.get('symbol', 'este ativo'))}; nao sao uma legenda generica.", usable, 8.5, 12, (0.70, 0.78, 0.77))
    factors_for_guide = [("Impulso do preco", "momentum"), ("Comparacao com o mercado", "relative_strength"), ("Direcao do preco", "trend"), ("Atividade de negociacao", "volume"), ("Clima das noticias", "news"), ("Ambiente economico", "macro")]
    card_gap = 9
    card_width = (usable - card_gap) / 2
    top = PAGE_HEIGHT - 178
    card_height = 145
    for index, (label, key) in enumerate(factors_for_guide):
        column = index % 2
        row = index // 2
        x = left + column * (card_width + card_gap)
        y = top - row * (card_height + 10)
        page.box(x, y - card_height, card_width, card_height, PALE)
        if signal:
            value = float(signal.get(key, 0) or 0)
            reading = personalized_metric_reading(key, value, catalog_item, signal, context)
            page.text(x + 10, y - 18, label, 8.5, True, INK)
            page.text(x + 10, y - 34, f"{value:.1f}/100  |  {reading['level']}  ({reading['band']})", 7.4, True, ORANGE)
            description_cursor = page.wrapped(x + 10, y - 53, reading["personalized_meaning"], card_width - 20, 8, 11, MUTED)
            # Descriptions have variable length. Anchor the action to the
            # actual end of the wrapped text instead of a fixed y coordinate.
            page.wrapped(x + 10, description_cursor - 10, f"Na pratica: {reading['action']}", card_width - 20, 7.6, 10, INK, True)
        else:
            page.text(x + 10, y - 18, label, 8.5, True, INK)
            page.wrapped(x + 10, y - 40, "Sem dados live deste ativo. A explicacao so fica disponivel depois de recolher uma serie com qualidade.", card_width - 20, 8, 11, MUTED)
    page.rule(left, 74, usable)
    page.wrapped(left, 57, "Como usar: escolhe primeiro o prazo, lê o contexto deste ativo e só depois decide o tamanho da posição. Volume alto não significa automaticamente compras ou panic sell.", usable, 8, 11, MUTED)
    page.text(left, 26, f"radar / gerado {dt.datetime.now().strftime('%Y-%m-%d %H:%M')}  |  pagina 2", 7, False, MUTED)

    # Page 3 keeps the reusable glossary separate from the asset-specific text.
    page = Page(3)
    pages.append(page)
    page.box(0, 0, PAGE_WIDTH, PAGE_HEIGHT, (0.98, 0.99, 0.98))
    page.box(0, PAGE_HEIGHT - 132, PAGE_WIDTH, 132, INK)
    page.text(left, PAGE_HEIGHT - 49, "RADAR / LEGENDA SIMPLES", 8, False, (0.55, 0.66, 0.65))
    page.text(left, PAGE_HEIGHT - 84, "O que significam estes numeros?", 24, True, (0.96, 0.98, 0.96))
    page.wrapped(left, PAGE_HEIGHT - 105, "Usa esta pagina como uma legenda. O radar organiza sinais; nao transforma nenhuma metrica numa garantia de lucro.", usable, 8.5, 12, (0.70, 0.78, 0.77))
    glossary = [
        ("Pontuacao geral", "Nota de 0 a 100 que junta os sinais. Alta significa alinhamento; nao e uma probabilidade de ganhar dinheiro."),
        ("Consistencia dos sinais", "Mede se os fatores concordam e se existe historico suficiente. Nao elimina surpresas."),
        ("Risco tecnico", "Penalizacao quando o ativo esteve instavel ou caiu bastante. Quanto maior, mais cuidado pede."),
        ("Queda desde o pico", "Queda desde o ultimo maximo recente. 20% significa estar 20% abaixo desse maximo."),
        ("Impulso do preco", "Mostra se o movimento recente ganhou ou perdeu forca."),
        ("Comparacao com o mercado", "Diz se o ativo esta melhor ou pior do que o grupo usado como referencia."),
        ("Direcao do preco", "Mostra se o preco construiu uma direcao consistente; nao adivinha o proximo preco."),
        ("Atividade de negociacao", "Compara a quantidade negociada com o normal do proprio ativo. Nao distingue sozinha compras de vendas."),
        ("Clima das noticias", "Resume noticias recentes ligadas ao ativo. 50 e neutro; uma manchete nao preve o futuro."),
        ("Ambiente economico", "Resume se inflacao, juros e moeda ajudam ou dificultam este tipo de ativo."),
        ("Mercado de comparacao", "Grupo de referencia usado para evitar uma leitura isolada do ativo."),
        ("Crescimento e retorno/risco", "Medidas do backtest historico. Descrevem o passado e nao prometem o futuro."),
    ]
    card_gap = 9
    card_width = (usable - card_gap) / 2
    top = PAGE_HEIGHT - 178
    card_height = 83
    for index, (label, definition) in enumerate(glossary):
        column = index % 2
        row = index // 2
        x = left + column * (card_width + card_gap)
        y = top - row * (card_height + 9)
        page.box(x, y - card_height, card_width, card_height, PALE)
        page.text(x + 10, y - 17, label, 8.5, True, INK)
        page.wrapped(x + 10, y - 33, definition, card_width - 20, 7.6, 10, MUTED)
    page.rule(left, 74, usable)
    page.wrapped(left, 57, "Como usar: escolhe primeiro o prazo do investimento, verifica a qualidade dos dados e decide o tamanho da posicao. Uma entrada faseada reduz o risco de depender de um unico dia.", usable, 8, 11, MUTED)
    page.text(left, 26, f"radar / gerado {dt.datetime.now().strftime('%Y-%m-%d %H:%M')}  |  pagina 3", 7, False, MUTED)

    if alert_events:
        page = Page(4)
        pages.append(page)
        page.box(0, 0, PAGE_WIDTH, PAGE_HEIGHT, (0.98, 0.99, 0.98))
        page.box(0, PAGE_HEIGHT - 132, PAGE_WIDTH, 132, INK)
        page.text(left, PAGE_HEIGHT - 49, "RADAR / HISTORICO RECENTE", 8, False, (0.55, 0.66, 0.65))
        page.text(left, PAGE_HEIGHT - 84, "O que mudou?", 24, True, (0.96, 0.98, 0.96))
        page.wrapped(left, PAGE_HEIGHT - 105, "Estas transicoes comparam o snapshot atual com a leitura anterior comparavel. Descrevem uma mudanca observada; nao sao uma previsao.", usable, 8.5, 12, (0.70, 0.78, 0.77))
        cursor = PAGE_HEIGHT - 178
        for event in alert_events[:8]:
            page.box(left, cursor - 70, usable, 70, PALE)
            transition = f"{event.get('from_action', '-')}  ->  {event.get('to_action', '-')}"
            delta = event.get("score_delta")
            delta_text = "score sem variacao" if delta is None else f"score {float(delta):+.1f}"
            page.text(left + 12, cursor - 20, transition, 10, True, INK)
            page.text(PAGE_WIDTH - left - 92, cursor - 20, delta_text, 8.5, True, ORANGE)
            page.wrapped(left + 12, cursor - 40, event.get("reason", "mudanca registada no snapshot"), usable - 24, 8.2, 11, MUTED)
            cursor -= 84
        page.rule(left, 74, usable)
        page.wrapped(left, 57, "Como usar: confirma a data, a qualidade da fonte e o motivo da transicao antes de alterar uma decisao. Exportar o PDF nao faz novas chamadas.", usable, 8, 11, MUTED)
        page.text(left, 26, f"radar / gerado {dt.datetime.now().strftime('%Y-%m-%d %H:%M')}  |  pagina 4", 7, False, MUTED)

    try:
        from src.action_commentary import action_commentary
    except ModuleNotFoundError:
        from action_commentary import action_commentary
    append_commentary_pages(pages, [(str(catalog_item.get("symbol", "Ativo")), action_commentary(catalog_item, signal, quality, meta, position))], meta)
    return write_pdf(pages, output_path)


def build_daily_pdf(payload: dict[str, Any], output_path: Path | None = None) -> bytes:
    """Build a shareable, local PDF snapshot of the daily radar report."""
    meta = payload.get("meta", {}) if isinstance(payload.get("meta", {}), dict) else {}
    signals = [item for item in payload.get("signals", []) if isinstance(item, dict)]
    sector_summary = [item for item in payload.get("sector_summary", []) if isinstance(item, dict)]
    quality = [item for item in payload.get("quality", []) if isinstance(item, dict)]
    alerts = payload.get("alerts", {}) if isinstance(payload.get("alerts", {}), dict) else {}
    events = [item for item in alerts.get("events", []) if isinstance(item, dict)]
    network_usage = payload.get("network_usage", {}) if isinstance(payload.get("network_usage", {}), dict) else {}
    cache_stats = payload.get("cache_stats", {}) if isinstance(payload.get("cache_stats", {}), dict) else {}
    outcomes = payload.get("outcomes", {}) if isinstance(payload.get("outcomes", {}), dict) else {}

    def background(page: Page, page_number: int, title: str, subtitle: str = "") -> None:
        page.box(0, 0, PAGE_WIDTH, PAGE_HEIGHT, (0.98, 0.99, 0.98))
        page.box(0, PAGE_HEIGHT - 126, PAGE_WIDTH, 126, INK)
        page.text(46, PAGE_HEIGHT - 45, "RADAR / RELATORIO DIARIO", 8, False, (0.55, 0.66, 0.65))
        page.text(46, PAGE_HEIGHT - 82, title, 23, True, (0.96, 0.98, 0.96))
        if subtitle:
            page.text(46, PAGE_HEIGHT - 104, subtitle, 8.5, False, (0.70, 0.78, 0.77))
        page.rule(46, 47, PAGE_WIDTH - 92)
        page.text(46, 28, f"radar / snapshot {meta.get('as_of', '-')}  |  pagina {page_number}", 7, False, MUTED)
        page.text(PAGE_WIDTH - 188, 28, "sem ordens / leitura descritiva", 7, False, MUTED)

    def metric_box(page: Page, x: float, y: float, width: float, label: str, value: Any, detail: str) -> None:
        page.box(x, y - 76, width, 76, PALE)
        page.text(x + 11, y - 19, label.upper(), 7.2, False, MUTED)
        page.text(x + 11, y - 43, value, 17, True, INK)
        page.text(x + 11, y - 62, clip(detail, 27), 7.5, False, MUTED)

    pages: list[Page] = []
    page = Page(1)
    pages.append(page)
    background(page, 1, "Leitura de mercado", f"snapshot {meta.get('as_of', '-')}  /  modo {meta.get('mode', '-')}")
    buy_count = sum("compra" in str(item.get("action", "")).lower() for item in signals)
    context_label = "completo" if meta.get("context_available") else "incompleto"
    metrics = [
        ("Sinais", len(signals), "ativos no snapshot"),
        ("Compras", buy_count, "sinais ativos"),
        ("Contexto", context_label, "noticias / macro"),
        ("Chamadas", int(network_usage.get("outbound_calls", 0)), "tentadas nesta execucao"),
    ]
    metric_width = (PAGE_WIDTH - 92 - 27) / 4
    for index, (label, value, detail) in enumerate(metrics):
        metric_box(page, 46 + index * (metric_width + 9), 656, metric_width, label, value, detail)
    page.text(46, 545, "Resumo", 10, True, ORANGE)
    page.wrapped(46, 525, meta.get("source_note", "Leitura gerada a partir do snapshot local."), PAGE_WIDTH - 92, 9, 13, MUTED)
    page.text(46, 472, "Pulso por setor", 10, True, ORANGE)
    page.text(46, 452, "SETOR", 7, False, MUTED)
    page.text(300, 452, "SINAIS", 7, False, MUTED)
    page.text(366, 452, "SCORE MEDIO", 7, False, MUTED)
    page.text(468, 452, "COMPRAS", 7, False, MUTED)
    cursor = 430
    for row in sector_summary[:10]:
        page.rule(46, cursor + 8, PAGE_WIDTH - 92, LINE)
        page.text(46, cursor - 4, clip(row.get("sector", "Sem setor"), 38), 8.5, False, INK)
        page.text(300, cursor - 4, int(row.get("signals", 0) or 0), 8.5, False, INK)
        average = row.get("average_score")
        page.text(366, cursor - 4, "-" if average is None else f"{float(average):.1f}", 8.5, False, INK)
        page.text(468, cursor - 4, int(row.get("buy_signals", 0) or 0), 8.5, False, ORANGE)
        cursor -= 27
    if not sector_summary:
        page.text(46, cursor, "Sem resumo setorial disponível.", 9, False, MUTED)

    page = Page(2)
    pages.append(page)
    background(page, 2, "Ranking e qualidade", "scores atuais e estado das fontes")
    page.text(46, 680, "Top sinais", 10, True, ORANGE)
    columns = [(46, "ATIVO"), (105, "SETOR"), (302, "SCORE"), (360, "CONFIANCA"), (440, "ACAO")]
    for x, label in columns:
        page.text(x, 660, label, 7, False, MUTED)
    cursor = 638
    ordered = sorted(signals, key=lambda item: float(item.get("score", -1) or -1), reverse=True)
    for signal in ordered[:14]:
        page.rule(46, cursor + 8, PAGE_WIDTH - 92, LINE)
        page.text(46, cursor - 4, clip(signal.get("symbol", "-"), 9), 8.5, True, INK)
        page.text(105, cursor - 4, clip(signal.get("sector", "-"), 32), 8.2, False, INK)
        page.text(302, cursor - 4, f"{float(signal.get('score', 0) or 0):.1f}", 8.5, True, ORANGE)
        page.text(360, cursor - 4, f"{float(signal.get('confidence', 0) or 0):.1f}", 8.5, False, INK)
        page.text(440, cursor - 4, clip(signal.get("action", "-"), 20), 8, False, INK)
        cursor -= 29
    if not ordered:
        page.text(46, cursor, "Sem sinais disponíveis.", 9, False, MUTED)
    page.text(46, 218, "Fontes a rever", 10, True, ORANGE)
    failed = [item for item in quality if str(item.get("status", "")).upper() not in {"OK", "", "FORA_DA_COORTE"}]
    cursor = 194
    for item in failed[:8]:
        if cursor < 82:
            break
        page.text(46, cursor, clip(item.get("symbol", "-"), 18), 8.5, True, INK)
        page.text(135, cursor, clip(item.get("status", "ERRO"), 12), 8.5, False, ORANGE)
        end_y = page.wrapped(205, cursor, concise_quality_message(item), 344, 8, 10, MUTED)
        cursor = min(cursor - 25, end_y - 9)
    if not failed:
        page.text(46, cursor, "Todas as fontes do snapshot estão OK.", 9, False, GREEN)

    page = Page(3)
    pages.append(page)
    background(page, 3, "Supervisão", "mudanças que merecem uma segunda leitura")
    page.text(46, 680, "Mudanças desde a execução anterior", 10, True, ORANGE)
    cursor = 650
    for event in events[:9]:
        page.box(46, cursor - 37, PAGE_WIDTH - 92, 42, PALE)
        page.text(57, cursor - 14, clip(f"{event.get('symbol', 'Radar')} · {event.get('type', 'mudança')}", 48), 8.5, True, INK)
        delta = event.get("score_delta")
        page.text(470, cursor - 14, "-" if delta is None else f"{float(delta):+.1f}", 8.5, True, ORANGE)
        page.wrapped(57, cursor - 29, f"{event.get('from_action', '-')} -> {event.get('to_action', '-')} · {event.get('reason', 'mudança registada')}", PAGE_WIDTH - 114, 7.7, 9, MUTED)
        cursor -= 51
    if not events:
        page.text(46, cursor, "Nenhuma transição relevante neste snapshot.", 9, False, MUTED)
    page.text(46, 180, "Nota de segurança", 10, True, ORANGE)
    page.wrapped(46, 158, "Qualidade fora de OK, contexto incompleto ou dados atrasados devem bloquear uma decisão até a fonte ser confirmada. Este PDF não envia ordens nem atualiza providers.", PAGE_WIDTH - 92, 9, 13, MUTED)

    page = Page(4)
    pages.append(page)
    background(page, 4, "Auditoria de custo", "quota, cache e resultados observados")
    page.text(46, 680, "Chamadas e cache", 10, True, ORANGE)
    page.text(46, 655, f"Chamadas externas nesta execução: {int(network_usage.get('outbound_calls', 0))}", 9, True, INK)
    by_bucket = network_usage.get("outbound_calls_by_bucket", {})
    cursor = 630
    if isinstance(by_bucket, dict) and by_bucket:
        for bucket, count in sorted(by_bucket.items()):
            page.text(58, cursor, clip(bucket, 25), 8.5, False, INK)
            page.text(300, cursor, int(count), 8.5, True, ORANGE)
            cursor -= 19
    else:
        page.text(58, cursor, "Nenhuma chamada externa nesta execução.", 8.5, False, GREEN)
    page.text(46, 535, "Resultados observados", 10, True, ORANGE)
    outcome_summary = outcomes.get("summary", {}) if isinstance(outcomes.get("summary", {}), dict) else {}
    page.wrapped(46, 512, outcome_summary.get("note", "Leitura descritiva do histórico fechado; não é uma previsão."), PAGE_WIDTH - 92, 8.5, 12, MUTED)
    cursor = 474
    for horizon, item in (outcome_summary.get("by_horizon", {}) if isinstance(outcome_summary.get("by_horizon", {}), dict) else {}).items():
        if not isinstance(item, dict) or not item.get("records"):
            continue
        positive = "-" if item.get("positive_rate") is None else f"{float(item.get('positive_rate')):.1%}"
        average = "-" if item.get("average_return") is None else f"{float(item.get('average_return')):.2%}"
        page.text(46, cursor, f"{horizon} observacoes", 8.5, False, INK)
        page.text(220, cursor, int(item.get("records", 0) or 0), 8.5, False, INK)
        page.text(300, cursor, positive, 8.5, False, INK)
        page.text(390, cursor, average, 8.5, False, INK)
        cursor -= 22
    page.text(46, 333, "Proveniência", 10, True, ORANGE)
    cache_namespaces = cache_stats.get("namespaces", {}) if isinstance(cache_stats.get("namespaces", {}), dict) else {}
    cursor = 310
    for namespace, item in sorted(cache_namespaces.items()):
        if not isinstance(item, dict):
            continue
        page.text(46, cursor, clip(namespace, 20), 8, False, INK)
        page.text(178, cursor, f"hits {int(item.get('hits', 0) or 0)}", 8, False, GREEN)
        page.text(264, cursor, f"misses {int(item.get('misses', 0) or 0)}", 8, False, INK)
        page.text(356, cursor, f"erros {int(item.get('errors', 0) or 0)}", 8, False, ORANGE)
        cursor -= 18
    page.wrapped(46, 108, "O report usa apenas ficheiros locais. API keys, URLs e parâmetros de pedido não são incluídos.", PAGE_WIDTH - 92, 8.5, 12, MUTED)
    try:
        from src.action_commentary import commentary_entries
    except ModuleNotFoundError:
        from action_commentary import commentary_entries
    append_commentary_pages(pages, commentary_entries(payload), meta)
    return write_pdf(pages, output_path)


def build_portfolio_pdf(state: dict[str, Any], output_path: Path | None = None) -> bytes:
    """Build a focused portfolio report with only score-threshold highlights."""
    meta = state.get("meta", {}) if isinstance(state.get("meta", {}), dict) else {}
    portfolio = state.get("portfolio", {}) if isinstance(state.get("portfolio", {}), dict) else {}
    positions = [item for item in portfolio.get("positions", []) if isinstance(item, dict)]
    threshold = float((state.get("thresholds", {}) or {}).get("buy_score", 80) or 80)
    standout_positions = sorted(
        [item for item in positions if item.get("score") is not None and float(item.get("score", 0) or 0) >= threshold],
        key=lambda item: float(item.get("score", 0) or 0),
        reverse=True,
    )
    standout_sectors = sorted(
        [item for item in state.get("sector_summary", []) if isinstance(item, dict) and item.get("average_score") is not None and float(item.get("average_score", 0) or 0) >= threshold],
        key=lambda item: float(item.get("average_score", 0) or 0),
        reverse=True,
    )
    monitor = state.get("portfolio_monitor", {}) if isinstance(state.get("portfolio_monitor", {}), dict) else {}

    def background(page: Page, page_number: int, title: str, subtitle: str) -> None:
        page.box(0, 0, PAGE_WIDTH, PAGE_HEIGHT, (0.98, 0.99, 0.98))
        page.box(0, PAGE_HEIGHT - 126, PAGE_WIDTH, 126, INK)
        page.text(46, PAGE_HEIGHT - 45, "RADAR / CARTEIRA", 8, False, (0.55, 0.66, 0.65))
        page.text(46, PAGE_HEIGHT - 82, title, 23, True, (0.96, 0.98, 0.96))
        page.text(46, PAGE_HEIGHT - 104, subtitle, 8.5, False, (0.70, 0.78, 0.77))
        page.rule(46, 47, PAGE_WIDTH - 92)
        page.text(46, 28, f"radar / snapshot {meta.get('as_of', '-')} / pagina {page_number}", 7, False, MUTED)
        page.text(PAGE_WIDTH - 188, 28, "sem ordens / leitura descritiva", 7, False, MUTED)

    pages = [Page(1), Page(2)]
    page = pages[0]
    background(page, 1, "Carteira e destaques", f"posicoes e setores com score >= {threshold:.0f}")
    metric_width = (PAGE_WIDTH - 92 - 27) / 4
    metrics = [
        ("Valor EUR", f"{float(portfolio.get('market_value', 0) or 0):,.0f}", "normalizado" if portfolio.get("valuation_approximate") else "comparavel"),
        ("Posicoes", len(positions), "na carteira local"),
        ("Acima do limiar", len(standout_positions), f"score >= {threshold:.0f}"),
        ("Monitorizadas", len(monitor.get("selected_symbols", []) or []), "nesta ronda"),
    ]
    for index, (label, value, detail) in enumerate(metrics):
        x = 46 + index * (metric_width + 9)
        page.box(x, 656 - 76, metric_width, 76, PALE)
        page.text(x + 11, 637, label.upper(), 7.2, False, MUTED)
        page.text(x + 11, 613, value, 17, True, INK)
        page.text(x + 11, 594, detail, 7.5, False, MUTED)
    page.text(46, 545, "Setores em destaque", 10, True, ORANGE)
    cursor = 520
    if standout_sectors:
        for item in standout_sectors[:8]:
            page.rule(46, cursor + 7, PAGE_WIDTH - 92, LINE)
            page.text(46, cursor - 4, clip(item.get("sector", "Sem setor"), 42), 8.5, True, INK)
            page.text(360, cursor - 4, f"score {float(item.get('average_score', 0) or 0):.1f}", 8.5, True, GREEN)
            page.text(470, cursor - 4, f"{int(item.get('signals', 0) or 0)} ativos", 8, False, MUTED)
            cursor -= 28
    else:
        page.box(46, cursor - 54, PAGE_WIDTH - 92, 54, PALE)
        page.text(60, cursor - 22, f"Nenhum setor atingiu {threshold:.0f}/100 neste snapshot.", 10, True, INK)
        page.text(60, cursor - 40, "Nao existe uma entrada confirmada; o radar deve continuar a observar.", 8, False, MUTED)
        cursor -= 75
    page.text(46, cursor - 6, "Posicoes da carteira acima do limiar", 10, True, ORANGE)
    cursor -= 32
    if standout_positions:
        for item in standout_positions[:10]:
            page.rule(46, cursor + 7, PAGE_WIDTH - 92, LINE)
            page.text(46, cursor - 4, clip(item.get("symbol", "-"), 12), 8.5, True, INK)
            page.text(120, cursor - 4, clip(item.get("sector", "Fora do radar"), 34), 8, False, INK)
            page.text(330, cursor - 4, f"score {float(item.get('score', 0) or 0):.1f}", 8.5, True, GREEN)
            page.text(430, cursor - 4, f"peso {float(item.get('weight', 0) or 0):.1%}", 8, False, MUTED)
            cursor -= 27
    else:
        page.text(46, cursor, f"Nenhuma posicao atingiu {threshold:.0f}/100.", 9, False, MUTED)

    page = pages[1]
    background(page, 2, "Exposicao e supervisao", "pesos normalizados em EUR e prioridades locais")
    page.text(46, 680, "Maiores exposicoes por setor", 10, True, ORANGE)
    cursor = 654
    for item in (portfolio.get("sector_exposure", []) or [])[:10]:
        page.rule(46, cursor + 7, PAGE_WIDTH - 92, LINE)
        page.text(46, cursor - 4, clip(item.get("sector", "Sem setor"), 40), 8.5, False, INK)
        page.text(330, cursor - 4, f"{float(item.get('weight', 0) or 0):.1%}", 8.5, True, INK)
        page.text(420, cursor - 4, f"{float(item.get('market_value', 0) or 0):,.0f} EUR", 8, False, MUTED)
        cursor -= 27
    page.text(46, 365, "Prioridade de dados", 10, True, ORANGE)
    selected = [str(value) for value in monitor.get("selected_symbols", []) if str(value)]
    next_symbols = [str(value) for value in monitor.get("next_symbols", []) if str(value)]
    page.wrapped(46, 340, f"Monitorizados nesta ronda: {', '.join(selected) if selected else 'nenhum'}.", PAGE_WIDTH - 92, 8.5, 12, INK)
    page.wrapped(46, 305, f"Proximos na fila: {', '.join(next_symbols[:10]) if next_symbols else 'sem fila local'}.", PAGE_WIDTH - 92, 8.5, 12, MUTED)
    page.text(46, 255, "Alertas que merecem confirmacao", 10, True, ORANGE)
    cursor = 230
    for item in (state.get("supervision", []) or [])[:4]:
        page.text(46, cursor, clip(item.get("title", "Aviso"), 38), 8.5, True, INK)
        page.wrapped(235, cursor, clip(item.get("detail", ""), 88), PAGE_WIDTH - 281, 7.7, 9, MUTED)
        cursor -= 28
    page.wrapped(46, 76, "Uso responsavel: valores noutras moedas usam o cambio implicito no extrato. Confirma preco, cambio, custos e qualidade antes de qualquer decisao. Este PDF nao envia ordens.", PAGE_WIDTH - 92, 7.5, 9, MUTED)
    try:
        from src.action_commentary import commentary_entries
    except ModuleNotFoundError:
        from action_commentary import commentary_entries
    append_commentary_pages(pages, commentary_entries(state, portfolio_only=True), meta)
    return write_pdf(pages, output_path)


def write_pdf(pages: list[Page], output_path: Path | None = None) -> bytes:
    objects: list[bytes] = []
    objects.append(b"<< /Type /Catalog /Pages 2 0 R >>")
    kids = " ".join(f"{5 + i * 2} 0 R" for i in range(len(pages)))
    objects.append(f"<< /Type /Pages /Kids [{kids}] /Count {len(pages)} >>".encode())
    objects.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>")
    objects.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold /Encoding /WinAnsiEncoding >>")
    page_objects: list[bytes] = []
    for index, page in enumerate(pages):
        content = b"\n".join(page.commands) + b"\n"
        content_object_number = 6 + index * 2
        page_object_number = 5 + index * 2
        page_objects.append(f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {PAGE_WIDTH} {PAGE_HEIGHT}] /Resources << /Font << /F1 3 0 R /F2 4 0 R >> >> /Contents {content_object_number} 0 R >>".encode())
        page_objects.append(f"<< /Length {len(content)} >>\nstream\n".encode() + content + b"endstream")
    objects.extend(page_objects)
    pdf = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = [0]
    for index, obj in enumerate(objects, 1):
        offsets.append(len(pdf))
        pdf.extend(f"{index} 0 obj\n".encode())
        pdf.extend(obj)
        pdf.extend(b"\nendobj\n")
    xref_at = len(pdf)
    pdf.extend(f"xref\n0 {len(objects) + 1}\n".encode())
    pdf.extend(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        pdf.extend(f"{offset:010d} 00000 n \n".encode())
    pdf.extend(f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref_at}\n%%EOF\n".encode())
    data = bytes(pdf)
    if output_path:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(data)
    return data
