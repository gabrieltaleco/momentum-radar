param(
    [string]$State = "outputs\paper-week-100k.json",
    [string]$TaskName = "Radar Paper 100k - Semana",
    [int]$ExpectedRuns = 7
)

$ErrorActionPreference = "Stop"
$projectRoot = (Resolve-Path $PSScriptRoot).Path
$statePath = if ([IO.Path]::IsPathRooted($State)) { $State } else { Join-Path $projectRoot $State }
if (!(Test-Path -LiteralPath $statePath -PathType Leaf)) { throw "Estado não encontrado: $statePath" }

$stateJson = Get-Content -Raw -LiteralPath $statePath | ConvertFrom-Json
$taskInfo = $null
$task = $null
$taskError = $null
try {
    $taskInfo = Get-ScheduledTaskInfo -TaskName $TaskName -ErrorAction Stop
    $task = Get-ScheduledTask -TaskName $TaskName -ErrorAction Stop
} catch {
    # Task inspection can require elevation on some Windows installations.
    # Keep the ledger report usable instead of failing the whole monitor.
    $taskError = $_.Exception.Message
}
$runs = @($stateJson.runs | Where-Object { $_ })
$snapshots = @($stateJson.snapshots | Where-Object { $_ })
$trades = @($stateJson.trades | Where-Object { $_ })
$processedRuns = @($runs | Where-Object { $_.processed -eq $true })
$blockedRuns = @($runs | Where-Object { ([string]$_.reason) -like "qualidade live bloqueada*" })
$decisionRecords = 0
foreach ($snapshot in $snapshots) {
    $decisionRecords += [int]$snapshot.signals
}
$reviewTargetSnapshots = 60
$reviewTargetDecisions = 50
$readyForReview = ($snapshots.Count -ge $reviewTargetSnapshots -or $decisionRecords -ge $reviewTargetDecisions)
$status = [ordered]@{
    checked_at = (Get-Date).ToUniversalTime().ToString("o")
    task = $TaskName
    task_state = if ($task) { [string]$task.State } else { "Unavailable" }
    next_run = if ($taskInfo) { $taskInfo.NextRunTime } else { $null }
    last_run = if ($taskInfo) { $taskInfo.LastRunTime } else { $null }
    last_result = if ($taskInfo) { $taskInfo.LastTaskResult } else { $null }
    task_check_error = $taskError
    expected_runs = $ExpectedRuns
    recorded_runs = $runs.Count
    processed_runs = $processedRuns.Count
    blocked_runs = $blockedRuns.Count
    market_snapshots = $snapshots.Count
    trades = $trades.Count
    decision_records = $decisionRecords
    review_target_snapshots = $reviewTargetSnapshots
    review_target_decisions = $reviewTargetDecisions
    ready_for_review = $readyForReview
    review_message = if ($readyForReview) { "Amostra mínima atingida; já pode ser feita a revisão escrita." } else { "Faltam pelo menos $([Math]::Max(0, $reviewTargetSnapshots - $snapshots.Count)) snapshots ou $([Math]::Max(0, $reviewTargetDecisions - $decisionRecords)) decisões." }
    cash = [double]$stateJson.cash
    initial_cash = [double]$stateJson.initial_cash
    positions = @($stateJson.positions.PSObject.Properties).Count
    paper_only = $true
    on_track = if ($taskInfo -and $task) {
        ($task.State -eq "Ready" -and $taskInfo.LastTaskResult -eq 0 -and $runs.Count -le $ExpectedRuns)
    } else {
        # Ledger-only fallback: useful when task metadata is protected.
        ($runs.Count -le $ExpectedRuns)
    }
}
$status | ConvertTo-Json -Depth 5
