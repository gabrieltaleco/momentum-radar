# Feature Scout — Radar diário de momentum setorial — 2026-08-13

## Sumário executivo

O Radar já tem uma base diferenciadora: combina momentum, força relativa, tendência, volume, notícias, macro, risco, carteira, alertas, paper trading e relatórios locais. A comparação mostra que a maior distância não está no cálculo, mas na descoberta e acompanhamento diário. TradingView, Koyfin e StockCharts tornam muito visível o ranking, a watchlist, os filtros guardados, a distribuição por setor e as mudanças que merecem atenção. Seeking Alpha acrescenta uma leitura de fatores e alertas de upgrades/downgrades ligados à carteira. A prioridade recomendada é transformar o snapshot num cockpit de decisão: ranking inicial, favoritos, filtros rápidos, explicação da mudança e exportação Markdown/PDF consistente. A eficiência de API deve seguir a mesma lógica: dados lentos em cache mais longo, pedidos do mesmo recurso deduplicados e providers usados em lote quando o endpoint o permite.

## Concorrentes analisados

| Nome | Link | Funcionalidades verificadas | Preço/licença |
|---|---|---|---|
| TradingView | https://www.tradingview.com/support/solutions/43000718866-tradingview-stock-screener-trade-smarter-not-harder/ | [V] screener com múltiplos filtros, ecrãs guardados, exportação CSV, presets, colunas e vista de tabela/gráficos | Comercial |
| Koyfin | https://www.koyfin.com/features/ | [V] watchlists com vistas personalizadas, dashboards guardados, alertas de preço/técnicos/valuation, notas e partilha | Freemium/comercial |
| StockCharts | https://stockcharts.com/features/ | [V] scans, alertas, sector summary, relative rotation graphs, market carpets, predefined scans e chartlists | Comercial |
| Seeking Alpha | https://about.seekingalpha.com/ | [V] Quant Ratings, fatores de momentum/valuation/growth/profitability/EPS revisions, screener, portfolio warnings e alerts | Freemium/comercial |

## Matriz de features

| Feature | Radar | TradingView | Koyfin | StockCharts | Seeking Alpha |
|---|:---:|:---:|:---:|:---:|:---:|
| Ranking/screener visível por defeito | parcial | ✅ | ✅ | ✅ | ✅ |
| Filtros por score/fatores | parcial | ✅ | ✅ | ✅ | ✅ |
| Presets e filtros guardados | ❌ | ✅ | ✅ | ✅ | ✅ |
| Watchlist/favoritos | parcial | ✅ | ✅ | ✅ | ✅ |
| Alertas de mudança | parcial | ✅ | ✅ | ✅ | ✅ |
| Explicação de fatores | ✅ | parcial | parcial | parcial | ✅ |
| Contexto macro/notícias | ✅ | parcial | ✅ | parcial | ✅ |
| Carteira e exposição | ✅ | parcial | ✅ | parcial | ✅ |
| Relatório local auditável | ✅ | parcial | parcial | parcial | parcial |
| Cache local sem chamadas no browsing | ✅ | desconhecido | desconhecido | desconhecido | desconhecido |

## Gaps — o que nos falta

1. **Ranking inicial e filtros rápidos** — [V] concorrentes mostram listas filtráveis e ordenáveis; o Radar começa vazio até o utilizador pesquisar. Esforço S; totalmente viável em HTML/JS local.
2. **Watchlist/favoritos persistentes** — [V] TradingView e Koyfin permitem organizar listas; o Radar tem inventário mas não uma lista de observação leve. Esforço S; localStorage evita API e autenticação.
3. **Relatório acionável de mudança** — [V] Seeking Alpha alerta para upgrades/downgrades e o Radar já calcula transições; falta uma apresentação consolidada com score anterior, fator dominante, qualidade da fonte e próximos passos. Esforço M; viável reutilizando `alerts.json` e o snapshot.
4. **Presets de leitura** — [V] TradingView oferece popular screens; falta ao Radar presets como “mais fortes”, “a perder força”, “na minha carteira” e “sem contexto”. Esforço S.
5. **Alertas configuráveis** — [V] Koyfin permite condições customizadas e gestão central; o Radar só mostra supervisão automática. Esforço M; viável localmente, com notificações do browser numa fase seguinte.
6. **Gráficos de rotação/heatmap** — [V] StockCharts oferece RRG e MarketCarpets. Esforço M/L; útil, mas posterior ao ranking textual porque o projeto ainda é pequeno e local.

