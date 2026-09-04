# Radar diário de momentum setorial

MVP local para recolher dados de mercado, calcular sinais de momentum e gerar um Excel auditável e um relatório diário.

## Executar em modo demo

O modo demo não usa rede nem chaves. Serve para validar a pipeline e o formato do workbook:

```powershell
.\run.ps1 -Mode demo
```

Os ficheiros aparecem em `outputs/`:

- `radar-momentum.xlsx`
- `relatorio-momentum.md`
- `momentum_data.json`
- `signals.csv`
- `alerts.json` — mudanças de ação/score desde a execução anterior no mesmo modo
- `signal-history.jsonl` — diário compacto dos sinais para auditoria
- `signal-outcomes.jsonl` — retorno posterior observado após 5/20 observações

## Abrir a interface local

Os relatórios de ativo, diário e carteira incluem **Como agiria nesta situação**: até 150 palavras por ativo, com ação condicional, motivo, fator a vigiar e condição de revisão. O texto usa o snapshot local e o custo normalizado quando disponível; dados em falta ou atrasados bloqueiam sugestões de entrada. PDF e Markdown partilham a mesma lógica, sem chamadas a APIs ou alteração das regras do motor. A secção descreve uma leitura de apoio à decisão, não uma recomendação pessoal. O arquivo histórico mantém os relatórios originais.

A interface transforma o snapshot do radar num painel simples para utilização diária. Abre logo com o ranking dos ativos, filtros rápidos para score alto/mudanças/favoritos, favoritos persistentes no browser, pesquisa local de ETFs, metais, índices, ações e criptos, leitura explicada dos ativos configurados e acompanhamento de uma carteira importada ou introduzida manualmente. O endpoint que alimenta o painel envia um estado compacto, sem séries macro e linhas pesadas de diagnóstico; os detalhes completos continuam locais para os relatórios e análises específicas.

```powershell
.\run-ui.ps1
```

Depois abre `http://127.0.0.1:8765` no browser. O launcher pede uma password local em cada arranque; ela fica apenas na variável de ambiente do processo. Para configurar sem prompt, define as variáveis de `.env.example` no teu terminal antes de iniciar. Nunca comites `.env` nem chaves de providers. O utilizador predefinido é `admin` e pode ser alterado com `RADAR_AUTH_USERNAME`.

Se o PowerShell não arrancar, executa `run-ui-direct.bat` ou usa diretamente `python app_server.py --host 127.0.0.1 --port 8765`; o próprio Python pede a password de forma oculta. O `run-ui.bat` continua disponível para Windows e tenta iniciar o launcher com política temporária de execução.

## Publicar a aplicação online

GitHub Pages não executa este servidor Python. Para colocar o painel online, cria um Web Service num provider que leia este repositório. O ficheiro `render.yaml` deixa o arranque preparado para Render: escolhe **New → Blueprint**, seleciona `gabrieltaleco/momentum-radar` e confirma o serviço. No painel do serviço, define `RADAR_AUTH_PASSWORD` como secret antes do primeiro deploy. O build cria um snapshot demo sem carteira pessoal; as chaves de providers são opcionais e devem ser adicionadas apenas como secrets.

O sistema de ficheiros de serviços gratuitos pode ser efémero. Não uses o deployment demo para guardar carteira ou notas reais sem configurar um volume/database privado, backups e uma política de retenção. Antes de aceitar tráfego público, troca a autenticação local por uma solução de produção com gestão de utilizadores, rate limiting e HTTPS terminado no provider.

