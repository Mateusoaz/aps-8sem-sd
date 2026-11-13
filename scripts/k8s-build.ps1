# Constrói as 3 imagens das APIs com a mesma tag e as importa nos nós do cluster k3d.
#   .\scripts\k8s-build.ps1                -> tag 1.1.0 (a dos manifestos)
#   .\scripts\k8s-build.ps1 -Versao 1.2.0  -> outra versão, para o rolling update:
#        kubectl set image deployment/air-quality-api -n aps api=aps-sd/air-quality-api:1.2.0
#
# O cluster NÃO enxerga as imagens do Docker da máquina: cada nó tem o próprio depósito.
# Por isso o "k3d image import" depois do build.
param(
    [string]$Versao = "1.1.0",
    [string]$Cluster = "aps"
)
Set-Location (Split-Path $PSScriptRoot -Parent)

$imagens = [ordered]@{
    "air-quality-api"       = "src/AirQuality.Api"
    "flooding-api"          = "src/Flooding.Api"
    "thermal-inversion-api" = "src/ThermalInversion.Api"
}

$tags = @()
foreach ($nome in $imagens.Keys) {
    $tag = "aps-sd/${nome}:$Versao"
    Write-Host ">> docker build $tag"
    docker build --quiet --build-arg "APP_VERSION=$Versao" -t $tag $imagens[$nome]
    if ($LASTEXITCODE -ne 0) { throw "docker build falhou: $tag" }
    $tags += $tag
}

Write-Host ">> k3d image import ($($tags.Count) imagens) no cluster $Cluster"
k3d image import -c $Cluster @tags
if ($LASTEXITCODE -ne 0) { throw "k3d image import falhou" }
