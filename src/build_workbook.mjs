import fs from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { SpreadsheetFile, Workbook } from "@oai/artifact-tool";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const outputDir = path.join(root, "outputs");
const dataPath = path.join(outputDir, "momentum_data.json");
const payload = JSON.parse(await fs.readFile(dataPath, "utf8"));
const paperPath = process.env.RADAR_PAPER_STATE ? path.resolve(root, process.env.RADAR_PAPER_STATE) : path.join(outputDir, "paper_portfolio.json");
let paperPayload = { cash: 0, positions: {}, trades: [], snapshots: [] };
try {
  paperPayload = JSON.parse(await fs.readFile(paperPath, "utf8"));
} catch {
  // Paper sheet remains visible with an empty state until the first simulation.
}
const workbook = Workbook.create();

const colors = {
  navy: "#172B4D",
  blue: "#1D4ED8",
  teal: "#0F766E",
  amber: "#8A5A00",
  red: "#B42318",
  purple: "#6D28D9",
  ink: "#172B4D",
  muted: "#475569",
  pale: "#F6F8FA",
  white: "#FFFFFF",
  line: "#D9E2EC",
};
const scoreWeights = payload.config.weights;
const scoreThresholds = payload.config.thresholds;

const sheet = (name) => workbook.worksheets.add(name);
const summary = sheet("Resumo");
const signals = sheet("Sinais");
const history = sheet("Histórico");
const backtest = sheet("Backtest");
const quality = sheet("Qualidade");
const paper = sheet("Paper");
const config = sheet("Config");
const sources = sheet("Fontes");
const guide = sheet("Guia");
const alerts = sheet("Alertas");
const exposure = sheet("Exposição");
for (const current of [summary, signals, history, backtest, quality, paper, config, sources, guide, alerts, exposure]) {
  current.showGridLines = false;
}

function titleBlock(current, title, subtitle, endColumn = "H") {
  current.mergeCells(`A1:${endColumn}1`);
  current.getRange("A1").values = [[title]];
  current.getRange(`A1:${endColumn}1`).format = { fill: colors.navy, font: { bold: true, color: colors.white }, rowHeight: 30 };
  current.mergeCells(`A2:${endColumn}2`);
  current.getRange("A2").values = [[subtitle]];
  current.getRange(`A2:${endColumn}2`).format = { fill: colors.pale, font: { color: colors.muted, italic: true }, wrapText: true, rowHeight: 28 };
}

function headerFormat(range) {
  range.format = { fill: colors.blue, font: { bold: true, color: colors.white }, wrapText: true, borders: { preset: "outside", style: "thin", color: colors.line } };
}

function bodyFormat(range) {
  range.format = { font: { color: colors.ink }, borders: { insideHorizontal: { style: "thin", color: colors.line } } };
}

function addActionFormatting(range) {
  range.conditionalFormats.add("containsText", { text: "Considerar compra", format: { fill: colors.teal, font: { color: colors.white, bold: true } } });
  range.conditionalFormats.add("containsText", { text: "Manter/observar", format: { fill: "#FEF3C7", font: { color: colors.amber, bold: true } } });
  range.conditionalFormats.add("containsText", { text: "Reduzir/evitar", format: { fill: "#FEE2E2", font: { color: colors.red, bold: true } } });
  range.conditionalFormats.add("containsText", { text: "Não agir", format: { fill: "#EDE9FE", font: { color: colors.purple, bold: true } } });
}