O inventário fica em `data/user_portfolio.json`; não contém chaves de API e não envia ordens. Importações pessoais ficam apenas em ficheiros locais ignorados pelo Git. Navegar e pesquisar não chama APIs. A área **Pulso por setor** resume a média do score por setor, mostra quantos ativos têm leitura e permite filtrar com um clique. Nos cartões com dados podes usar **⇄** para comparar até três ativos lado a lado, sempre com o snapshot local e sem gastar quota. Seleciona um ativo e usa **Analisar live** apenas quando quiseres gastar quota nesse ativo; o resultado fica em cache por 6 horas por defeito. A análise usa Alpha Vantage/CoinMarketCap no universo inicial e Yahoo Finance sem chave para os instrumentos globais/europeus importados. Depois podes usar **Exportar PDF** para descarregar um relatório com uma explicação específica para esse ativo, sem nova chamada. O PDF separa entrada tática, swing e longo prazo, sem estimar um preço futuro. Quando existe preço médio de compra, o inventário e o PDF acrescentam uma segunda leitura: ganho/perda face ao custo, distância ao ponto de equilíbrio e como cruzar isso com o sinal de mercado. Se o extrato não permitir confirmar o custo, aparece “sem comparação” em vez de se inventar um valor. Um ativo que ainda não tenha dados aparece como “Sem dados” até ser analisado live. O painel relê os outputs ao carregar, ao clicar em atualizar e a cada 60 segundos.

Para desenvolvimento local sem login, usa explicitamente `$env:RADAR_AUTH_DISABLED = "1"`; não uses essa opção num servidor partilhado ou público. A autenticação é uma barreira para o painel local, não substitui HTTPS, gestão de utilizadores, backups protegidos ou um servidor de produção endurecido. Consulta [SECURITY.md](SECURITY.md), [PRIVACY.md](PRIVACY.md), [TERMS.md](TERMS.md) e [LICENSE](LICENSE) antes de distribuir.
Na secção de supervisão podes filtrar os avisos por **qualidade**, **mudanças**, **carteira** ou **evidência**, mantendo o mesmo snapshot local. O detalhe de cada ativo também mostra as últimas mudanças de ação e score, quando existem.
Os avisos podem ser marcados como **revistos** neste browser e filtrados por “Por rever” ou “Revistos”; este estado é apenas local e não altera o snapshot nem faz chamadas.
O resumo inicial inclui agora **quota live**: mostra as chamadas restantes do provider com orçamento local e leva-te diretamente à supervisão quando o limite está perto ou esgotado.
Mostra também quantas chamadas externas foram efetivamente tentadas na última execução, sem confundir esse valor com respostas reutilizadas do cache.
O pulso inclui também um **mapa de calor por ativo**, agrupado por setor: a cor resume o score, os tiles são clicáveis e os ativos sem leitura aparecem a cinzento com a contagem de cobertura.
Logo abaixo, a **rotação relativa** posiciona cada setor pela média de força relativa e impulso, separando líderes, recuperação, a melhorar e atrasados. É uma leitura exploratória, não uma previsão nem uma chamada live.

O catálogo junta o universo configurado, a prateleira pública e os instrumentos importados, para que qualquer sinal produzido pelo radar também possa ser encontrado no website. A lista pode ser ordenada localmente por score, símbolo, setor, ação ou favoritos; a ordenação também fica guardada nas vistas.
Cada cartão mostra ainda a qualidade da leitura da fonte e o filtro **Dados a rever** concentra ativos sem sinal ou com fonte degradada, para não confundir ausência de evidência com um sinal neutro.

### Diário de decisão local

No detalhe de cada sinal podes guardar uma nota pessoal ligada ao símbolo e à data do snapshot. A nota fica em `data/decision_journal.json`, não é enviada para nenhum provider e é incluída nos relatórios Markdown e PDF desse ativo. Guardar uma nota vazia remove-a. Na pesquisa podes guardar até 12 **vistas** locais — cada uma conserva pesquisa, setor e filtro rápido no browser — para reabrir o mesmo recorte sem repetir a configuração.
O botão **Exportar CSV** exporta o recorte atual da watchlist, já com pesquisa, setor, filtro e ordenação aplicados, incluindo score, ação, confiança e estado da fonte. É uma operação local e não gasta quota.

