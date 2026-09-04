# Feature Scout — Radar diário de momentum setorial — 2026-08-05

## Sumário executivo

O radar já cobre o núcleo que muitas ferramentas deixam escondido: recolha multi-fonte, score explicável, qualidade dos dados, backtest walk-forward, Excel auditável e paper trading. [V] A pesquisa mostra três lacunas práticas: não há alertas quando um ativo entra/sai dos critérios, o backtest ainda não modela custos/slippage e não existe um histórico de alterações do sinal que permita comparar “o que o modelo dizia” com o resultado posterior. [V][?] TradingView e StockCharts destacam screener/watchlists/alertas; Koyfin acrescenta exposições, dashboards e relatórios; Composer e QuantConnect mostram a importância de backtest, alocação histórica, custos e paper trading. [V]

Recomendação principal: transformar cada execução diária num “radar de mudanças”, gerando alertas apenas quando um ativo muda de estado ou atravessa um limiar. Isso é pequeno, local e compatível com o stack atual, e resolve uma queixa recorrente dos utilizadores de screeners: ter de atualizar manualmente a página para descobrir novas entradas. [V][?]

## Inventário do projeto atual

### Funcionalidades existentes

- [V] Modo demo determinístico e modo live com Alpha Vantage, CoinMarketCap e FRED.
- [V] Universo configurável de ETFs/setores e criptomoedas.
- [V] Score composto por momentum, força relativa, tendência, amplitude, volume, notícias, macro e penalização de risco.
- [V] Bloqueio de ações quando benchmark, notícias ou macro estão indisponíveis.
- [V] Excel com Resumo, Sinais, Histórico, Backtest, Qualidade, Paper, Config, Fontes e Guia.
- [V] Relatório Markdown com glossário, fontes, ações e métricas de backtest.
- [V] Backtest walk-forward simples e comparação contra benchmark equiponderado.
- [V] Paper trading local, idempotente e sem corretora.
- [V] Validação live por fonte e mensagens de erro sem expor chaves.

### Restrições do stack

- Python local, JSON/CSV/Markdown e Excel gerado com `@oai/artifact-tool`; não existe aplicação web nem base de dados.
- APIs gratuitas têm limites, cobertura variável e atrasos; Alpha Vantage é usado para ETFs/notícias e CoinMarketCap para cripto.
- O plano Basic da CoinMarketCap limita o histórico cripto configurado a cerca de 365 dias. [V]
- Não há integração com corretora, execução automática, dados intraday ou feed de ordens.
- O projeto deve continuar seguro por defeito: sinais são investigação, paper trading vem antes de dinheiro real.

## Concorrentes analisados