titleBlock(summary, "Radar diário de momentum setorial", `As of ${payload.meta.as_of} · ${payload.meta.mode} · ${payload.meta.source_note}`, "L");
summary.getRange("A4:B10").values = [
  ["Indicador", "Valor"],
  ["Sinais calculados", null],
  ["Considerar compra", null],
  ["Manter/observar", null],
  ["Reduzir/evitar", null],
  ["Pontuação média", null],
  ["Confiança média", null],
];
headerFormat(summary.getRange("A4:B4"));
summary.getRange("B5").formulas = [[`=COUNTA('Sinais'!$B$4:$B$${payload.signals.length + 3})`]];
summary.getRange("B6").formulas = [[`=COUNTIF('Sinais'!$N$4:$N$${payload.signals.length + 3},"Considerar compra")`]];
summary.getRange("B7").formulas = [[`=COUNTIF('Sinais'!$N$4:$N$${payload.signals.length + 3},"Manter/observar")`]];
summary.getRange("B8").formulas = [[`=COUNTIF('Sinais'!$N$4:$N$${payload.signals.length + 3},"Reduzir/evitar")`]];
summary.getRange("B9").formulas = [[`=AVERAGE('Sinais'!$L$4:$L$${payload.signals.length + 3})`]];
summary.getRange("B10").formulas = [[`=AVERAGE('Sinais'!$M$4:$M$${payload.signals.length + 3})`]];
bodyFormat(summary.getRange("A5:B10"));
summary.getRange("B9:B10").format.numberFormat = "0.0";
summary.getRange("A12:D16").values = [
  ["Backtest", "Estratégia", "Benchmark", "Estado"],
  ["Retorno total", payload.backtest.strategy.total_return, payload.backtest.benchmark.total_return, null],
  ["CAGR", payload.backtest.strategy.cagr, payload.backtest.benchmark.cagr, null],
  ["Drawdown máximo", payload.backtest.strategy.max_drawdown, payload.backtest.benchmark.max_drawdown, null],
  ["Sharpe", payload.backtest.strategy.sharpe, payload.backtest.benchmark.sharpe, null],
];
headerFormat(summary.getRange("A12:D12"));
summary.getRange("D13").formulas = [[`=IF(B13>=C13,"supera benchmark","rever")`]];
summary.getRange("D14").formulas = [[`=IF(B14>=C14,"supera benchmark","rever")`]];
summary.getRange("D15").formulas = [[`=IF(B15>=C15,"menor drawdown","rever")`]];
summary.getRange("D16").formulas = [[`=IF(B16>=C16,"melhor Sharpe","rever")`]];
bodyFormat(summary.getRange("A13:D16"));
summary.getRange("B13:C15").format.numberFormat = "0.0%";
summary.getRange("B16:C16").format.numberFormat = "0.00";
summary.getRange("A18:L21").values = [
  ["Uso", "Este ficheiro apresenta sinais de pesquisa; não envia ordens e não garante retorno.", null, null, null, null, null, null, null, null, null, null],
  ["Legenda", "Verde: compra", "Amarelo: manter", "Vermelho: reduzir", "Roxo: sem dados", null, null, null, null, null, null, null],
  ["Próximo passo", "Rever os fatores e confirmar os dados antes de qualquer decisão.", null, null, null, null, null, null, null, null, null, null],
  ["Versão", payload.meta.version, null, null, null, null, null, null, null, null, null, null],
];
summary.mergeCells("B18:L18");
summary.mergeCells("B20:L20");
summary.mergeCells("B21:L21");
summary.getRange("A18:L21").format = { fill: colors.pale, font: { color: colors.muted }, wrapText: true };
summary.getRange("A18:A21").format.font = { bold: true, color: colors.navy };
summary.getRange("A18:L21").format.rowHeight = 24;