## Queixas dos utilizadores da concorrência

- [?] Discussões públicas no Reddit referem a ausência ou limitação de alertas quando um novo ativo entra num screener TradingView: https://www.reddit.com/r/TradingView/comments/1r100q0/screener_alerts_we_were_told_they_would_be_coming/
- [?] Outras discussões referem resultados inesperadamente omitidos por screeners e dificuldade em confiar apenas no filtro: https://www.reddit.com/r/TradingView/comments/v9kclk/tradingview_screener_omits_stocks_all_the_time/
- Implicação para o Radar: cada alerta deve dizer o que mudou, qual a fonte e se o contexto está completo; não basta mostrar um ticker.

## Features inovadoras — o que ninguém tem neste conjunto

1. **Reason ledger** — guardar, por transição, os fatores que subiram/desceram e explicar “o score mudou porque…”. Nasce da força existente do Radar em explicações personalizadas. Esforço M; viável com `signal-history.jsonl` e `alerts.json`. Definition of Done: cada alerta tem score anterior/novo, diferença, fator dominante e link para o ativo.
2. **Quota-aware research mode** — mostrar antes de cada chamada quais dados estão em cache, que provider será usado e que quota pode ser consumida; reutilizar contexto macro/notícias por frescura própria. Esforço M; viável no backend atual. Definition of Done: nenhum browsing chama API e o relatório regista cache hit/miss.
3. **Decision journal local** — permitir adicionar uma nota à leitura, sem enviar dados para fora, e incluí-la no relatório seguinte. Esforço M; viável com ficheiro JSON local. Definition of Done: nota por símbolo/data aparece no painel e no Markdown/PDF.

## Top 5 recomendações

1. Ranking por defeito + filtros rápidos: maior impacto imediato na descoberta.
2. Favoritos/watchlist local: reduz fricção sem criar backend.
3. Relatório Markdown/PDF com comparação e fontes: transforma o snapshot em artefacto reutilizável.
4. Cache TTL por provider + deduplicação: reduz quota, latência e falhas repetidas.
5. Alertas com razão explicável: aumenta confiança antes de investir em notificações externas.

## Fontes primárias adicionais

## Estado da implementação nesta sessão

- Ranking inicial, filtros rápidos e favoritos locais: implementado na interface.
- Alertas com fator dominante e diferença de score: implementado no motor.
- Relatório diário e exportação Markdown/PDF por ativo: implementado no servidor.
- TTL por provider, cache sem identidade de API key e deduplicação concorrente: implementado no motor.
- Diário de decisão local por símbolo/data, visível no painel e nos dois formatos de relatório: implementado.
- Auditoria descritiva de outcomes por horizonte, exposta no relatório diário e na supervisão da interface: implementado.
- Pré-verificação local de quota antes do live, com cache/contexto/chaves e chamadas estimadas: implementado.
- Evidência histórica por símbolo nos exports e no detalhe do website: implementado.
- Ledger agregado de eficiência do cache por namespace, sem URLs, parâmetros ou API keys: implementado no motor, painel e relatório.
- Cooldown local após rate limit por provider, com bloqueio antes da rede e aviso no pré-flight live: implementado; evita retries repetidos e consumo desnecessário de quota.
- Pulso por setor com média de score, cobertura de dados e filtro clicável: implementado na interface para aproximar a leitura de sector summary/market carpet.
- Centro de supervisão com filtros locais de qualidade, mudanças, carteira e evidência: implementado sem novas chamadas de API.
- Pulso por setor também incluído no relatório Markdown diário, com score médio, cobertura de sinais e contagem de compras.
- Comparação local até três ativos, com score, confiança e fatores lado a lado, inspirada no Compare tool de TradingView e sem novas chamadas.
- Pré-flight de quota corrigido para contar cada série macro FRED individualmente, evitando subestimar o custo live.
- Cooldown de Alpha Vantage e notícias unificado no mesmo bucket de quota, evitando que endpoints relacionados contornem a proteção.
- Mudanças recentes agora aparecem diretamente no detalhe do ativo, além do centro de supervisão e do relatório Markdown.
- Catálogo unificado entre configuração, prateleira pública e importações, eliminando sinais produzidos que não eram encontráveis no website.
- Histórico recente de transições acrescentado ao PDF de ativo quando existe alerta, mantendo a explicação consistente entre website, Markdown e PDF.
- Telemetria on-demand segura persistida no estado após refresh, mantendo provider/TTL/contexto sem URLs ou API keys.
- Ordenação local da watchlist por score, símbolo, setor, ação ou favoritos, persistida nas vistas guardadas.
- Reason ledger estruturado nos alertas, com fator dominante, delta e direção além da explicação textual.
- Badges de qualidade nos cartões e filtro local **Dados a rever**, separando ausência de sinal de uma leitura validada sem chamadas adicionais.
- Orçamento diário local por bucket de provider, com contagem UTC, cálculo de shortfall no pré-flight e bloqueio antes da rede quando o custo estimado excede o limite configurado.
- Estado de quota exposto no resumo da homepage, supervisão e report diário, para tornar o custo live observável sem abrir cada ativo.
- Fallback de cache antigo após falha de provider, com marcação `ATRASADO` na qualidade, contexto bloqueado para ação e contador próprio no report.
- Triagem local de supervisão com estado revisto/por rever, inspirado em centros de alertas de watchlists, sem backend ou custo de API.
- Exportação CSV do recorte filtrado da watchlist, aproximando a exportação de screener do TradingView sem enviar dados para fora.
- Mapa de calor local por setor/ativo, com cor por score, tiles clicáveis e cobertura de dados explícita; inspirado no MarketCarpet/Heatmap de StockCharts e TradingView sem recolha adicional.
- Matriz de rotação relativa local por setor, com força relativa no eixo X, impulso no eixo Y e quatro quadrantes clicáveis.

