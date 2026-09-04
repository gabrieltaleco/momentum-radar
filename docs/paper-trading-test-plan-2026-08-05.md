# Plano de testes e estratégias — paper trading — 2026-08-05

## Objetivo

Executar uma carteira virtual de 100.000 USD durante sete dias com os sinais live, sem corretora, e separar claramente três coisas: a qualidade dos dados, o sinal produzido e o resultado da execução simulada.

## O que a pesquisa externa confirma

- **Forward testing antes de dinheiro real.** O TradingView distingue backtesting histórico de forward testing em tempo real e atualiza o relatório à medida que chegam novos dados: <https://www.tradingview.com/support/solutions/43000562362-what-are-strategies-backtesting-and-forward-testing/>
- **Paper trading deve modelar a execução.** O QuantConnect descreve paper trading como dados live com capital fictício e alerta que custos, fills e slippage dependem do modelo escolhido: <https://www.quantconnect.com/docs/v2/cloud-platform/live-trading/brokerages/quantconnect-paper-trading>
- **Slippage não é um número cosmético.** O modelo deve refletir atraso, ligação à corretora e dinâmica do mercado: <https://www.quantconnect.com/docs/v2/writing-algorithms/reality-modeling/slippage/key-concepts>
- **Custos e slippage realistas são uma regra de publicação.** A própria documentação do TradingView recomenda que resultados históricos não usem comissão zero sem justificação: <https://www.tradingview.com/support/solutions/43000590599-script-publishing-rules/>

## Inventário atual do projeto

Já existe recolha multi-fonte (Alpha Vantage, FRED e CoinMarketCap), score com componentes explicáveis, bloqueio live sem benchmark/contexto, backtest com atraso/comissão/slippage, limites de posição/setor, Excel auditável, alertas, outcomes de 5/20 observações e paper ledger idempotente.

## Gaps prioritários encontrados

| Prioridade | Gap/teste | Risco mitigado | Estado |
|---|---|---|---|
| P0 | Confirmar que a tarefa agendada correu mesmo quando não há novo candle | Confundir ausência de novo preço com ausência de execução | **Implementado:** ledger `runs` separado de `snapshots` |
| P0 | Bloquear paper trading live com ativo crítico, benchmark ou contexto em erro | Comprar/vender com dados incompletos | **Implementado:** `--strict-live-quality` no modo live |
| P0 | Aplicar as mesmas comissões/slippage no paper ledger e no backtest | Equity artificialmente otimista | **Implementado:** preço de execução, preço de referência, fees e total_fees |
| P1 | Teste de sensibilidade a atraso, custos e thresholds | Estratégia dependente de um parâmetro arbitrário | **Implementado:** 81 cenários demo, com custos totais de 0/6/12 bps; nenhum cenário é escolhido automaticamente |
| P1 | Walk-forward com janela de treino/teste e parâmetros congelados | Overfitting e leakage temporal | **Implementado:** janelas fora da amostra aparecem no payload e no relatório |
| P1 | Stress de dados: série vazia, stale, duplicada, gaps e preço zero | Falhas silenciosas dos fornecedores | **Implementado:** série vazia/atrasada e erros de fornecedor bloqueiam; duplicados, lacunas >7 dias e preços inválidos ficam contados e em `ERRO` |
| P1 | Rate limit devolvido como resposta JSON HTTP 200 | Marcar um ativo como falha transitória sem o guardar em cache | **Implementado:** retry com backoff e envelopes de quota excluídos do cache |
| P2 | Limite de drawdown e pausa automática | Perdas acumuladas em regime adverso | **Implementado:** `paper_drawdown_brake_pct` bloqueia novas compras e mantém vendas permitidas |

## Estratégias a comparar no paper test

1. **Baseline atual:** compra apenas quando score e confiança superam os thresholds; caps de 10% por posição e 20% por setor.
2. **Trend + relative strength:** manter a regra atual, mas comparar a contribuição de momentum/tendência/força relativa em cada sinal.
3. **Volatility-aware sizing:** reduzir o tamanho de posições com volatilidade anual elevada, sem aumentar o cap máximo.
4. **Cash fallback:** se nenhum ativo cumprir compra, manter cash; não forçar rotação para “perseguir hype”.
5. **Drawdown brake:** congelar novas compras depois de um drawdown configurável; permitir apenas manter ou reduzir.

Nenhuma variante deve ser escolhida pelo maior retorno de uma única janela. O critério é estabilidade entre períodos, custos, drawdown, turnover e diferença para o benchmark.

## Definition of Done da semana

- Sete execuções agendadas observáveis no ledger `runs`.
- Cada execução guarda modo, timestamp UTC, data dos dados, número de sinais e se criou snapshot.
- Zero chamadas a corretora e `paper_only: true` em todos os status.
- Nenhuma compra/venda quando o quality gate live falhar.
- Relatório final com equity, cash, posições, operações, drawdown, custos e comparação com benchmark.
- Testes unitários e de integração verdes; nenhuma chave de API aparece em ficheiros gerados.

## Próximo ciclo depois da semana

1. Comparar o turnover do backtest com o turnover observado no ledger de paper trading, sem escolher automaticamente o melhor cenário.
2. Comparar variantes de sizing e drawdown brake em paper, nunca diretamente em dinheiro real.
3. Rever a semana completa com custos, turnover, drawdown e diferença para o benchmark.