summary.getRange("F4:L10").values = [
  ["Estado da execução", "Valor", null, null, null, null, null],
  ["Modo", payload.meta.mode, null, null, null, null, null],
  ["Dados reais", payload.meta.mode === "live" ? "Sim" : "Não — demo", null, null, null, null, null],
  ["Notícias/macro", payload.meta.mode === "live" ? (payload.meta.context_available ? "Disponíveis" : "Em falta") : "Neutros (demo)", null, null, null, null, null],
  ["Fonte dos preços", payload.meta.source_note, null, null, null, null, null],
  ["Última atualização", payload.meta.generated_at, null, null, null, null, null],
  ["Regra", "Sem contexto completo, a ação deve ser apenas observação.", null, null, null, null, null],
];
headerFormat(summary.getRange("F4:G4"));
summary.mergeCells("G7:L7");
summary.mergeCells("G8:L8");
summary.mergeCells("G9:L9");
summary.mergeCells("G10:L10");
bodyFormat(summary.getRange("F5:L10"));
summary.getRange("F5:F10").format.font = { bold: true, color: colors.navy };
summary.getRange("F4:L10").format.wrapText = true;
summary.getRange("F4:L10").format.rowHeight = 24;
summary.getRange("G9").format.numberFormat = "yyyy-mm-dd hh:mm";

titleBlock(signals, "Sinais de hoje", "Os componentes são inputs do motor; Score e Ação foram calculados com os parâmetros desta execução. Para recalcular, edite config.json e execute novamente.", "R");
signals.getRange("A3:R3").values = [["Setor", "Símbolo", "Preço", "Momentum", "Força relativa", "Tendência", "Amplitude", "Volume", "Notícias", "Macro", "Penalização risco", "Score", "Confiança", "Ação", "Data", "Fonte", "Notas", "Score bruto"]];
headerFormat(signals.getRange("A3:R3"));
const signalValues = payload.signals.map((row) => [
  row.sector, row.symbol, row.price, row.momentum, row.relative_strength, row.trend, row.breadth, row.volume,
  row.news, row.macro, row.risk_penalty, null, row.confidence, null, new Date(`${row.date}T00:00:00Z`), row.source, row.notes, null,
]);
if (signalValues.length) signals.getRange(`A4:R${signalValues.length + 3}`).values = signalValues;
for (let row = 4; row <= signalValues.length + 3; row += 1) {
  signals.getRange(`R${row}`).formulas = [[`=D${row}*${scoreWeights.momentum}+E${row}*${scoreWeights.relative_strength}+F${row}*${scoreWeights.trend}+G${row}*${scoreWeights.breadth}+H${row}*${scoreWeights.volume}+I${row}*${scoreWeights.news}+J${row}*${scoreWeights.macro}-K${row}`]];
  signals.getRange(`L${row}`).formulas = [[`=MAX(0,MIN(100,R${row}))`]];
  signals.getRange(`N${row}`).formulas = [[`=IF(M${row}<${scoreThresholds.min_confidence},"Não agir",IF(L${row}>=${scoreThresholds.buy_score},"Considerar compra",IF(L${row}>=${scoreThresholds.hold_score},"Manter/observar","Reduzir/evitar")))`]];
}
bodyFormat(signals.getRange(`A4:R${signalValues.length + 3}`));
signals.getRange(`C4:C${signalValues.length + 3}`).format.numberFormat = "0.00";
signals.getRange(`D4:M${signalValues.length + 3}`).format.numberFormat = "0.0";
signals.getRange(`R4:R${signalValues.length + 3}`).format.numberFormat = "0.0";
signals.getRange(`O4:O${signalValues.length + 3}`).format.numberFormat = "yyyy-mm-dd";
addActionFormatting(signals.getRange(`N4:N${signalValues.length + 3}`));
signals.getRange(`L4:L${signalValues.length + 3}`).conditionalFormats.add("dataBar", { color: colors.blue, gradient: true });
signals.freezePanes.freezeRows(3);

