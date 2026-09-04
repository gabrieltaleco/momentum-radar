# Feature Scout — Radar diário de momentum setorial — 2026-08-06

## Sumário executivo

Sim, já existem ferramentas que fazem partes deste trabalho. TradingView, Koyfin e StockCharts são fortes em pesquisa, filtros, momentum e alertas. Seeking Alpha acrescenta ratings quantitativos e notas por fatores. Composer junta criação de estratégias, backtest e execução automática. QuantConnect é mais técnico e junta backtest com paper trading.

Na pesquisa não encontrei uma solução que reúna exatamente o que estamos a construir: vários tipos de ativos, análise por três horizontes, explicação em português simples, qualidade dos dados visível, consumo de API apenas quando o utilizador escolhe um ativo, PDF diário e paper trading local sem corretora.

A recomendação é não tentar copiar uma plataforma inteira. Devemos copiar três ideias comprovadas: pesquisa multi-ativo com filtros guardados, alertas de transição e exposição/risco da carteira. A nossa diferença deve ser a tradução para o utilizador comum e a separação rigorosa entre sinal, qualidade dos dados e decisão.

## Inventário do projeto atual

### Funcionalidades existentes

- Modo demo e live com Alpha Vantage, CoinMarketCap e FRED.
- Catálogo local pesquisável de ETFs, metais, obrigações, setores, IA e cripto.
- Análise live apenas depois de escolher um ativo, com cache local para poupar quota.
- Score composto por momentum, força relativa, tendência, volume, notícias, macro e penalização de risco.
- Horizontes tático, swing e longo prazo.
- Qualidade/frescura por fornecedor e bloqueio de sinais quando falta contexto essencial.
- Portfolio local, paper trading, backtest walk-forward, alertas e histórico de sinais.
- Exportação Markdown e PDF com glossário para utilizadores não especialistas.
- Excel auditável e scripts PowerShell portáteis.

### Restrições do stack

- Aplicação local em Python/JavaScript sem base de dados nem corretora ligada.
- APIs gratuitas têm limites, atrasos e cobertura diferente por classe de ativo.
- O catálogo atual é uma base inicial de 52 ativos; ainda não é um top 100 curado por setor.
- Não há intraday garantido, execução real, login multiutilizador ou notificações móveis nativas.

## Concorrentes analisados