Na supervisão podes guardar regras locais para score, confiança, impulso ou força relativa, com escopo para todo o catálogo, **minha carteira**, favoritos ou setor atual. Cada regra pode disparar **ao entrar** (recomendado: só avisa quando um ativo passa a cumprir a condição) ou em **cada snapshot**. O histórico de correspondências fica apenas neste browser, para evitar repetir a mesma notificação enquanto a condição se mantém; mudar de provider ou atualizar regras não faz chamadas adicionais.
Podes ativar **notificações locais** na mesma área. O browser pede permissão apenas quando clicas no botão e, quando chega um snapshot novo, avisa sobre mudanças e regras atingidas; não há servidor de notificações, email, push externo ou chamadas adicionais.
O centro de supervisão também permite pesquisar texto nos alertas e ordenar por prioridade, gravidade ou categoria. A pesquisa é local e não altera os dados guardados.
O botão **Relatório** nessa área exporta o recorte atual para Markdown, com snapshot, filtros, razões e estado de revisão. Também é uma operação local e não gasta quota.

Na mesma área, **Marcar visíveis revistos** fecha de uma vez a triagem do recorte atual (incluindo pesquisa, categoria e ordenação). O estado fica apenas neste browser e pode ser reaberto por item.

Na carteira, a secção de contribuição para variabilidade usa apenas os retornos históricos locais para estimar que posições explicam mais da variabilidade conjunta. É uma aproximação, não uma previsão nem uma análise look-through dos componentes de ETFs.
O botão **PDF carteira + destaques** descarrega um relatório local centrado na carteira e apenas nos setores/posições que atingem o limiar de compra (80 por defeito). Quando nada atinge o limiar, o PDF diz isso diretamente. A exportação não chama providers nem inclui chaves.
Os valores da carteira são comparados em EUR. Para posições noutras moedas, o Radar usa o câmbio implícito entre o valor EUR e o preço de referência do extrato e marca a avaliação como aproximada. As **metas de alocação por setor** continuam disponíveis num bloco opcional recolhido; ficam em `data/portfolio_targets.json`, são locais e nunca geram ordens.

## Executar com dados live

1. A configuração já traz um universo inicial com Alpha Vantage (ETFs/setores), CoinMarketCap (cripto) e a prateleira importada com Yahoo Finance; edite `config.json` apenas se quiser mudar símbolos ou setores.
2. Definir as chaves antes de executar:

```powershell
$env:ALPHAVANTAGE_API_KEY = "COLOQUE_A_CHAVE_AQUI"
$env:COINMARKETCAP_API_KEY = "COLOQUE_A_CHAVE_CMC_AQUI"
$env:FRED_API_KEY = "COLOQUE_A_CHAVE_FRED_AQUI"
.\run.ps1 -Mode live
```

Antes de gerar o Excel, validar as fontes e chaves sem enviar ordens:

```powershell
powershell.exe -ExecutionPolicy Bypass -File .\validate-live.ps1
```

Quando a validação termina, o resultado fica em `outputs/live-validation.json` e aparece também na biblioteca de reports do website. O Markdown **Validação live** resume timestamp, linhas verificadas e falhas críticas/contextuais sem mostrar chaves; abrir esse report não faz novas chamadas.

Depois de adicionar ou alterar um ETF/cripto, validar primeiro a configuração sem gastar quota:

```powershell
powershell.exe -ExecutionPolicy Bypass -File .\validate-config.ps1
```

Este passo verifica providers suportados, `source_id` numérico da CoinMarketCap, símbolos duplicados, tickers de notícias, pesos e limites.

O sistema marca cada fonte como `OK`, `ATRASADO` ou `ERRO` na folha `Qualidade`. Alpha Vantage e Yahoo Finance fornecem preços; Alpha Vantage fornece também o clima das notícias; FRED fornece o contexto económico. Se o mercado de comparação não estiver disponível, bloqueia os sinais com `Não agir`. As fontes têm limites e coberturas próprias; confirma sempre a frescura, moeda e custos antes de usar com dinheiro.