## Atualização de pesquisa — mapa de calor

- [V] StockCharts descreve o MarketCarpet como uma leitura de relance com quadrados coloridos para encontrar forças e fraquezas e explorar rotação setorial: https://help.stockcharts.com/charts-and-tools/other-charting-tools/marketcarpets
- [V] TradingView documenta heatmaps agrupados por setor, com tiles que abrem o detalhe do grupo: https://www.tradingview.com/support/solutions/43000766446-tradingview-heatmaps-from-global-trends-to-details/
- [V] StockCharts documenta RRGs como pontos em quadrantes de força relativa e momentum para distinguir líderes e atrasados: https://chartschool.stockcharts.com/table-of-contents/chart-analysis/chart-types/relative-rotation-graphs-rrg-charts

## Atualização de pesquisa — orçamento de API

- [V] Alpha Vantage documenta até 25 pedidos por dia no serviço gratuito e recomenda o plano premium para volumes superiores: https://www.alphavantage.co/support/ e https://www.alphavantage.co/premium/
- [V] CoinMarketCap distingue limite por minuto de limite diário/mensal e expõe estatísticas de uso da chave; por isso o Radar usa buckets configuráveis em vez de assumir um limite universal: https://coinmarketcap.com/api/documentation/guides/errors-and-rate-limits e https://coinmarketcap.com/api/documentation/pro-api-reference/tools
- [V] FRED exige uma chave por aplicação e pode impor limites de banda/transações; o orçamento fica opcional por provider para não inventar um limite que a documentação não fixa: https://fred.stlouisfed.org/docs/api/api_key.html e https://fred.stlouisfed.org/docs/api/terms_of_use.html

## Atualização de pesquisa — vistas guardadas

- [V] Koyfin centraliza alertas em watchlists e portfólios, permite pesquisar/filtrar/ordenar o centro de alertas e mantém dados históricos em tabelas de watchlist/screener: https://www.koyfin.com/features/alerts/ e https://www.koyfin.com/help/release-notes/
- [V] Finviz Elite permite guardar presets de screener, reutilizá-los e receber alertas quando novos ativos passam os filtros: https://finviz.com/blog/create-stock-screens-then-save-and-trade-them/ e https://elite.finviz.com/help/elite.ashx
- Gap confirmado: o Radar tinha filtros rápidos, mas não guardava o recorte escolhido. Implementado nesta tranche com até 12 vistas locais, sem autenticação, backend ou chamadas de API.