titleBlock(history, "Histórico recente", "Últimos 180 dias disponíveis por instrumento. Dados brutos usados como evidência, não como recomendação.", "H");
history.getRange("A3:H3").values = [["Data", "Setor", "Símbolo", "Fecho", "Volume", "Moeda", "Fonte", "Source ID"]];
headerFormat(history.getRange("A3:H3"));
const historyValues = payload.history.map((row) => [new Date(`${row.date}T00:00:00Z`), row.sector, row.symbol, row.close, row.volume, row.currency, row.source, row.source_id]);
if (historyValues.length) history.getRange(`A4:H${historyValues.length + 3}`).values = historyValues;
bodyFormat(history.getRange(`A4:H${historyValues.length + 3}`));
history.getRange(`A4:A${historyValues.length + 3}`).format.numberFormat = "yyyy-mm-dd";
history.getRange(`D4:E${historyValues.length + 3}`).format.numberFormat = "#,##0.00";
history.freezePanes.freezeRows(3);

titleBlock(backtest, "Backtest walk-forward", "Rebalanceamento periódico, sinais calculados apenas com dados anteriores e sem promessa de retorno futuro.", "I");
backtest.getRange("A3:H3").values = [["Data", "Selecionados", "Turnover", "Retorno estratégia", "Retorno benchmark", "Equity estratégia", "Equity benchmark", "Observação"]];
headerFormat(backtest.getRange("A3:H3"));
const btValues = payload.backtest.rows.map((row) => [new Date(`${row.date}T00:00:00Z`), row.selected, row.turnover ?? 0, row.strategy_return, row.benchmark_return, row.strategy_equity, row.benchmark_equity, row.selected ? "posição nos sinais acima do limite" : "sem posição"]);
if (btValues.length) backtest.getRange(`A4:H${btValues.length + 3}`).values = btValues;
bodyFormat(backtest.getRange(`A4:H${btValues.length + 3}`));
backtest.getRange(`A4:A${btValues.length + 3}`).format.numberFormat = "yyyy-mm-dd";
backtest.getRange(`C4:E${btValues.length + 3}`).format.numberFormat = "0.0%";
backtest.getRange(`F4:G${btValues.length + 3}`).format.numberFormat = "0.000";
backtest.freezePanes.freezeRows(3);
if (btValues.length > 1) {
  const chartRows = Math.min(btValues.length + 3, 150);
  backtest.getRange(`J3:L${chartRows}`).values = [["Data", "Equity estratégia", "Equity benchmark"], ...btValues.slice(0, chartRows - 3).map((row) => [row[0].toISOString().slice(0, 10), null, null])];
  for (let row = 4; row <= chartRows; row += 1) {
    backtest.getRange(`K${row}`).formulas = [[`=F${row}`]];
    backtest.getRange(`L${row}`).formulas = [[`=G${row}`]];
  }
  headerFormat(backtest.getRange("J3:L3"));
  bodyFormat(backtest.getRange(`J4:L${chartRows}`));
  backtest.getRange(`K4:L${chartRows}`).format.numberFormat = "0.000";
  const chart = backtest.charts.add("line", backtest.getRange(`J3:L${chartRows}`));
  chart.title = "Equity: estratégia vs benchmark";
  chart.hasLegend = true;
  chart.xAxis = { axisType: "textAxis" };
  chart.yAxis = { numberFormatCode: "0.00" };
  chart.setPosition("J3", "R20");
}

titleBlock(quality, "Qualidade dos dados", "Um erro ou atraso deve bloquear a ação e preservar o último relatório válido.", "J");
quality.getRange("A3:J3").values = [["Símbolo", "Fonte", "Linhas", "Estado", "Idade (dias)", "Duplicadas", "Lacunas >7d", "Preços inválidos", "Mensagem", "Data do radar"]];
headerFormat(quality.getRange("A3:J3"));
const qualityValues = payload.quality.map((row) => [row.symbol, row.source, row.rows, row.status, row.age_days ?? null, row.duplicate_dates ?? 0, row.gap_count ?? 0, row.invalid_prices ?? 0, row.message, payload.meta.as_of]);
if (qualityValues.length) quality.getRange(`A4:J${qualityValues.length + 3}`).values = qualityValues;
bodyFormat(quality.getRange(`A4:J${qualityValues.length + 3}`));
quality.getRange(`E4:E${qualityValues.length + 3}`).format.numberFormat = "0";
quality.getRange(`J4:J${qualityValues.length + 3}`).format.numberFormat = "yyyy-mm-dd";
quality.getRange(`D4:D${qualityValues.length + 3}`).conditionalFormats.add("containsText", { text: "OK", format: { fill: "#DCFCE7", font: { color: colors.teal, bold: true } } });
quality.getRange(`D4:D${qualityValues.length + 3}`).conditionalFormats.add("containsText", { text: "ATRASADO", format: { fill: "#FEF3C7", font: { color: colors.amber, bold: true } } });
quality.getRange(`D4:D${qualityValues.length + 3}`).conditionalFormats.add("containsText", { text: "ERRO", format: { fill: "#FEE2E2", font: { color: colors.red, bold: true } } });
quality.freezePanes.freezeRows(3);

