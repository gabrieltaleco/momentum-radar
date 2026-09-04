param(
    [int]$Port = 8765,
    [string]$ListenHost = "127.0.0.1",
    [switch]$CheckOnly
)

$ErrorActionPreference = "Stop"
$projectRoot = (Resolve-Path $PSScriptRoot).Path
if ($CheckOnly) {
  Write-Output "Launcher válido: http://$ListenHost`:$Port"
  exit 0
}
if (-not $env:RADAR_AUTH_PASSWORD -and -not $env:RADAR_AUTH_DISABLED) {
  $securePassword = Read-Host "Password do Radar (não será guardada no projeto)" -AsSecureString
  $env:RADAR_AUTH_PASSWORD = [Runtime.InteropServices.Marshal]::PtrToStringBSTR(
    [Runtime.InteropServices.Marshal]::SecureStringToBSTR($securePassword)
  )
}
Write-Host "A abrir o Radar UI em http://$ListenHost`:$Port"
python (Join-Path $projectRoot "app_server.py") --host $ListenHost --port $Port