- TradingView alerts e watchlists: https://www.tradingview.com/support/solutions/43000520149-introduction-to-tradingview-alerts/ e https://www.tradingview.com/support/solutions/43000745825-mastering-the-tradingview-watchlists/
- [V] TradingView permite aplicar uma condição a uma watchlist inteira e avaliar cada símbolo individualmente: https://www.tradingview.com/support/solutions/43000739708-watchlist-alerts-your-trading-edge/
- [V] Koyfin posiciona alertas por preço, valuation, técnica e notícias, com gestão centralizada e escopo para watchlists/portfolios: https://www.koyfin.com/features/alerts/
- Gap confirmado: o Radar mostrava mudanças do snapshot, mas não permitia ao utilizador guardar um limiar próprio. Implementado como regras locais de score, confiança, impulso e força relativa; não há notificações externas nem consumo adicional de API.

- [V] Koyfin separa exposição por segurança, tipo, setor e outras dimensões e oferece uma tabela de contribuição das posições para a exposição agregada: https://www.koyfin.com/help/portfolio-exposures/
- Gap confirmado: o Radar mostrava peso por setor e pares correlacionados, mas não mostrava que posições explicam mais da variabilidade conjunta. Implementado com covariância dos retornos locais, observações usadas e volatilidade anualizada aproximada; não há recolha adicional nem look-through inventado.
- Gap adicional fechado: a carteira tinha exposição no painel, mas não tinha um relatório exportável próprio. Implementado `radar-carteira-relatorio.md` com posições, setores, risco aproximado, correlações, quota e qualidade, sem rede.

## Atualização de pesquisa — metas e desvio de alocação

- [V] Koyfin documenta uma Rebalance Table que compara a carteira com uma alocação-alvo/benchmark e identifica excesso, falta e ajustes necessários: https://www.koyfin.com/help/rebalance-drift-table/
- Gap confirmado: o Radar mostrava a exposição atual, mas não permitia guardar metas nem ver o desvio por setor. Implementado com metas locais, validação de soma máxima de 100%, estados acima/abaixo/alinhado, supervisão e inclusão no relatório da carteira.

- Koyfin functionality: https://www.koyfin.com/help/topic/functionality/
- Rebalance drift agora inclui ajuste indicativo em valor (aumentar/reduzir); em carteiras multi-moeda fica marcado como aproximado e nunca cria ordens.
- Gap fechado: o centro de supervisao agora permite pesquisar alertas e ordenar por prioridade, gravidade ou categoria, seguindo a gestao de alertas pesquisavel da Koyfin; tudo fica no browser e nao chama APIs.
- O mesmo recorte pode agora ser exportado para `radar-supervisao-AAAA-MM-DD.md`, preservando filtros, pesquisa, ordenacao, razoes e estado de revisao sem rede.
- Gap fechado: a supervisão acrescentou revisão em lote do recorte visível; filtros e pesquisa podem ser triados de uma vez, com estado local persistente e sem chamadas externas.
- [V] Koyfin documenta alertas para watchlists/portfolios com canais desktop, email e mobile; TradingView documenta alertas aplicados a cada símbolo de uma watchlist: https://www.koyfin.com/features/alerts/ e https://www.tradingview.com/support/solutions/43000739708-watchlist-alerts-your-trading-edge/
- Gap confirmado: as regras locais do Radar apareciam apenas no painel depois do refresh. Implementadas notificações opt-in do browser para mudanças e regras num snapshot novo; sem backend, permissões automáticas ou chamadas de API.
- Gap fechado: `run.ps1 -Mode live -PlanOnly` expõe um pré-flight reutilizável fora do website, com custo estimado por provider/bucket, cache fresco, orçamento, cooldowns e estado configurado das chaves sem revelar segredos; o comando termina antes da rede.
- Eficiência adicional: a janela temporal do fallback Yahoo ficou estável por dia UTC, evitando que `period2` mudasse a cada segundo e criasse entradas de cache diferentes durante o mesmo dia.
- Correção de custo: o pré-flight passou a contar os dois pedidos reais de notícias quando a configuração mistura tickers de mercado e `CRYPTO:*`, mantendo o orçamento Alpha Vantage alinhado com a implementação do provider.
- Gap fechado no report: o ledger passou a contar chamadas externas mesmo sem orçamento local configurado e cada relatório diário mostra o delta efetivamente tentado naquela execução, separado dos hits/misses acumulados do cache.
- O cartão de quota da homepage passou a mostrar esse mesmo delta da última execução, tornando o custo live visível sem abrir o report ou a supervisão.
- Gap fechado: o report diário passou a ter uma versão PDF paginada, com resumo, ranking, qualidade, mudanças, outcomes e auditoria de quota/cache; o website oferece Markdown e PDF sem rede.
- Alpha Vantage compact output: https://www.alphavantage.co/documentation/
- Gap fechado: o ledger de quota/cache passou a usar lock entre processos e temporarios especificos por processo; duas execucoes concorrentes preservam 200 hits e 200 chamadas no teste isolado.
- Gap fechado: ativos ainda nao visitados numa coorte expanded passaram a estado FORA_DA_COORTE, com filtro local e explicacao no report, em vez de serem apresentados como erro do provider.
- Gap fechado: a revisao de entradas passou a guardar a distancia ate ao limiar de compra e os fatores mais fracos de cada candidato proximo; website, paper report e report diario usam a mesma explicacao.

