param(
    [string]$Config = ""
)

$ErrorActionPreference = "Stop"
$projectRoot = $PSScriptRoot
$pythonPath = Join-Path $projectRoot ".runtime\python\python.exe"
if (-not (Test-Path -LiteralPath $pythonPath)) { $pythonPath = "python" }
$arguments = @((Join-Path $projectRoot "src\validate_config.py"))
if ($Config) { $arguments += @("--config", $Config) }
& $pythonPath @arguments
exit $LASTEXITCODE
