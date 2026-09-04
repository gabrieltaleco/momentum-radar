# Segurança

## Reportar uma vulnerabilidade

Não publiques detalhes de uma vulnerabilidade num issue. Envia uma mensagem
privada ao proprietário do repositório com:

- componente e versão afetados;
- passos mínimos para reproduzir;
- impacto observado e uma correção sugerida, se existir;
- qualquer log sem passwords, tokens, dados de carteira ou informação pessoal.

Confirmarei a receção assim que possível e combinaremos a divulgação depois de
existir uma correção. Não há programa de recompensa neste projeto.

## Limites atuais

O Radar é uma ferramenta local e não executa ordens. O servidor deve ficar
ligado a `127.0.0.1` por defeito. Não o exponhas diretamente à internet: o
`http.server` integrado é adequado para desenvolvimento local, não para uma
instalação pública sem um servidor endurecido, HTTPS, gestão de utilizadores e
proteção operacional.

As passwords são fornecidas por variável de ambiente, as sessões são mantidas
apenas em memória e as rotas de leitura e escrita exigem sessão autenticada.
Chaves de providers nunca devem ser commitadas. Se uma chave aparecer num log,
ficheiro ou histórico Git, revoga-a e gera uma nova imediatamente.