## Atualização de pesquisa — rotação de cobertura

- [V] TradingView permite aplicar uma condição a uma watchlist inteira; StockCharts e TrendSpider documentam scans agendados sobre universos mais amplos: https://www.tradingview.com/support/solutions/43000739708-watchlist-alerts-your-trading-edge/ e https://help.trendspider.com/kb/scanner/market-scanner
- Gap confirmado: o perfil `expanded` completo excedia a margem segura de Yahoo Finance, enquanto o perfil `core` podia deixar oportunidades de fora.
- Implementado: em live, `expanded` mantém todos os ativos `core` e acrescenta uma coorte determinística de 15 ativos, distribuída por setores e rodada automaticamente por data UTC. O plano mostra índice, setores cobertos e símbolos escolhidos; `-CohortIndex` permite reproduzir uma ronda.
- Definition of Done verificada: o pré-flight atual passou a estimar 23 chamadas Yahoo brutas, 14 novas após cache e 31 chamadas totais, com `network_allowed: true` e margem segura de 46 pedidos; a coorte cobre 12 setores.
- Gap fechado: cada execução arquiva Markdown/PDF com data em `outputs/reports/` e a homepage expõe uma biblioteca local de snapshots, aproximando a gestão de reports do Koyfin sem conta, backend ou chamadas externas.
- A comparação entre as duas datas mais recentes aparece no painel com variação de score e mudanças de ação; o mesmo recorte pode ser descarregado em Markdown sem nova recolha.
- [V] A documentação oficial da CoinMarketCap aceita vários IDs separados por vírgulas no histórico: https://coinmarketcap.com/api/documentation/pro-api-reference/cryptocurrency
- Gap de eficiência fechado: o motor agrupa agora BTC/ETH numa única chamada histórica CMC quando existem vários ativos cripto; o pré-flight passou de 17 para 16 chamadas no perfil atual e o cache continua a identificar o lote sem guardar a API key.
- O pré-flight global passou a reconstruir as identidades reais de cache por recurso, distinguindo chamadas brutas de chamadas novas; o report e o estado local mostram chamadas evitadas por cache fresco antes da execução.
- CoinMarketCap keyless/public API e limites: https://coinmarketcap.com/api/documentation/pro-api-reference/keyless-public-api
- FRED observações e API key: https://fred.stlouisfed.org/docs/api/fred/series_observations.html e https://fred.stlouisfed.org/docs/api/api_key.html

## Atualização de pesquisa — cobertura por tema

- [V] Screeners como TradingView e TrendSpider trabalham sobre listas/scan universes e permitem separar descoberta ampla da análise detalhada: https://www.tradingview.com/support/solutions/43000718866-tradingview-stock-screener-trade-smarter-not-harder/ e https://help.trendspider.com/kb/scanner/market-scanner
- Gap confirmado: o Radar mostrava um catálogo amplo, mas o live analisava apenas 10 representantes; isso podia explicar a ausência de entradas sem provar que não existiam oportunidades no setor.
- Implementado: perfil `expanded` opcional com aproximadamente cinco ETFs/ativos por tema, mantendo o perfil `core` no agendamento diário até o custo ser aprovado pelo pré-flight.
- Proteção: Yahoo Finance recebe um orçamento local de 60 pedidos/dia e reserva de 5; estes números são guardas operacionais do Radar, não limites oficiais do provider. Uma ronda ampliada bloqueia antes da rede se não houver margem segura.
- Definition of Done verificada: `--universe-profile expanded` produziu 65 sinais em demo; o pré-flight live estimou 59 preços/67 pedidos brutos e bloqueou corretamente quando a reserva diária não podia ser preservada.

