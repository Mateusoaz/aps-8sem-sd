# Verificação rápida da aplicação no cluster, sempre PELO GATEWAY (http://localhost:8081).
# Confere: cliente web, readiness das 3 APIs, POST com alerta via fila, cache (MISS -> HIT),
# distribuição das requisições entre os pods (X-Pod) e métricas (kubectl top).
#
# Uso:   .\scripts\k8s-verificar.ps1
param([string]$Gateway = "http://127.0.0.1:8081")
$NS = "aps"
$script:falhas = 0

Add-Type -AssemblyName System.Net.Http
$http = New-Object System.Net.Http.HttpClient
$http.Timeout = [TimeSpan]::FromSeconds(10)

function Ok([string]$texto)   { Write-Host "  OK   $texto" -ForegroundColor Green }
function Erro([string]$texto) { Write-Host "  ERRO $texto" -ForegroundColor Red; $script:falhas++ }

# Faz a requisição e devolve status, corpo e cabeçalhos (o HttpClient não lança exceção em 4xx/5xx)
function Chamar([string]$metodo, [string]$url, [string]$json) {
    $pedido = New-Object System.Net.Http.HttpRequestMessage ([System.Net.Http.HttpMethod]::new($metodo)), $url
    if ($json) { $pedido.Content = New-Object System.Net.Http.StringContent $json, ([Text.Encoding]::UTF8), "application/json" }
    try {
        $r = $http.SendAsync($pedido).GetAwaiter().GetResult()
        $cab = @{}
        foreach ($h in $r.Headers) { $cab[$h.Key] = ($h.Value -join ",") }
        return @{ Status = [int]$r.StatusCode; Corpo = $r.Content.ReadAsStringAsync().GetAwaiter().GetResult(); Cab = $cab }
    } catch {
        return @{ Status = 0; Corpo = $_.Exception.Message; Cab = @{} }
    }
}

Write-Host "== Cliente web"
$r = Chamar GET "$Gateway/"
if ($r.Status -eq 200) { Ok "GET / -> 200" } else { Erro "GET / -> $($r.Status)" }

$servicos = [ordered]@{
    "air-quality" = @{
        Post = "particulate"; Consulta = "areas/VERIF/average?hours=24"
        Json = '{"stationId":"EST-VERIF","sensorId":"SEN-PM-01","areaId":"VERIF","pm25":12.5,"pm10":20}' }
    "flooding" = @{
        Post = "water-level"; Consulta = "monitoring-points/PT-VERIF/latest"
        Json = '{"monitoringPointId":"PT-VERIF","sensorId":"SEN-N-01","waterLevelCm":120}' }
    "thermal-inversion" = @{
        Post = "temperature-profile"; Consulta = "areas/VERIF/thermal-profile?hours=24"
        Json = '{"stationId":"EST-VERIF","areaId":"VERIF","surfaceSensorId":"S1","upperSensorId":"S2","surfaceTemperatureC":15,"upperTemperatureC":12}' }
}

foreach ($nome in $servicos.Keys) {
    $s = $servicos[$nome]
    $base = "$Gateway/api/v1/$nome"
    Write-Host "== $nome"

    $r = Chamar GET "$base/health/ready"
    if ($r.Status -eq 200) { Ok "readiness 200: $($r.Corpo)" } else { Erro "readiness -> $($r.Status): $($r.Corpo)" }

    $r = Chamar POST "$base/$($s.Post)" $s.Json
    $modo = $r.Cab["X-Alerta"]
    if ($r.Status -eq 201) { Ok "POST /$($s.Post) -> 201 (alerta: $modo)" } else { Erro "POST /$($s.Post) -> $($r.Status)" }
    if ($modo -ne "fila") { Erro "alerta não passou pela fila (X-Alerta: $modo)" }

    $c1 = (Chamar GET "$base/$($s.Consulta)").Cab["X-Cache"]
    $c2 = (Chamar GET "$base/$($s.Consulta)").Cab["X-Cache"]
    if ($c2 -eq "HIT") { Ok "cache: 1ª $c1, 2ª $c2" } else { Erro "cache: 1ª $c1, 2ª $c2 (esperado HIT na 2ª)" }

    $pods = 1..10 | ForEach-Object { (Chamar GET "$base/health/live").Cab["X-Pod"] } | Group-Object | Sort-Object Name
    if ($pods.Count -ge 2) { Ok "10 requisições em $($pods.Count) pods:" } else { Erro "10 requisições caíram em $($pods.Count) pod(s):" }
    $pods | ForEach-Object { Write-Host ("         {0,3} {1}" -f $_.Count, $_.Name) }
}

Write-Host "== Métricas (metrics-server)"
$top = kubectl top pod -n $NS 2>$null
if ($LASTEXITCODE -eq 0 -and $top) {
    Ok "kubectl top pod responde"
    $top | ForEach-Object { Write-Host "         $_" }
} else {
    Erro "kubectl top pod ainda sem dados (espere ~1 min depois de subir)"
}

Write-Host ""
if ($script:falhas -eq 0) { Write-Host "Tudo certo." -ForegroundColor Green } else { Write-Host "$($script:falhas) verificação(ões) falharam." -ForegroundColor Red }
exit $script:falhas