titleBlock(paper, "Paper trading", "Simulação sem corretora; a mesma data não é processada duas vezes.", "N");
const latestPaper = paperPayload.snapshots?.at(-1) || { date: "", equity: paperPayload.initial_cash || 0, cash: paperPayload.cash || 0, positions: 0, signals: 0 };
const latestPaperRun = paperPayload.runs?.at(-1) || { run_at: "", processed: false };
paper.getRange("A3:B10").values = [
  ["Indicador", "Valor"],
  ["Data", latestPaper.date],
  ["Equity simulada", latestPaper.equity],
  ["Cash", latestPaper.cash],
  ["Posições", latestPaper.positions],
  ["Sinais processados", latestPaper.signals],
  ["Execucoes registadas", paperPayload.runs?.length || 0],
  ["Ultima execucao", latestPaperRun.run_at],
];
headerFormat(paper.getRange("A3:B3"));
bodyFormat(paper.getRange("A4:B10"));
paper.getRange("B5:B6").format.numberFormat = "#,##0.00";
paper.getRange("A11:F11").values = [["Símbolo", "Setor", "Quantidade", "Entrada", "Último preço", "Data entrada"]];
headerFormat(paper.getRange("A11:F11"));
const paperPositions = Object.entries(paperPayload.positions || {}).map(([symbol, position]) => [symbol, position.sector || "", position.shares, position.entry_price, position.last_price, position.entry_date]);
if (paperPositions.length) paper.getRange(`A12:F${paperPositions.length + 11}`).values = paperPositions;
bodyFormat(paper.getRange(`A12:F${Math.max(12, paperPositions.length + 11)}`));
paper.getRange("H11:O11").values = [["Data", "Ação", "Símbolo", "Quantidade", "Preço", "Valor", "Custos", "Motivo"]];
headerFormat(paper.getRange("H11:O11"));
paper.getRange("A11:N11").format.rowHeight = 32;
const paperTrades = (paperPayload.trades || []).slice(-30).map((trade) => [trade.date, trade.action, trade.symbol, trade.shares, trade.price, trade.notional, trade.fees || 0, trade.reason]);
if (paperTrades.length) paper.getRange(`H12:O${paperTrades.length + 11}`).values = paperTrades;
bodyFormat(paper.getRange(`H12:O${Math.max(12, paperTrades.length + 11)}`));
paper.getRange("A:F").format.columnWidth = 18;
paper.getRange("H:O").format.columnWidth = 18;
paper.getRange("O:O").format.columnWidth = 34;
paper.freezePanes.freezeRows(3);