Também pode executar `run.bat` com duplo clique no Windows. O pacote do portátil inclui versões locais de Python e Node se a pasta `.runtime/` existir no momento da exportação; sem ela, é necessário ter Python e Node instalados.

Para automatizar uma execução diária no Windows (por exemplo, às 18:00):

```powershell
powershell.exe -ExecutionPolicy Bypass -File .\register-daily-task.ps1 -Mode live -Paper
```

Para o paper de 100.000 USD com preços Yahoo Finance (sem depender da quota de preços da Alpha Vantage):

```powershell
powershell.exe -ExecutionPolicy Bypass -File .\register-daily-task.ps1 -TaskName "Radar Paper 100k Daily" -Mode live -Paper -PaperInitialCash 100000 -PaperState outputs\paper-week-100k.json -PriceProvider yahoo_finance
```

O perfil `core` analisa os ativos essenciais. Para uma ronda de descoberta com cobertura ampliada, usa primeiro o pré-flight e só depois executa:

```powershell
.\run.ps1 -Mode live -PlanOnly -PriceProvider yahoo_finance -UniverseProfile expanded
.\run.ps1 -Mode live -PriceProvider yahoo_finance -UniverseProfile expanded -Paper
```

O perfil ampliado acrescenta cerca de cinco ETFs/ativos por tema e, em live, acompanha sempre o `core` mais uma coorte equilibrada de 15 ativos adicionais por ronda. A coorte roda automaticamente por data UTC; pode ser fixada com `-CohortIndex 0` ou ajustada com `-CohortSize 10`. Os ativos adicionais ficam sem notícias específicas por defeito; isso reduz chamadas, mas torna a leitura de notícias menos rica nesses nomes. O orçamento de 60 pedidos/dia e a reserva de 5 para Yahoo Finance são uma proteção local do Radar, não um limite oficial do provider. O custo live deve ser confirmado no pré-flight e os limites/licenças do Yahoo Finance devem ser verificados antes de depender dele.

Uma execução live completa e automática é ignorada ao sábado e domingo (`network.skip_weekend_full_runs`), evitando gastar quota quando os mercados principais estão fechados. Uma análise explícita de símbolos, incluindo cripto, continua disponível. A tarefa diária pode permanecer registada: o bloqueio acontece antes das chamadas externas.

Em modo `live`, `run.ps1` acompanha automaticamente até 10 posições prioritárias da carteira, escolhidas pelo maior valor declarado. O planeador mostra o custo e preserva 5 chamadas para margem/retries; a monitorização é apenas leitura e não cria ordens. Usa `-PlanOnly` para confirmar o custo sem rede. Para desativar numa execução específica, usa `-NoPortfolioMonitor`.
Os ativos ampliados que ainda não foram visitados aparecem como **Fora da coorte**, não como falha do provider. O website inclui um filtro próprio para os distinguir de erros reais e o centro de supervisão explica quantas coortes faltam.
Na ronda automática, o snapshot guarda também a data e o índice da próxima coorte; o cabeçalho do website e o report mostram essa previsão para tornar a cobertura auditável sem chamadas adicionais.

Para um teste limitado a uma semana com a carteira de 100.000 USD:

```powershell
powershell.exe -ExecutionPolicy Bypass -File .\register-daily-task.ps1 -TaskName "Radar Paper 100k - Semana" -Mode live -Paper -PaperInitialCash 100000 -PaperState outputs\paper-week-100k.json -DurationDays 7 -At (Get-Date).Date.AddHours(23).AddMinutes(30)
```

O script apenas regista a tarefa quando é executado; as credenciais continuam nas variáveis de ambiente do utilizador.

