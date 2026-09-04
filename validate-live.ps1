param(
    [switch]$AllowMissingContext
)

$ErrorActionPreference = "Stop"
$projectRoot = $PSScriptRoot
$pythonPath = Join-Path $projectRoot ".runtime\python\python.exe"
if (-not (Test-Path -LiteralPath $pythonPath)) { $pythonPath = "python" }
$arguments = @((Join-Path $projectRoot "src\validate_live.py"), "--output-dir", (Join-Path $projectRoot "outputs"))
if ($AllowMissingContext) { $arguments += "--allow-missing-context" }
& $pythonPath @arguments
exit $LASTEXITCODE