## Atualização de pesquisa — decisão da ronda

- [V] O Stock Screener da TradingView foi desenhado para ordenar universos por filtros e indicadores e transformar o resultado numa lista de acompanhamento: https://www.tradingview.com/support/solutions/43000718866-tradingview-stock-screener-trade-smarter-not-harder/
- [V] As watchlists da Koyfin suportam alertas por preço, sinais técnicos, valuation e notícias, além de vistas personalizadas: https://www.koyfin.com/features/watchlists/
- [V] O scanner da TrendSpider distingue símbolos novos, persistentes e removidos entre scans, e permite agendar scans: https://help.trendspider.com/kb/scanner/market-scanner
- Gap confirmado: o Radar tinha a informação de entrada no report, mas a homepage não respondia explicitamente “há entrada? porquê?”.
- Implementado: bloco **Decisão desta ronda** no topo do website, ligado ao ledger paper, com estado (sem entrada/bloqueado/para investigar), limiar, score máximo e ativos próximos clicáveis. Não faz chamadas adicionais.
- Definition of Done verificada: o snapshot atual mostra “Não há entrada confirmada nesta ronda”, CLOUD 60.0 e BANKS 55.5 como watchlist; clicar num ativo abre o detalhe correspondente.

## Atualização de pesquisa — automação observável

- [V] TradingView separa condição, frequência, expiração e estado do alerta no Alerts Manager: https://www.tradingview.com/support/solutions/43000763312-learn-how-to-configure-alerts/ e https://www.tradingview.com/support/solutions/43000595311-manage-alerts/
- [V] StockCharts mostra o resultado da última execução, o horário e se um scan agendado foi bem-sucedido: https://help.stockcharts.com/scanning-and-alerts/technical-scans/advanced-scan-workbench
- [V] Koyfin centraliza alertas e canais de notificação num Alerts Center: https://www.koyfin.com/help/release-notes/v3-66-desktop-alerts/
- Gap confirmado: a tarefa do Windows estava registada, mas o Radar não guardava um estado próprio de execução; era possível confundir “agendado” com “concluído”.
- Implementado: `outputs/automation-status.json` com heartbeat atómico (`running`, `completed`, `failed`), timestamps, modo, provider, perfil e código de saída. O endpoint local e a supervisão do website passam a distinguir estes estados.
- Definition of Done verificada: uma execução live+paper terminou com `completed`, `exit_code: 0`, `price_provider: yahoo_finance` e `universe_profile: core`.
- Verificação adicional: a própria tarefa `Radar Paper 100k Daily` foi executada manualmente, terminou com `LastTaskResult: 0`, zero execuções perdidas e a próxima execução ficou marcada para 14/08/2026 às 18:00.

## Atualização de pesquisa — cobertura e estado do paper

- Gap operacional identificado: uma tentativa repetida na mesma data podia parecer uma nova revisão sem entrada, embora o ledger tivesse bloqueado a duplicação corretamente.
- Implementado: o website e a supervisão distinguem `Paper sem nova ronda` de `Paper revisto sem entrada`; o report regista o estado e o motivo da última revisão.
- A rotação de coortes passou a guardar o índice/data da próxima coorte automática. O website e o report mostram essa previsão sem fazer chamadas adicionais.
- O estudo de sensibilidade foi regenerado com 81 cenários, incluindo custos totais em bps. Continua a ser diagnóstico em dados demo e não escolhe limiares automaticamente.

## Atualização de pesquisa — fallback de providers

- Gap confirmado: uma falha ou cooldown do provider principal podia deixar o histórico de preços inteiro em erro, apesar de existir uma fonte alternativa sem chave.
- Implementado: `provider_fallbacks` explícito para preços, com Alpha Vantage a poder usar Yahoo Finance; a proveniência fica em `provider_requested`, `provider_used` e `fallback_used`.
- A interface acrescenta a origem alternativa ao detalhe do ativo. Notícias e macro não são substituídas silenciosamente, porque têm semântica e requisitos de qualidade diferentes.
- Definition of Done verificada: teste sem `ALPHAVANTAGE_API_KEY` produziu AI e GLOBAL via Yahoo Finance e o pre-flight deixou de exigir a chave primária quando existe fallback keyless configurado.

