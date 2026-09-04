# Privacidade

O Radar foi desenhado para correr localmente. O operador da instalação é o
responsável pelos dados introduzidos e deve guardar o diretório do projeto com
as permissões adequadas.

## Dados locais

O Radar pode ler e guardar posições, quantidade, preço médio, notas pessoais,
preferências do browser e relatórios gerados. A autenticação guarda apenas uma
sessão temporária em memória; a password não é escrita em disco. O `.gitignore`
exclui a carteira, notas, caches, outputs e ficheiros de ambiente por defeito.
Importadores específicos de carteiras e metas pessoais também são excluídos.
Os testes devem usar posições fictícias e temporárias; nunca extratos reais.
O pacote portátil exclui dados pessoais e relatórios locais.

## Dados enviados

Quando uma análise live é pedida, símbolos e pedidos de dados podem ser enviados
para os providers configurados. Consulta os termos e políticas desses
providers antes de usar dados reais. A navegação pelo snapshot local não precisa
de chamadas externas.

## Retenção e eliminação

Para eliminar dados, apaga os ficheiros locais de `data/` e `outputs/` que não
pretendas manter e limpa o armazenamento local do browser. Revoga também as
chaves de API no provider quando deixarem de ser necessárias.
