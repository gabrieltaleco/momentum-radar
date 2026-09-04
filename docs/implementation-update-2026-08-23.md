# Atualização de implementação — 2026-08-23

## Resultado

- Pipeline principal tolera falhas no relatório: JSON, CSV e alertas ficam utilizáveis e `artifact_status` identifica o erro.
- Escritas críticas de JSON, CSV, Markdown e PDF são atómicas.
- Execuções live completas são bloqueadas ao fim de semana antes da rede; análises explícitas continuam permitidas.
- Paper trading rejeita snapshots repetidos ou fora de ordem e exige 60 snapshots únicos **e** 50 decisões para revisão.
- Carteira é normalizada em EUR com câmbio implícito do extrato e marca avaliações aproximadas.
- IUIT usa o ticker Xetra correto `QDVE.DE`.
- Novo PDF da carteira mostra valor, exposição, prioridades e apenas destaques com score >= 80.
- PDF diário reduz erros brutos de providers, corrige texto legado e evita conteúdo junto ao rodapé.
- Sensibilidade cobre 108 cenários e declara o resultado não interpretável se faltar o benchmark `GLOBAL`.
- O histórico futuro passa a conservar a janela necessária e a série `GLOBAL`.

## Estado do teste imaginário

- Capital: 100.000.
- Posições e operações: 0.
- Snapshots únicos: 5/60.
- Decisões: 50/50.
- Melhor candidato do snapshot 2026-08-22: CLOUD, score 57,42; faltam 22,58 pontos para o limiar 80.
- Conclusão: não houve entrada válida. A amostra ainda não permite avaliar a estratégia.

## Limitações honestas

- O histórico já guardado não contém `GLOBAL`; a sensibilidade atual não deve justificar mudanças de threshold. As próximas execuções passam a guardá-lo.
- A estabilidade da automação durante cinco sessões de mercado só pode ser confirmada após cinco dias úteis futuros.
- Tiingo está suportado, mas não existe uma `TIINGO_API_KEY` configurada nesta máquina; o fallback atual continua Yahoo Finance com orçamento local conservador.
- O projeto não está num repositório Git, por isso não existe histórico de commits. Foi criado um backup dos ficheiros do paper antes da recuperação em `outputs/backups/2026-08-23-before-paper-recovery/`.