titleBlock(config, "Configuração e regras", "Células azuis documentam os parâmetros usados nesta execução; para recalcular, edite config.json e execute novamente.", "D");
config.getRange("A4:B18").values = [
  ["Parâmetro", "Valor"],
  ["Peso momentum", payload.config.weights.momentum],
  ["Peso força relativa", payload.config.weights.relative_strength],
  ["Peso tendência", payload.config.weights.trend],
  ["Peso amplitude", payload.config.weights.breadth],
  ["Peso volume", payload.config.weights.volume],
  ["Peso notícias", payload.config.weights.news],
  ["Peso macro", payload.config.weights.macro],
  ["Limite considerar compra", payload.config.thresholds.buy_score],
  ["Limite manter/observar", payload.config.thresholds.hold_score],
  ["Confiança mínima", payload.config.thresholds.min_confidence],
  ["Data mínima do radar", new Date(`${payload.meta.as_of}T00:00:00Z`)],
  ["Atraso do sinal (dias)", payload.config.backtest?.signal_delay_days ?? 0],
  ["Comissão do backtest (bps)", payload.config.backtest?.commission_bps ?? 0],
  ["Slippage do backtest (bps)", payload.config.backtest?.slippage_bps ?? 0],
];
headerFormat(config.getRange("A4:B4"));
bodyFormat(config.getRange("A5:B18"));
config.getRange("B5:B11").format = { font: { color: "#0000FF" }, numberFormat: "0.0%" };
config.getRange("B12:B14").format = { font: { color: "#0000FF" }, numberFormat: "0.0" };
config.getRange("B15").format = { font: { color: "#0000FF" }, numberFormat: "yyyy-mm-dd" };
config.getRange("B16:B18").format = { font: { color: "#0000FF" }, numberFormat: "0.0" };
config.getRange("A20:D23").values = [
  ["Convenção", "Descrição", "Fonte", "Estado"],
  ["Dados", "Preço/volume, notícias Alpha Vantage e macro FRED; demo mantém notícias/macro neutros.", "motor Python + APIs", "Ativo"],
  ["Ação", "Rótulos são hipóteses de pesquisa; confirmar dados e carteira.", "regras do projeto", "Manual"],
  ["Limites", "Sem alavancagem, short ou execução automática.", "regras do projeto", "Manual"],
];
headerFormat(config.getRange("A20:D20"));
bodyFormat(config.getRange("A21:D23"));

titleBlock(sources, "Fontes e auditoria", "URLs e notas para rastrear os fornecedores e o enquadramento do produto.", "D");
sources.getRange("A3:D3").values = [["ID", "Fonte", "URL", "Uso"]];
headerFormat(sources.getRange("A3:D3"));
sources.getRange("A4:D7").values = [
  ["AV", "Alpha Vantage", "https://www.alphavantage.co/documentation/", "OHLCV, commodities e notícias"],
  ["CMC", "CoinMarketCap", "https://coinmarketcap.com/api/documentation/guides/get-historical-price-data", "Preço, histórico e volume cripto"],
  ["FRED", "Federal Reserve Bank of St. Louis", "https://fred.stlouisfed.org/docs/api/fred/series_observations.html", "Séries macroeconómicas"],
  ["PRIIPs", "EUR-Lex", "https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX:32014R1286", "KID e acesso de retalho na UE"],
];
bodyFormat(sources.getRange("A4:D7"));

