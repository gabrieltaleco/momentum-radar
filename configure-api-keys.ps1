param()

$ErrorActionPreference = "Stop"

$definitions = @(
    @{ Name = "ALPHAVANTAGE_API_KEY"; Label = "Alpha Vantage" },
    @{ Name = "FRED_API_KEY"; Label = "FRED" },
    @{ Name = "COINMARKETCAP_API_KEY"; Label = "CoinMarketCap Basic" }
)

Write-Host "As chaves serao gravadas apenas nas variaveis de utilizador do Windows."
Write-Host "A entrada fica escondida e nunca e escrita num ficheiro do projeto."
Write-Host "Pressiona Enter sem escrever nada para manter uma chave ja existente."
Write-Host ""

foreach ($definition in $definitions) {
    $secret = Read-Host -Prompt "$($definition.Label) API key" -AsSecureString
    $pointer = [IntPtr]::Zero
    try {
        $pointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secret)
        $value = ([Runtime.InteropServices.Marshal]::PtrToStringBSTR($pointer)).Trim()
        if (-not [string]::IsNullOrWhiteSpace($value)) {
            [Environment]::SetEnvironmentVariable($definition.Name, $value, "User")
            Write-Host "$($definition.Name): guardada"
        } else {
            Write-Host "$($definition.Name): mantida"
        }
    } finally {
        if ($pointer -ne [IntPtr]::Zero) {
            [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($pointer)
        }
    }
}

Write-Host ""
Write-Host "Concluido. Fecha esta PowerShell, abre uma nova e executa validate-live.ps1."
