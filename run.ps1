param(
  [ValidateSet("demo", "live")]
  [string]$Mode = "demo",
  [switch]$PlanOnly,
  [switch]$Paper,
  [double]$PaperInitialCash = 10000,
  [string]$PaperState = "",
  [ValidateSet("strict", "ladder", "matrix")]
  [string]$PaperPolicy = "strict",
  [string]$Symbols = "",
  [ValidateSet("", "alpha_vantage", "tiingo", "yahoo_finance")]
  [string]$PriceProvider = "",
  [ValidateSet("core", "expanded")]
  [string]$UniverseProfile = "core",
  [int]$CohortSize = 15,
  [int]$CohortIndex = -1,
  [switch]$MonitorPortfolio,
  [switch]$NoPortfolioMonitor,
  [int]$PortfolioMonitorLimit = 10
)

$projectRoot = $PSScriptRoot
$ErrorActionPreference = "Stop"
$outputDir = Join-Path $projectRoot "outputs"
$automationStatusPath = Join-Path $outputDir "automation-status.json"
$automationHistoryPath = Join-Path $outputDir "automation-history.jsonl"
$startedAt = (Get-Date).ToUniversalTime().ToString("o")

function Write-AutomationHistory {
  param(
    [Parameter(Mandatory = $true)]$Payload
  )
  try {
    $lines = @()
    if (Test-Path -LiteralPath $automationHistoryPath -PathType Leaf) {
      $lines = @(Get-Content -LiteralPath $automationHistoryPath -Encoding UTF8)
    }
    $lines += ($Payload | ConvertTo-Json -Compress -Depth 5)
    if ($lines.Count -gt 90) { $lines = @($lines | Select-Object -Last 90) }
    $temporaryHistory = "$automationHistoryPath.tmp"
    [IO.File]::WriteAllLines($temporaryHistory, $lines, (New-Object System.Text.UTF8Encoding($false)))
    Move-Item -LiteralPath $temporaryHistory -Destination $automationHistoryPath -Force
  } catch {
    # History is diagnostic only; never hide a valid radar result.
  }
}

function Write-AutomationStatus {
  param(
    [Parameter(Mandatory = $true)][string]$State,
    [int]$ExitCode = 0,
    [string]$ErrorMessage = ""
  )
  $payload = [ordered]@{
    state = $State
    run_id = $startedAt
    started_at = $startedAt
    completed_at = (Get-Date).ToUniversalTime().ToString("o")
    mode = $Mode
    paper = [bool]$Paper
    plan_only = [bool]$PlanOnly
    price_provider = if ($PriceProvider) { $PriceProvider } else { "configuração" }
    universe_profile = $UniverseProfile
    exit_code = $ExitCode
    error = $ErrorMessage
  }
  try {
    New-Item -ItemType Directory -Path $outputDir -Force | Out-Null
    $temporary = "$automationStatusPath.tmp"
    $json = $payload | ConvertTo-Json -Depth 5
    [IO.File]::WriteAllText($temporary, $json, (New-Object System.Text.UTF8Encoding($false)))
    Move-Item -LiteralPath $temporary -Destination $automationStatusPath -Force
    if ($State -ne "running") { Write-AutomationHistory -Payload $payload }
  } catch {
    # Telemetry failure must never hide the radar result.
  }
}

Write-AutomationStatus -State "running"
$pythonPath = Join-Path $projectRoot ".runtime\python\python.exe"
$nodePath = Join-Path $projectRoot ".runtime\node\node.exe"

if (-not (Test-Path -LiteralPath $pythonPath)) { $pythonPath = "python" }
if (-not (Test-Path -LiteralPath $nodePath)) { $nodePath = "node" }

$radarArgs = @((Join-Path $projectRoot "src\momentum_tool.py"), "--mode", $Mode, "--output-dir", $outputDir)
if ($PlanOnly) { $radarArgs += "--plan-only" }
if ($Symbols) { $radarArgs += @("--symbols", $Symbols) }
if ($PriceProvider) { $radarArgs += @("--price-provider", $PriceProvider) }
$radarArgs += @("--universe-profile", $UniverseProfile)
$radarArgs += @("--cohort-size", $CohortSize, "--cohort-index", $CohortIndex)
if (($Mode -eq "live" -and -not $NoPortfolioMonitor) -or $MonitorPortfolio) { $radarArgs += @("--monitor-portfolio", "--portfolio-monitor-limit", $PortfolioMonitorLimit) }
& $pythonPath @radarArgs
if ($LASTEXITCODE -ne 0) {
  $code = $LASTEXITCODE
  Write-AutomationStatus -State "failed" -ExitCode $code -ErrorMessage "momentum_tool terminou com código $code"
  exit $code
}

if ($PlanOnly) {
  Write-AutomationStatus -State "completed" -ExitCode 0
  exit 0
}

if ($Paper) {
  if (-not $PaperState) { $PaperState = Join-Path $projectRoot "outputs\paper_portfolio.json" }
  elseif (-not [IO.Path]::IsPathRooted($PaperState)) { $PaperState = Join-Path $projectRoot $PaperState }
  $paperPrefix = [IO.Path]::GetFileNameWithoutExtension($PaperState)
  $paperArgs = @((Join-Path $projectRoot "src\paper_trading.py"), "--signals", (Join-Path $projectRoot "outputs\momentum_data.json"), "--state", $PaperState, "--output-dir", $outputDir, "--initial-cash", $PaperInitialCash, "--output-prefix", $paperPrefix, "--policy", $PaperPolicy)
  if ($Mode -eq "live") { $paperArgs += "--strict-live-quality" }
  & $pythonPath @paperArgs
  if ($LASTEXITCODE -ne 0) {
    $code = $LASTEXITCODE
    Write-AutomationStatus -State "failed" -ExitCode $code -ErrorMessage "paper_trading terminou com código $code"
    exit $code
  }
  $env:RADAR_PAPER_STATE = $PaperState
}

& $nodePath (Join-Path $projectRoot "src\build_workbook.mjs")
if ($LASTEXITCODE -ne 0) {
  $code = $LASTEXITCODE
  Write-AutomationStatus -State "failed" -ExitCode $code -ErrorMessage "build_workbook terminou com código $code"
  exit $code
}
Write-AutomationStatus -State "completed" -ExitCode 0
exit 0