Cada execução escreve `outputs\automation-status.json` com estado `running`, `completed` ou `failed`, provider, perfil, timestamps e código de saída. O website usa esse heartbeat para distinguir uma tarefa agendada concluída de uma tarefa que apenas ficou registada. As execuções terminadas ficam também em `outputs\automation-history.jsonl` (máximo de 90 linhas), para não perder a sequência de falhas/sucessos quando o estado atual é substituído.

Para aplicar os sinais ao diário de paper trading, sem corretora:

```powershell
.\run.ps1 -Mode live -Paper
```

Para iniciar uma carteira virtual separada com 100.000 USD:

```powershell
.\run.ps1 -Mode live -Paper -PaperInitialCash 100000 -PaperState outputs\paper-week-100k.json
```

Para testar a escada experimental sem alterar o ledger anterior:

```powershell
.\run.ps1 -Mode live -Paper -PaperPolicy ladder -PaperInitialCash 100000 -PaperState outputs\paper-ladder-v1.json -PriceProvider yahoo_finance
```

O `paper-ladder-v1` usa entradas exploratórias (score 60–69), confirmadas (70–79) e fortes (80+). Os limites-base são 0,5%, 2% e 4% da equity, respetivamente; o valor final é reduzido por volatilidade, caixa, exposição por setor e drawdown. A política é experimental, mantém o teste estrito separado e não envia ordens.

Para testar a matriz por score e prazo, usa um ledger separado:

```powershell
.\run.ps1 -Mode live -Paper -PaperPolicy matrix -PaperInitialCash 100000 -PaperState outputs\paper-matrix-v2.json -PriceProvider yahoo_finance
```

O `paper-matrix-v2` avalia cada ativo em três slots independentes — curto (5 sessões), médio (20) e longo (60 sessões) — e cada slot tem as bandas 60–69, 70–79 e 80+. Os percentuais são parâmetros experimentais conservadores e configuráveis em `thresholds.paper_entry_matrix`; não são valores validados nem promessa de retorno. Um mesmo ativo pode ocupar mais do que um prazo, mas os limites de ativo, setor, horizonte, exposição total, caixa e entradas por sessão são partilhados. O slot pode sair quando o score fica abaixo de 45 ou quando atinge a maturidade definida. O report fica em `outputs/paper-matrix-v2-report.md` e nunca envia ordens.

O estado fica separado da carteira de demonstração anterior. Cada execução da mesma data é idempotente e não duplica operações.
O ficheiro `paper-week-100k_status.json` resume a última execução, saldo, equity, posições, operações e número de `runs`. `runs` regista a execução da tarefa mesmo quando a data de mercado não mudou (por exemplo, fim de semana).
O mesmo ficheiro inclui `review_progress`: snapshots únicos de mercado, decisões registadas, percentagem de progresso e `ready_for_review`. O sistema só marca a amostra como pronta quando chega simultaneamente a 60 snapshots únicos **e** 50 decisões de sinais. Datas repetidas ou anteriores à última data processada não alteram posições.
`review_progress.coverage` mede quantos dias úteis potenciais tiveram um snapshot entre a primeira e a última data observadas. O report e o website mostram as lacunas para separar “não houve entrada” de “não houve supervisão nova”; feriados e fechos de mercado podem explicar parte dessas datas.

Em modo live, `run.ps1` passa `--strict-live-quality`: se faltar o benchmark ou qualquer ativo crítico, o ledger regista a execução como bloqueada e não altera posições.

Isto atualiza `outputs/paper_portfolio.json`, `paper_trades.csv` e `paper-report.md`, respeitando os limites máximos por posição/setor. A mesma data não é processada duas vezes.

O paper trading tem ainda um travão de segurança configurável em `thresholds.paper_drawdown_brake_pct` (por defeito 15%): se a equity cair esse valor desde o pico, novas compras ficam bloqueadas; as vendas continuam permitidas e o motivo fica registado no snapshot.

