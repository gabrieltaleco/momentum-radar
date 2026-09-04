param(
    [string]$Destination = (Join-Path $PSScriptRoot "outputs\radar-momentum-portable.zip"),
    [string]$NodeRuntimeSource = ""
)

$ErrorActionPreference = "Stop"
$projectRoot = (Resolve-Path $PSScriptRoot).Path
$destinationPath = [IO.Path]::GetFullPath($Destination)
$stagingRoot = Join-Path $projectRoot "work\portable"
$staging = Join-Path $stagingRoot "radar-momentum-setorial"

if (Test-Path -LiteralPath $staging) {
    Remove-Item -LiteralPath $staging -Recurse -Force
}
New-Item -ItemType Directory -Path $staging -Force | Out-Null

$files = @(
    "config.json",
    "README.md",
    "run.ps1",
    "run.bat",
    "package-portable.ps1",
    "register-daily-task.ps1",
    "monitor-paper-week.ps1",
    "validate-live.ps1",
    "validate-config.ps1",
    "configure-api-keys.ps1",
    "app_server.py",
    "run-ui.ps1",
    "run-ui.bat",
    "ui\index.html",
    "ui\styles.css",
    "ui\app.js",
    "data\user_portfolio.json",
    "data\asset_catalog.json",
    "data\portfolio_import_2026-08-06.json",
    "scripts\import_portfolio_2026_08_06.py",
    "src\momentum_tool.py",
    "src\build_workbook.mjs",
    "src\validate_live.py",
    "src\validate_config.py",
    "src\paper_trading.py",
    "src\sensitivity.py",
    "src\metric_explanations.py",
    "src\pdf_report.py",
    "docs\feature-scout-2026-08-05.md",
    "docs\feature-scout-2026-08-06.md",
    "docs\paper-trading-test-plan-2026-08-05.md",
    "tests\test_momentum_tool.py",
    "tests\test_paper_trading.py",
    "tests\test_sensitivity.py",
    "tests\test_app_server.py",
    "tests\test_ui_launcher.py",
    "tests\test_metric_explanations.py",
    "outputs\radar-momentum.xlsx",
    "outputs\relatorio-momentum.md",
    "outputs\radar-slv-relatorio.md",
    "outputs\radar-slv-relatorio.pdf",
    "outputs\signals.csv",
    "outputs\momentum_data.json",
    "outputs\paper_portfolio.json",
    "outputs\paper_trades.csv",
    "outputs\paper-report.md",
    "outputs\paper-week-100k.json",
    "outputs\paper-week-100k_portfolio.json",
    "outputs\paper-week-100k_trades.csv",
    "outputs\paper-week-100k-report.md",
    "outputs\paper-week-100k_status.json",
    "outputs\sensitivity.json",
    "outputs\sensitivity-report.md",
    "outputs\alerts.json",
    "outputs\signal-history.jsonl",
    "outputs\signal-outcomes.jsonl"
)
if (Test-Path -LiteralPath (Join-Path $projectRoot "outputs\live-validation.json") -PathType Leaf) {
    $files += "outputs\live-validation.json"
}

foreach ($relativePath in $files) {
    $source = Join-Path $projectRoot $relativePath
    if (-not (Test-Path -LiteralPath $source -PathType Leaf)) {
        Write-Warning "A ignorar ficheiro ausente: $relativePath"
        continue
    }
    $target = Join-Path $staging $relativePath
    $targetDir = Split-Path -Parent $target
    New-Item -ItemType Directory -Path $targetDir -Force | Out-Null
    Copy-Item -LiteralPath $source -Destination $target -Force
}

$onDemandSource = Join-Path $projectRoot "data\on_demand"
if (Test-Path -LiteralPath $onDemandSource -PathType Container) {
    $onDemandTarget = Join-Path $staging "data\on_demand"
    New-Item -ItemType Directory -Path $onDemandTarget -Force | Out-Null
    Get-ChildItem -LiteralPath $onDemandSource -File -Filter "*.json" | Copy-Item -Destination $onDemandTarget -Force
}

$runtimeSource = Join-Path $projectRoot ".runtime"
if (Test-Path -LiteralPath $runtimeSource -PathType Container) {
    $runtimeItem = Get-Item -LiteralPath $runtimeSource -Force
    if ($runtimeItem.Attributes -band [IO.FileAttributes]::ReparsePoint) {
        Write-Warning ".runtime é uma ligação/reparse point; não será seguida para evitar incluir a cache global."
    } else {
        Copy-Item -LiteralPath $runtimeSource -Destination (Join-Path $staging ".runtime") -Recurse -Force
    }
}

if ($NodeRuntimeSource) {
    $nodeRoot = (Resolve-Path $NodeRuntimeSource).Path
    $nodeExe = Join-Path $nodeRoot "bin\node.exe"
    $artifactSource = Join-Path $nodeRoot "node_modules\@oai\artifact-tool"
    if (-not (Test-Path -LiteralPath $nodeExe -PathType Leaf)) {
        throw "NodeRuntimeSource não contém bin\node.exe: $nodeRoot"
    }
    if (-not (Test-Path -LiteralPath $artifactSource -PathType Container)) {
        throw "NodeRuntimeSource não contém node_modules\@oai\artifact-tool: $nodeRoot"
    }
    $runtimeNodeDir = Join-Path $staging ".runtime\node"
    New-Item -ItemType Directory -Path $runtimeNodeDir -Force | Out-Null
    Copy-Item -LiteralPath $nodeExe -Destination (Join-Path $runtimeNodeDir "node.exe") -Force
    $artifactTarget = Join-Path $staging "src\node_modules\@oai\artifact-tool"
    New-Item -ItemType Directory -Path (Split-Path -Parent $artifactTarget) -Force | Out-Null
    Copy-Item -LiteralPath $artifactSource -Destination $artifactTarget -Recurse -Force
}

$manifest = @"
Radar Momentum Setorial — pacote portátil
Gerado: $(Get-Date -Format "yyyy-MM-dd HH:mm:ss zzz")

Modo demo: .\run.ps1 -Mode demo
Modo live: execute .\configure-api-keys.ps1 numa PowerShell, abra uma nova janela e execute .\run.ps1 -Mode live
Interface: execute .\run-ui.ps1 e abra http://127.0.0.1:8765 no browser
Automação: powershell.exe -ExecutionPolicy Bypass -File .\register-daily-task.ps1 -Mode live

O pacote não contém chaves de API. O Excel e o relatório incluídos são o último snapshot gerado.
$(if ($NodeRuntimeSource) { "Foi incluído um runtime Node mínimo para reconstruir o Excel." } else { "Para reconstruir o Excel, execute com -NodeRuntimeSource apontado para uma distribuição Node que contenha @oai/artifact-tool." })
"@
$manifest | Set-Content -LiteralPath (Join-Path $staging "PACOTE.txt") -Encoding UTF8

$destinationDir = Split-Path -Parent $destinationPath
New-Item -ItemType Directory -Path $destinationDir -Force | Out-Null
if (Test-Path -LiteralPath $destinationPath) {
    Remove-Item -LiteralPath $destinationPath -Force
}
Compress-Archive -Path (Join-Path $staging "*") -DestinationPath $destinationPath -CompressionLevel Optimal
Remove-Item -LiteralPath $staging -Recurse -Force

$archive = Get-Item -LiteralPath $destinationPath
Write-Output ("Pacote criado: {0} ({1:N0} bytes)" -f $archive.FullName, $archive.Length)
