param(
    [string]$EnvFile = ".env",
    [string]$Namespace = "aps"
)

$ErrorActionPreference = "Stop"
if (-not (Test-Path -LiteralPath $EnvFile)) { throw "Arquivo $EnvFile não encontrado. Copie .env.example para .env e preencha a senha." }
$values = @{}
Get-Content -LiteralPath $EnvFile | ForEach-Object {
    if ($_ -match '^\s*([A-Za-z_][A-Za-z0-9_]*)=(.*)\s*$' -and $Matches[1] -notmatch '^\s*#') {
        $values[$Matches[1]] = $Matches[2].Trim().Trim('"').Trim("'")
    }
}
foreach ($required in @('POSTGRES_USER', 'POSTGRES_PASSWORD')) {
    if (-not $values.ContainsKey($required) -or [string]::IsNullOrWhiteSpace($values[$required])) { throw "Defina $required em $EnvFile" }
}
$user = $values['POSTGRES_USER']
$password = $values['POSTGRES_PASSWORD']
$dbHostname = "postgres"
$port = "5432"
$literals = @(
    "POSTGRES_USER=$user",
    "POSTGRES_PASSWORD=$password",
    "CONNECTION_AIR=Host=$dbHostname;Port=$port;Database=air_quality;Username=$user;Password=$password",
    "CONNECTION_FLOODING=Host=$dbHostname;Port=$port;Database=flooding;Username=$user;Password=$password",
    "CONNECTION_THERMAL=Host=$dbHostname;Port=$port;Database=thermal_inversion;Username=$user;Password=$password"
)
$secretArgs = @("create", "secret", "generic", "aps-db", "-n", $Namespace)
foreach ($entry in $literals) { $secretArgs += "--from-literal=$entry" }
$secretArgs += @("--dry-run=client", "-o", "yaml")
$secretYaml = & kubectl @secretArgs
if ($LASTEXITCODE -ne 0) { throw "Falha preparando Secret aps-db" }
$secretYaml | & kubectl apply -f -
if ($LASTEXITCODE -ne 0) { throw "Falha aplicando Secret aps-db" }
Write-Host "Secret aps-db criado no namespace $Namespace (valores não são exibidos)."