O backtest e o paper ledger aplicam por defeito um atraso de entrada de um dia, 1 bp de comissão e 5 bps de slippage quando existe posição. Estes parâmetros ficam em `config.json` na secção `backtest`; o ledger guarda preço de referência, preço de execução, fees e `total_fees` para auditoria.

O Excel inclui as folhas `Alertas` e `Exposição`. `Alertas` mostra transições entre snapshots (por exemplo, `Manter/observar` → `Considerar compra`); `Exposição` resume o peso atual do paper portfolio por setor. Nenhuma destas folhas envia ordens.

O plano de testes e estratégias está em `docs/paper-trading-test-plan-2026-08-05.md`.

Para repetir o estudo de sensibilidade sem rede (108 combinações de threshold, confiança, atraso e custos, incluindo limiares 70/75/80/85):

```powershell
python src\sensitivity.py --input outputs\momentum_data.json --output-dir outputs
```

O resultado fica em `outputs/sensitivity-report.md` e aparece no arquivo de reports do website. A validação só é interpretável quando o histórico local contém a série `GLOBAL` usada como benchmark; se ela faltar, o relatório assinala a limitação e não recomenda baixar o limiar. O estudo é apenas diagnóstico: não escolhe automaticamente novos parâmetros para o paper.

Para consultar o estado da semana sem alterar nada:

```powershell
powershell.exe -ExecutionPolicy Bypass -File .\monitor-paper-week.ps1
```

## Configurar chaves sem as guardar no projeto

Executa `configure-api-keys.ps1` numa PowerShell. O script pede as três chaves com entrada escondida e grava-as apenas nas variáveis de utilizador do Windows. A chave CoinMarketCap Basic pode ser criada em `https://pro.coinmarketcap.com/signup`. Fecha a janela, abre uma nova e executa `validate-live.ps1`. Nunca coloques as chaves no chat, Excel, ZIP ou GitHub.

Antes de gastar quota, podes pedir um plano local da recolha live:

```powershell
.\run.ps1 -Mode live -PlanOnly
```

O comando estima chamadas por provider e bucket, conta ficheiros de cache ainda frescos, mostra apenas se cada chave está configurada e verifica orçamento/cooldown. Não faz chamadas externas, não escreve resultados e nunca imprime os valores das chaves.

## Exportar para outro portátil

Gerar um pacote Windows com o código, configuração e outputs atuais:

```powershell
.\package-portable.ps1
```

Para incluir o runtime Node mínimo usado pelo construtor do Excel, acrescente a origem local:

```powershell
.\package-portable.ps1 -NodeRuntimeSource "C:\caminho\para\node"
```

As chaves ficam fora do pacote e devem ser configuradas no portátil do seu pai. O pacote inclui o Excel/relatório atuais; para gerar novos ficheiros precisa de Python e, se não incluir o runtime acima, Node com `@oai/artifact-tool`.

## Visibilidade da quota live

Depois de uma análise live, o detalhe do ativo mostra o provider, o TTL aplicado e se o contexto de macro/notícias foi reutilizado. Esta telemetria segura também sobrevive a um refresh porque fica guardada no estado on-demand apenas com nomes de provider, TTLs e flags — nunca URLs ou chaves. O resultado on-demand fica guardado em `data/on_demand/`; repetir a mesma leitura dentro do TTL não faz nova chamada. As chaves continuam apenas em variáveis de ambiente e nunca são mostradas na interface ou usadas como identidade do cache.

Ao clicar em **Analisar live**, a interface consulta primeiro `/api/live-plan`, uma pré-verificação local que mostra cache, contexto, chaves em falta, chamadas estimadas e todos os providers em cooldown. A estimativa conta cada série macro como uma chamada separada, para refletir o custo real do FRED. Esta pré-verificação não consulta providers; só depois da confirmação explícita é que a recolha pode gastar quota.