## Atualização de pesquisa — alertas por watchlist e ciclo de vida

- [V] TradingView permite uma condição única para uma watchlist inteira e separa a frequência do alerta, incluindo disparo uma vez ou repetido: https://www.tradingview.com/support/solutions/43000739708-watchlist-alerts-your-trading-edge/ e https://www.tradingview.com/support/solutions/43000763312-learn-how-to-configure-alerts/
- [V] Koyfin documenta alertas aplicáveis a watchlists/portfolios e um centro para pesquisar, filtrar, ordenar e gerir alertas: https://www.koyfin.com/features/alerts/
- Gap confirmado: as regras locais do Radar mostravam todas as correspondências em cada renderização e não distinguiam uma nova entrada na condição de uma condição persistente.
- Implementado: cada regra local tem agora disparo `ao entrar` ou `cada snapshot`; o browser guarda o conjunto anterior de símbolos e cria um alerta específico quando um ativo entra na regra. A preferência e o histórico são locais e não alteram o orçamento de APIs.
- Definition of Done: a regra continua visível enquanto a condição permanece, mas as notificações só repetem em `cada snapshot`; uma saída e reentrada do ativo cria uma nova ocorrência; o report de supervisão exportado inclui o estado e a razão sem chamadas externas.

## Atualização de pesquisa — validação operacional visível

- [V] As ferramentas analisadas apresentam estado/gestão de alertas e scans num centro próprio; TradingView separa estado, condição, frequência e expiração, enquanto Koyfin centraliza pesquisa e gestão de alertas: https://www.tradingview.com/support/solutions/43000763312-learn-how-to-configure-alerts/ e https://www.koyfin.com/features/alerts/
- Gap confirmado: `validate-live.ps1` já escrevia JSON, mas o utilizador tinha de interpretar o terminal para saber se o último teste de providers tinha passado; o website podia mostrar o snapshot sem a proveniência da validação explícita.
- Implementado: o estado do dashboard inclui `live_validation`, a supervisão avisa quando a última validação falha e a biblioteca expõe um Markdown local, sem segredos, com linhas, timestamp e falhas.
- Definition of Done verificada: validação live executada hoje com 1.630 linhas, 0 falhas críticas e 0 falhas de contexto; o report pode ser aberto sem rede adicional.

## Atualização de pesquisa — cobertura temporal do paper

- [V] O StockCharts documenta scans agendados com execução e alertas associados ao resultado do scan: https://help.stockcharts.com/scanning-and-alerts/overview-of-technical-alerts
- [V] O TradingView documenta configuração de frequência e condição dos alertas, úteis para distinguir uma condição persistente de um novo disparo: https://www.tradingview.com/support/solutions/43000763312-learn-how-to-configure-alerts/
- Gap confirmado: quatro snapshots e vinte execuções repetidas na mesma data podiam ser lidos como vinte revisões de mercado, apesar de só existirem quatro datas observadas.
- Implementado: `review_progress.coverage` calcula dias úteis potenciais entre a primeira e a última data, lista lacunas, mede a percentagem observada e aparece no report, no website e na supervisão.
- Definition of Done verificada: o paper atual mostra 4/8 dias úteis potenciais (50,0%), lista 4 datas sem snapshot e mantém a ressalva de que feriados/fechos podem explicar parte das lacunas.

## Atualização de pesquisa — histórico de execuções

- Gap confirmado: um heartbeat único (`automation-status.json`) descrevia apenas a última execução e apagava a evidência de falhas anteriores.
- Implementado: `run.ps1` mantém `automation-history.jsonl` com as últimas 90 execuções terminadas; o dashboard lê apenas estado sanitizado, conta falhas e cruza esse histórico com dias sem snapshot.
- Definition of Done verificada: o estado local expõe `automation_history` sem chaves/URLs, mantém compatibilidade com instalações que ainda não têm o ficheiro e os testes cobrem sucesso, falha e migração do último heartbeat.
