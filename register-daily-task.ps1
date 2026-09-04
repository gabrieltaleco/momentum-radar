param(
    [string]$TaskName = "Radar Momentum Setorial",
    [ValidateSet("demo", "live")]
    [string]$Mode = "live",
    [switch]$Paper,
    [double]$PaperInitialCash = 10000,
    [string]$PaperState = "",
    [ValidateSet("strict", "ladder", "matrix")]
    [string]$PaperPolicy = "strict",
    [ValidateSet("", "alpha_vantage", "tiingo", "yahoo_finance")]
    [string]$PriceProvider = "",
    [ValidateSet("core", "expanded")]
    [string]$UniverseProfile = "core",
    [int]$CohortSize = 15,
    [int]$CohortIndex = -1,
    [switch]$MonitorPortfolio,
    [int]$PortfolioMonitorLimit = 10,
    [int]$DurationDays = 0,
    [datetime]$At = (Get-Date).Date.AddHours(18)
)

$ErrorActionPreference = "Stop"
$projectRoot = (Resolve-Path $PSScriptRoot).Path
$runScript = Join-Path $projectRoot "run.ps1"
$powershell = (Get-Command powershell.exe).Source
$arguments = "-NoProfile -ExecutionPolicy Bypass -File `"$runScript`" -Mode $Mode"
if ($Paper) {
    $arguments += " -Paper -PaperInitialCash $PaperInitialCash"
    if ($PaperState) { $arguments += " -PaperState `"$PaperState`"" }
    $arguments += " -PaperPolicy $PaperPolicy"
}
if ($PriceProvider) { $arguments += " -PriceProvider $PriceProvider" }
if ($UniverseProfile -ne "core") { $arguments += " -UniverseProfile $UniverseProfile" }
if ($UniverseProfile -eq "expanded") { $arguments += " -CohortSize $CohortSize -CohortIndex $CohortIndex" }
if ($MonitorPortfolio) { $arguments += " -MonitorPortfolio -PortfolioMonitorLimit $PortfolioMonitorLimit" }
$action = New-ScheduledTaskAction -Execute $powershell -Argument $arguments -WorkingDirectory $projectRoot
if ($DurationDays -gt 0) {
    $trigger = New-ScheduledTaskTrigger -Once -At $At -RepetitionInterval (New-TimeSpan -Days 1) -RepetitionDuration (New-TimeSpan -Days $DurationDays)
} else {
    $trigger = New-ScheduledTaskTrigger -Daily -At $At
}
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -MultipleInstances IgnoreNew

Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Settings $settings -Description "Gera diariamente o Excel e relatório do Radar de Momentum Setorial." -Force | Out-Null
Write-Output ("Tarefa registada: {0} às {1:HH:mm} ({2}{3}; {4})" -f $TaskName, $At, $Mode, $(if ($Paper) { "+ paper" } else { "" }), $(if ($DurationDays -gt 0) { "durante $DurationDays dias" } else { "sem data de fim" }))
Write-Output "As chaves de API devem existir nas variáveis de ambiente do utilizador que executa a tarefa."