titleBlock(guide, "Guia de leitura", "Explicação simples dos indicadores usados pelo radar. O resultado é apoio à pesquisa, não uma ordem de compra ou venda.", "C");
guide.getRange("A4:C4").values = [["Termo", "O que significa", "Como interpretar"]];
headerFormat(guide.getRange("A4:C4"));
guide.getRange("A5:C18").values = [
  ["Score", "Pontuação combinada de 0 a 100.", "Quanto maior, mais fatores apontam na mesma direção."],
  ["Confiança", "Qualidade/completude dos dados disponíveis.", "Abaixo do limite mínimo, a ação fica 'Não agir'."],
  ["Momentum", "Força da subida ou descida recente.", "Momentum alto mostra aceleração; não garante continuação."],
  ["Força relativa", "Desempenho contra o benchmark.", "Acima de 50 significa que o setor está relativamente forte."],
  ["Tendência", "Persistência do movimento (médias e direção).", "Ajuda a separar impulso de curto prazo de tendência."],
  ["Amplitude", "Percentagem de ativos do grupo a acompanhar o movimento.", "Movimento amplo é geralmente mais robusto que um caso isolado."],
  ["Volume", "Atividade de negociação comparada com o normal.", "Volume elevado confirma interesse; volume fraco pede cautela."],
  ["Notícias", "Sentimento agregado das notícias recentes.", "É apenas contexto; notícias podem mudar rapidamente."],
  ["Macro", "Sinal de ambiente económico (VIX, juros e dólar).", "Ajuda a avaliar se o ambiente favorece ou penaliza risco."],
  ["Risco", "Penalização por volatilidade e drawdown.", "Risco alto reduz o Score mesmo com momentum positivo."],
  ["Benchmark", "Referência usada para comparação.", "Serve para saber se o setor bate o mercado, não para prever preço."],
  ["CAGR", "Retorno anualizado no backtest.", "Resume crescimento médio anual; é histórico e hipotético."],
  ["Drawdown", "Maior queda desde um pico no backtest.", "Quanto mais negativo, maior a perda potencial observada."],
  ["Sharpe", "Retorno ajustado ao risco.", "Maior é melhor no histórico, mas não elimina risco futuro."],
];
bodyFormat(guide.getRange("A5:C18"));
guide.getRange("A5:A18").format.font = { bold: true, color: colors.navy };
guide.getRange("A:C").format.columnWidth = 30;
guide.getRange("B:B").format.columnWidth = 54;
guide.getRange("C:C").format.columnWidth = 58;
guide.getRange("A4:C18").format.wrapText = true;
guide.getRange("A4:C18").format.rowHeight = 34;
guide.freezePanes.freezeRows(4);

titleBlock(alerts, "Alertas de transição", "Mudanças desde a última execução no mesmo modo. São avisos informativos; não são ordens.", "F");
alerts.getRange("A3:F3").values = [["Tipo", "Símbolo", "Estado anterior", "Estado atual", "Variação do Score", "Motivo"]];
headerFormat(alerts.getRange("A3:F3"));
const alertRows = (payload.alerts?.events || []).map((event) => [event.type, event.symbol, event.from_action || "", event.to_action || "", event.score_delta ?? null, event.reason || ""]);
if (alertRows.length) alerts.getRange(`A4:F${alertRows.length + 3}`).values = alertRows;
else alerts.getRange("A4:F4").values = [["INFO", "—", "", "", null, payload.alerts?.comparable ? "Nenhuma transição relevante." : "Sem snapshot anterior comparável; linha de base criada."]];
bodyFormat(alerts.getRange(`A4:F${Math.max(4, alertRows.length + 3)}`));
alerts.getRange(`E4:E${Math.max(4, alertRows.length + 3)}`).format.numberFormat = "+0.0;-0.0;–";
addActionFormatting(alerts.getRange(`D4:D${Math.max(4, alertRows.length + 3)}`));
alerts.getRange("A:F").format.columnWidth = 22;
alerts.getRange("F:F").format.columnWidth = 46;
alerts.freezePanes.freezeRows(3);