O relatório diário e a supervisão do website também resumem os outcomes já fechados por horizonte: número de registos, percentagem de retornos positivos, média e mediana. É uma auditoria descritiva do histórico observado, não uma taxa de acerto nem uma previsão.
O cabeçalho do website permite agora descarregar o mesmo snapshot diário em Markdown ou num PDF paginado com resumo, pulso setorial, ranking, qualidade, mudanças, outcomes e auditoria de quota/cache. A exportação é local e não faz novas chamadas.

Os relatórios Markdown/PDF de cada ativo acrescentam a mesma evidência filtrada por símbolo quando existe amostra, e o detalhe do website mostra-a junto à leitura do radar. Quando há uma transição recente, o Markdown e o PDF acrescentam o histórico da mudança, o fator dominante e o motivo observado.

O motor mantém ainda um ledger agregado em `data/cache/stats.json`: conta hits, misses, erros e bypass por namespace, sem guardar URLs, parâmetros ou chaves. O painel e o relatório usam estes contadores para mostrar a eficiência real do cache ao longo das execuções. Os alertas guardam também o fator dominante, a variação e a direção em campos estruturados.
O mesmo ledger regista agora todas as tentativas externas por bucket UTC, mesmo quando não existe um limite local configurado. Cada relatório diário mostra quantas chamadas foram efetivamente tentadas naquela execução e separa esse número dos hits locais do cache.
O ledger usa agora um lock entre processos e temporários específicos por processo, para não perder contadores quando uma tarefa agendada e uma análise manual correm ao mesmo tempo.
Se `cache.stale_if_error` estiver ativo, uma falha de provider pode reutilizar a resposta antiga mais recente, mas a leitura fica marcada como **ATRASADO** e o report contabiliza o fallback; isto evita esconder a degradação de dados.
Para proteger chaves com limites pequenos, `network.daily_call_budgets` mantém um orçamento local por bucket UTC; a configuração limita Alpha Vantage a 25 pedidos/dia e Tiingo a 1.000/dia. No plano gratuito, a documentação comercial atual do Tiingo indica também 50 pedidos/hora. CoinMarketCap usa créditos mensais no plano Basic (não um simples limite diário), por isso o Radar agrupa IDs de cripto numa chamada e evita inventar uma quota diária equivalente. A FRED publica erros de rate limit, mas não garante um número diário estável. O pré-flight calcula o custo por provider, mostra chamadas restantes e bloqueia a análise antes da rede quando o orçamento local não chega. Os contadores guardam apenas data, provider e quantidade.

Se um provider responder com rate limit, o motor aplica um cooldown local configurável (`network.provider_cooldown_seconds`, 300 segundos por defeito). Alpha Vantage e notícias usam o mesmo bucket de quota, por isso o bloqueio cobre ambos. Durante esse período, novas tentativas são bloqueadas antes da rede e o pré-flight do website avisa sem gastar quota.
Para preços, `provider_fallbacks` permite uma alternativa explícita: a configuração incluída pode passar de Alpha Vantage ou Tiingo para Yahoo Finance quando falta a chave, há cooldown ou o provider falha. O resultado conserva `provider_requested`, `provider_used` e `fallback_used` na qualidade; isto não se aplica automaticamente a notícias ou macro, e as condições/licença do Yahoo devem ser confirmadas antes de uso real.
O pre-flight aplica a mesma rota quando a chave está ausente ou em cooldown, para que a estimativa de chamadas e o bucket de quota não prometam Alpha Vantage quando a execução irá usar Yahoo Finance.

Cada execução também guarda uma cópia datada em `outputs/reports/`; o bloco **Relatórios anteriores** lista snapshots locais em texto e PDF para comparação histórica, sem repetir recolhas, resume a variação do score entre as duas datas mais recentes e permite descarregar essa comparação.

## Nota sobre quotas live

### Provider alternativo para histórico