| Ferramenta | O que faz | Modelo | Fonte primária |
|---|---|---|---|
| TradingView | Screeners para ações, ETFs, obrigações e cripto; filtros técnicos/fundamentais, screens guardados, heatmaps e alertas | Freemium/comercial [V] | [Stock Screener](https://www.tradingview.com/support/solutions/43000718866-tradingview-stock-screener-trade-smarter-not-harder/) |
| Koyfin | Screener global, mais de 5.900 filtros, watchlists, portfolios, dashboards macro, relatórios e alertas | Freemium/comercial [V] | [Features](https://www.koyfin.com/features/) e [Functionality](https://www.koyfin.com/help/topic/functionality/) |
| StockCharts | Scans técnicos, alertas automáticos, RRG, MarketCarpets, Sector Summary e análise multi-timeframe | Comercial [V] | [Features](https://stockcharts.com/features/) |
| Seeking Alpha | Quant Rating de 1 a 5 e fatores de valuation, growth, profitability, momentum e EPS revisions; ratings para ETFs incluem risco e liquidez | Freemium/Premium [V] | [About](https://about.seekingalpha.com/about) |
| Composer | Cria estratégias em linguagem natural, faz backtest e pode rebalancear/executar automaticamente | Comercial [V] | [Produto](https://www.composer.trade/) |
| QuantConnect | Pesquisa e backtest programáveis, dados live e paper trading com capital fictício; exige mais conhecimento técnico | Freemium/comercial [V] | [Paper Trading](https://www.quantconnect.com/docs/v2/cloud-platform/live-trading/brokerages/quantconnect-paper-trading) |
| TrendSpider | Análise técnica automatizada, scanners, reconhecimento de padrões, backtesting, alertas e agentes de IA | Comercial [V] | [Produto](https://trendspider.com/product/analyze-and-chart-any-market-asset/) |
| Morningstar Investor | Acompanha carteira, alocação, risco, custos, overlaps e benchmark; mais orientada a gestão patrimonial do que a momentum | Comercial [V] | [Portfolio tools](https://www.morningstar.com/tools/portfolio/all) |

## Matriz de features

| Feature | Nós | TradingView | Koyfin | StockCharts | Seeking Alpha | Composer/QuantConnect |
|---|---:|---:|---:|---:|---:|---:|
| Pesquisa multi-ativo | parcial | ✅ | ✅ | ✅ | parcial | parcial |
| Filtros guardados | ❌ | ✅ | ✅ | ✅ | ✅ | ✅ |
| Momentum e força relativa | ✅ | ✅ | ✅ | ✅ | ✅ | configurável |
| Notícias e macro no mesmo score | ✅ | parcial | ✅ macro | parcial | notícias + fatores | configurável |
| Decisão por horizonte | ✅ | parcial | parcial | parcial | parcial | configurável |
| Explicação para iniciante | ✅ | parcial | parcial | parcial | parcial | parcial |
| Alertas de mudança de sinal | ✅ local | ✅ | ✅ | ✅ | ✅ | ✅ |
| Exposição e risco da carteira | parcial | parcial | ✅ | parcial | ✅ | ✅ |
| Backtest com paper trading | ✅ local | parcial | parcial | parcial | parcial | ✅ |
| PDF diário portátil/offline | ✅ | ❌ | ❌ | ❌ | parcial | ❌ |
| Sem corretora e sem execução real por defeito | ✅ | parcial | ✅ | ✅ | ✅ | ❌/opcional |

## Gaps — o que nos falta

### P0 — Catálogo realmente grande e filtros guardados (M, viabilidade média)

TradingView, Koyfin e StockCharts permitem filtrar universos grandes e guardar pesquisas. O nosso catálogo ainda é uma base inicial de 52 ativos e a pesquisa é local. Precisamos de uma fonte licenciada/estável para rankings e holdings, mais `watchlist.json` editável e filtros guardados.

### P1 — Alertas fora da aplicação (S/M, viabilidade alta)

Já temos alertas locais, mas falta enviar um resumo por email, Telegram ou notificação do Windows. A regra deve alertar apenas mudanças relevantes: entrar em “entrada faseada”, sair para “não agir”, queda forte de confiança ou quebra de qualidade.

### P1 — Exposição e correlação da carteira (M, viabilidade alta)

Morningstar e Koyfin mostram alocação, risco e sobreposição. O inventário já mostra concentração agregada por setor, alerta para o limite configurado e lista pares com correlação diária elevada; falta acrescentar contribuição para drawdown e exposição comum entre ETFs.

### P1 — Backtest comparável com custos por ativo (M, viabilidade alta)

Composer e QuantConnect tornam custos, fills e execução explícitos. Devemos mostrar resultado bruto, líquido, slippage, turnover e cenários stress no mesmo quadro.

## Queixas e riscos observados na concorrência

- Ratings diferentes podem discordar porque usam pesos, universos e períodos distintos. Um “Strong Buy” não é uma ordem universal.
- Screeners grandes podem ficar vazios ou mudar de resultado quando filtros, mercados e horários são configurados de forma diferente. [Guia TradingView](https://www.tradingview.com/support/solutions/43000635878-why-is-my-screener-empty-why-are-there-no-matches-in-the-screener/)
- Backtests e paper trading podem ser demasiado otimistas quando ignoram slippage, custos, fills, liquidez ou mudança de regime. A documentação do QuantConnect, por exemplo, explica que o modelo por defeito não aplica slippage em backtest/paper trading. [Documentação](https://www.quantconnect.com/docs/v2/cloud-platform/live-trading/brokerages/quantconnect-paper-trading)
- Automação de execução aumenta o risco operacional. Composer oferece execução e rebalanceamento automáticos, mas isso é precisamente uma fronteira que devemos manter desligada nesta fase. [Composer](https://www.composer.trade/)

## Features inovadoras — o que faz sentido neste projeto

### 1. “Porquê agora?” em três frases (S, viabilidade alta)

Para cada horizonte, mostrar o fator que melhorou, o fator que piorou e o risco que invalida a entrada. Definition of Done: o PDF e a UI geram a mesma explicação a partir dos mesmos dados.

### 2. Mapa “hype vs qualidade” (M, viabilidade média)

Separar hype de confirmação: preço/volume/notícias podem estar fortes enquanto qualidade dos dados, benchmark ou macro estão fracos. Definition of Done: quadrante visível e bloqueio automático de “comprar” quando o hype não tem confirmação.

### 3. Semáforo de confiança para o João (S, viabilidade alta)

Converter qualidade, cobertura, frescura e divergência entre fatores em “verde / amarelo / vermelho”, com uma frase sobre o que falta. Definition of Done: o semáforo aparece antes da ação em todos os relatórios.

## Top 5 recomendações

1. **Aumentar o catálogo por setor e adicionar filtros guardados** — maior gap face a TradingView/Koyfin/StockCharts.
2. **Adicionar semáforo de qualidade antes de comprar/manter/vender** — reduz más decisões por dados incompletos.
3. **Mostrar concentração, correlação e overlap da carteira** — transforma sinais isolados em decisão de carteira.
4. **Adicionar custos/slippage e stress ao relatório de backtest** — aproxima o resultado da execução real.
5. **Enviar alertas apenas para mudanças de estado** — evita ruído e não obriga a abrir a aplicação todos os dias.

## Conclusão

Há concorrência forte. O projeto não precisa de vencer TradingView em gráficos, Koyfin em cobertura ou QuantConnect em infraestrutura. Pode ser melhor para o utilizador comum ao responder uma pergunta concreta: “para este ativo, neste prazo, com estes dados e este risco, vale a pena investigar uma entrada agora?”