| Nome | Link | Popularidade/preço | Licença |
|---|---|---|---|
| TradingView Screener/Alerts | [docs oficiais](https://www.tradingview.com/support/solutions/43000718866-tradingview-stock-screener-trade-smarter-not-harder/) | Produto comercial; preço varia por plano [V] | Proprietário |
| Koyfin | [features oficiais](https://www.koyfin.com/features/) | Freemium/comercial [V] | Proprietário |
| StockCharts | [features oficiais](https://stockcharts.com/features/) | Subscrição comercial [V] | Proprietário |
| Composer | [produto oficial](https://www.composer.trade/) | Subscrição + corretora; execução automática [V] | Proprietário |
| QuantConnect | [paper trading oficial](https://www.quantconnect.com/docs/v2/cloud-platform/live-trading/brokerages/quantconnect-paper-trading) | Freemium/comercial; infraestrutura cloud [V] | Plataforma proprietária; LEAN tem licença própria |
| Portfolio Visualizer | [referência pública](https://portfolio-visualiser.dhansaarthi.com/) | Ferramenta web freemium/comercial [?] | Proprietário |

## Matriz de features

| Feature | Nós | TradingView | Koyfin | StockCharts | Composer/QuantConnect |
|---|---:|---:|---:|---:|---:|
| Score explicável com pesos visíveis | ✅ | parcial | parcial | parcial | parcial |
| Screener multi-filtro guardado | ❌ | ✅ [V] | ✅ [V] | ✅ [V] | ✅ [V] |
| Watchlist com alerta de entrada/saída | ❌ | parcial: watchlist alerts [V] | ✅ alertas customizados [V] | ✅ alertas técnicos [V] | ✅ regras condicionais [V] |
| Heatmap/rotação setorial | parcial: tabela Excel | ✅ chart/market views [V] | ✅ dashboards [V] | ✅ MarketCarpets/RRG/Sector Summary [V] | parcial |
| Exposições por setor/ativo/região | ❌ | parcial | ✅ [V] | parcial | ✅ alocação histórica [V] |
| Backtest com benchmark | ✅ | ✅ | ✅ | parcial | ✅ [V] |
| Custos, comissão, slippage | ❌ | parcial | parcial | parcial | ✅ explicita custos/slippage [V] |
| Paper trading separado do live | ✅ local | ✅ | parcial | parcial | ✅ [V] |
| Qualidade/frescura por fornecedor | ✅ | escondida | escondida | escondida | parcial |
| Relatório diário portátil/offline | ✅ | ❌ | ❌ | ❌ | ❌ |

## Gaps — o que nos falta

### P0 — Alertas de transição do screener (S, viabilidade alta)

TradingView oferece alertas por watchlist e StockCharts executa scans técnicos repetidamente. [V] O radar calcula o estado apenas no momento da execução e não diz “entrou hoje”, “saiu hoje” ou “subiu de manter para compra”. Deve ser implementado comparando o snapshot atual com o anterior, sem enviar ordens.

### P0 — Custos/slippage e execução no próximo preço (M, viabilidade alta)

Composer mostra custos e slippage no valor da estratégia. [V] Relatos de utilizadores de algo trading apontam slippage, comissões, look-ahead e overfitting como causas frequentes de divergência entre backtest e live. [V][?] O nosso backtest usa retorno entre o fecho do sinal e o fecho futuro, sem custos configuráveis.

### P1 — Histórico de sinal e auditoria “previsão vs resultado” (M, viabilidade alta)

Koyfin/Composer permitem acompanhar evolução de portfólios e alocações; o nosso relatório só conserva o snapshot atual. [V] Guardar cada score/ação e medir o retorno posterior de 5/20 dias permite saber se um sinal foi útil, em vez de avaliar apenas a curva do backtest.

### P1 — Exposição e concentração da carteira (M, viabilidade alta)

Koyfin mostra exposições por classes/setores e Composer mostra alterações de holdings. [V] O Paper já limita posição/setor, mas o Excel não mostra concentração atual, overlap de setores ou contribuição de risco.

### P2 — Screener guardado sem editar JSON (M, viabilidade média)

TradingView/Koyfin permitem guardar filtros e watchlists. [V] Hoje o utilizador precisa editar `config.json`; uma folha `Watchlist` ou ficheiro `watchlist.json` tornaria a extensão a novos ETFs/criptos menos frágil.

## Queixas dos utilizadores da concorrência

- [V][?] Há pedidos recorrentes para alertar diretamente quando um ativo entra num screener; utilizadores descrevem a ausência como razão para abandonar o screener e pagar ferramentas alternativas. [Discussão Reddit](https://www.reddit.com/r/TradingView/comments/1rxxr7t/alerts_on_screener/)
- [V][?] Utilizadores relatam que backtests podem parecer bons e falhar live por slippage, taxas, look-ahead, dados contaminados ou mudança de regime. [Discussão Reddit](https://www.reddit.com/r/algotrading/comments/1rkghne/backtests_lie_live_trading_doesnt/)
- [V] O próprio TradingView documenta que filtros demasiado restritivos, watchlists incompatíveis e sessões pré/pós-mercado podem deixar o screener vazio. [Guia oficial](https://www.tradingview.com/support/solutions/43000635878-why-is-my-screener-empty-why-are-there-no-matches-in-the-screener/)

## Features inovadoras — o que ninguem tem neste formato

### 1. Radar de transições com “motivo da mudança” (S, stack compatível)

Comparar dois snapshots e explicar que componente mudou: “AI passou de 54 para 72 porque momentum + volume confirmaram”. Nasce da lacuna dos alertas de screener. Definition of Done: `alerts.json` e secção no Markdown/Excel com entradas, saídas, upgrades/downgrades e componente dominante.

### 2. Diário de confiança do sinal (M, stack compatível)

Registar score, confiança, qualidade e retorno posterior por sinal. Definition of Done: cada execução acrescenta uma linha a `signal-history.jsonl` e o relatório mostra precisão descritiva por faixa de confiança sem chamar isso “probabilidade de lucro”.

### 3. Backtest “honesto” com custos e cenários (M, stack compatível)

Configurar comissão, slippage, atraso de execução e cenário stress. Definition of Done: métricas bruta/líquida e tabela de sensibilidade; nenhuma ação real é criada.

### 4. Mapa de concentração do paper portfolio (S/M, stack compatível)

Mostrar peso por setor, ativo, fonte e risco. Definition of Done: folha `Exposição` com pesos, limites e alertas de concentração, derivada apenas do ledger local.

### 5. Watchlist editável com validação de fornecedor (S/M, stack compatível)

Um ficheiro simples para adicionar ETFs/criptos, com verificação de provider/source_id antes do live. Definition of Done: comando de validação que aponta símbolo desconhecido sem gastar chamadas de notícias.

## Top 5 recomendações

1. **Implementar alertas de transição** — maior valor imediato, pequeno esforço, elimina a necessidade de comparar Excel manualmente.
2. **Adicionar custos/slippage ao backtest** — reduz o risco de resultados demasiado otimistas.
3. **Guardar histórico de sinais e retornos posteriores** — transforma o radar num sistema mensurável.
4. **Adicionar exposição/concentração ao Excel** — liga o score à carteira real de paper trading.
5. **Criar watchlist editável/validador** — facilita acrescentar ETFs e criptos sem quebrar o JSON.

## Estado após esta pesquisa

- ✅ Alertas de transição e folha `Alertas` implementados.
- ✅ Histórico de sinais, auditoria de retornos posteriores e folha `Exposição` implementados.
- ✅ Atraso de execução, comissão e slippage configuráveis no backtest.
- ✅ `validate-config.ps1` implementado para validar novos ETFs/criptos sem rede.
- ⏳ Continua pendente a criação de um screener visual com filtros guardados; o stack atual continua a ser local e orientado a Excel/Markdown.

### Fontes principais

- [TradingView Screener](https://www.tradingview.com/support/solutions/43000718866-tradingview-stock-screener-trade-smarter-not-harder/) [V]
- [TradingView Watchlist Alerts](https://www.tradingview.com/support/solutions/43000739708-watchlist-alerts-your-trading-edge/) [V]
- [Koyfin Features](https://www.koyfin.com/features/) [V]
- [StockCharts Features](https://stockcharts.com/features/) [V]
- [Composer](https://www.composer.trade/) [V]
- [QuantConnect Paper Trading](https://www.quantconnect.com/docs/v2/cloud-platform/live-trading/brokerages/quantconnect-paper-trading) [V]