titleBlock(exposure, "Exposição do paper portfolio", "Distribuição atual por setor, calculada a partir do ledger local. Cash fica separado e os pesos não são recomendações.", "F");
const exposurePositions = Object.entries(paperPayload.positions || {}).map(([symbol, position]) => ({
  symbol,
  sector: position.sector || "Sem setor",
  value: Number(position.shares || 0) * Number(position.last_price || position.entry_price || 0),
}));
const exposureValue = exposurePositions.reduce((sum, position) => sum + position.value, 0);
const cashValue = Number(paperPayload.cash || 0);
const equityValue = exposureValue + cashValue;
const sectorMap = new Map();
for (const position of exposurePositions) sectorMap.set(position.sector, (sectorMap.get(position.sector) || 0) + position.value);
exposure.getRange("A3:C3").values = [["Setor", "Valor", "Peso da equity"]];
headerFormat(exposure.getRange("A3:C3"));
const exposureRows = [...sectorMap.entries()].sort((a, b) => b[1] - a[1]).map(([sector, value]) => [sector, value, equityValue ? value / equityValue : 0]);
if (exposureRows.length) exposure.getRange(`A4:C${exposureRows.length + 3}`).values = exposureRows;
else exposure.getRange("A4:C4").values = [["Sem posições", 0, 0]];
bodyFormat(exposure.getRange(`A4:C${Math.max(4, exposureRows.length + 3)}`));
exposure.getRange(`B4:B${Math.max(4, exposureRows.length + 3)}`).format.numberFormat = "#,##0.00";
exposure.getRange(`C4:C${Math.max(4, exposureRows.length + 3)}`).format.numberFormat = "0.0%";
exposure.getRange(`C4:C${Math.max(4, exposureRows.length + 3)}`).conditionalFormats.add("dataBar", { color: colors.blue, gradient: true });
exposure.getRange("E3:F6").values = [
  ["Resumo", "Valor"],
  ["Equity simulada", equityValue],
  ["Cash", cashValue],
  ["Investido", exposureValue],
];
headerFormat(exposure.getRange("E3:F3"));
bodyFormat(exposure.getRange("E4:F6"));
exposure.getRange("F4:F6").format.numberFormat = "#,##0.00";
exposure.getRange("A:F").format.columnWidth = 22;
exposure.freezePanes.freezeRows(3);

for (const current of [summary, signals, history, backtest, quality, paper, config, sources, guide, alerts, exposure]) {
  current.getUsedRange()?.format.autofitColumns();
  current.getUsedRange()?.format.autofitRows();
}
summary.getRange("A1:L21").format.columnWidth = 18;
signals.getRange("A:R").format.columnWidth = 16;
signals.getRange("A:A").format.columnWidth = 24;
signals.getRange("Q:Q").format.columnWidth = 52;
history.getRange("A:H").format.columnWidth = 16;
backtest.getRange("A:G").format.columnWidth = 19;
quality.getRange("A:G").format.columnWidth = 20;
quality.getRange("F:F").format.columnWidth = 38;
config.getRange("A:D").format.columnWidth = 28;
sources.getRange("A:D").format.columnWidth = 30;
guide.getRange("A:A").format.columnWidth = 22;
guide.getRange("B:B").format.columnWidth = 54;
guide.getRange("C:C").format.columnWidth = 58;
alerts.getRange("A:F").format.columnWidth = 22;
alerts.getRange("F:F").format.columnWidth = 46;
exposure.getRange("A:F").format.columnWidth = 22;

await fs.mkdir(outputDir, { recursive: true });
const previewTargets = [
  ["Resumo", "resumo-preview.png"],
  ["Sinais", "sinais-preview.png"],
  ["Backtest", "backtest-preview.png"],
  ["Guia", "guia-preview.png"],
  ["Alertas", "alertas-preview.png"],
  ["Exposição", "exposicao-preview.png"],
];
for (const [sheetName, filename] of previewTargets) {
  const preview = await workbook.render({ sheetName, autoCrop: "all", scale: 1, format: "png" });
  await fs.writeFile(path.join(outputDir, filename), new Uint8Array(await preview.arrayBuffer()));
}
const output = await SpreadsheetFile.exportXlsx(workbook);
await output.save(path.join(outputDir, "radar-momentum.xlsx"));

const inspect = await workbook.inspect({ kind: "table", range: "Sinais!A1:R20", include: "values,formulas", tableMaxRows: 20, tableMaxCols: 18 });
const errors = await workbook.inspect({ kind: "match", searchTerm: "#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A", options: { useRegex: true, maxResults: 100 }, summary: "formula error scan" });
console.log(JSON.stringify({ inspect: inspect.ndjson, errors: errors.ndjson, output: path.join(outputDir, "radar-momentum.xlsx") }));