O perfil mantém Alpha Vantage como configuração compatível, mas agora aceita Tiingo como provider de preços sem misturar a sua quota com a quota de notícias Alpha. Tiingo usa `TIINGO_API_KEY`, histórico EOD ajustado e orçamento local de 1.000 pedidos/dia; o plano gratuito é para uso interno e deve ser validado quanto à cobertura/licença antes de qualquer publicação pública.

Para testar a mesma configuração com Tiingo sem editar o universo:

```powershell
$env:TIINGO_API_KEY = "COLOQUE_A_CHAVE_TIINGO_AQUI"
powershell.exe -ExecutionPolicy Bypass -File .\run.ps1 -Mode live -PriceProvider tiingo -PlanOnly
powershell.exe -ExecutionPolicy Bypass -File .\run.ps1 -Mode live -PriceProvider tiingo
```

O override troca apenas os ativos e o benchmark que usam Alpha Vantage; CoinMarketCap, FRED e as notícias permanecem separados. O pre-flight tem de mostrar `tiingo` como bucket de preços e bloquear antes da rede se a chave não existir.

O paper report inclui agora uma **Revisão de entradas**: candidatos a compra, entradas executadas, distribuição das ações e bloqueios por histórico curto, qualidade, drawdown ou alocação. Para cada candidato próximo, mostra quantos pontos faltam até ao limiar e quais os fatores mais fracos do modelo. Assim, zero trades deixa de ser um número ambíguo.

O perfil incluído usa `outputsize=compact` no Alpha Vantage, histórico diário do CoinMarketCap e o endpoint de histórico do Yahoo Finance para as posições importadas. Como `compact` pode ficar abaixo das 200 observações mínimas do sinal, esses ativos devem permanecer em `Não agir` até existir histórico suficiente; para um teste operacional com mais amostra, usa o override Tiingo acima (ou `full` apenas se a tua licença Alpha o permitir). A consulta de notícias separa ações/ETFs e cripto em dois pedidos para evitar a rejeição de listas mistas. O cache usa TTL próprio por provider — mais longo para macro e notícias —, remove a API key da identidade do cache e deduplica pedidos concorrentes para o mesmo recurso. A análise live continua a ser feita sob pedido; o catálogo, favoritos e inventário não gastam quota.

O pré-flight conta também os grupos reais de notícias: ações/ETFs e cripto são pedidos separados quando ambos existem, por isso o orçamento não subestima o custo do endpoint `NEWS_SENTIMENT`.
Quando existem vários ativos cripto no universo, o motor usa o suporte oficial de IDs múltiplos da CoinMarketCap para pedir o histórico num único lote; no perfil atual isso reduz uma chamada CMC por execução completa.
O pre-flight global usa agora as mesmas identidades de cache dos providers: mostra o custo bruto, as chamadas novas previstas e quantas podem ser evitadas por cache fresco, sem tocar na rede.

O pre-flight apresenta ainda uma recomendacao de cadencia: margem reservada para retries, rondas completas possiveis e tamanho seguro de uma coorte. `network.daily_call_reserves.alpha_vantage` fica em 5 por defeito; quando o universo cresce alem da quota, usa o cache para os restantes ativos e rota as coortes por dia em vez de tentar chamadas ate falhar.

Para atualizar apenas uma coorte sem perder a visão do universo, passa os símbolos ao comando. Os ativos fora da coorte ficam no snapshot com a última leitura live local, marcados como `ATRASADO`:

```powershell
.\run.ps1 -Mode live -Symbols "GOLD,SILVER,AI,ENERGY"
```

O pré-flight aceita o mesmo parâmetro (`-PlanOnly -Symbols ...`) e calcula o custo da coorte. A coorte não deve ser usada para paper trading estrito até todos os ativos críticos terem uma leitura `OK` no mesmo ciclo.

## Limites

O score é uma ferramenta de investigação. Não prevê o mercado, não garante retorno e não envia ordens para corretoras. O modo demo usa dados sintéticos e não deve suportar decisões de investimento.
