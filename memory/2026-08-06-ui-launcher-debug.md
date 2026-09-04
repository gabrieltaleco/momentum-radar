# Debug report — arranque da interface

- Sintoma: `run-ui.ps1` falhava com `Cannot overwrite variable Host` e o browser mostrava `ERR_CONNECTION_REFUSED`.
- Causa: `$Host` é uma variável automática, constante e reservada do PowerShell. O script falhava antes de iniciar o servidor Python.
- Correção: o parâmetro passou a chamar-se `$ListenHost`; o encaminhamento para `app_server.py` usa o mesmo nome.
- Verificação: `run-ui.ps1 -CheckOnly` terminou com código 0; a suíte completa passou 25 testes; o servidor e os endpoints tinham sido validados anteriormente.
- Regressão: `tests/test_ui_launcher.py` garante que o script não volta a declarar `[string]$Host`.
- Estado: DONE.
