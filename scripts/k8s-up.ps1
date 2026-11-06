# Sobe a aplicação inteira no Kubernetes local (k3d), do zero:
#   cluster de 3 nós -> imagens -> namespace + Secret -> manifestos -> espera tudo ficar pronto.
# Pode rodar de novo: o que já existe é mantido ou atualizado.
#
# Uso, no PowerShell, na pasta do projeto:   .\scripts\k8s-up.ps1
# Requisitos: Docker Desktop em execução, kubectl e k3d (winget install k3d.k3d).
param([string]$Cluster = "aps")
Set-Location (Split-Path $PSScriptRoot -Parent)
$NS = "aps"
$Secret = "aps-credenciais"

function Exigir([string]$descricao) {
    if ($LASTEXITCODE -ne 0) { throw "Falhou: $descricao" }
}

# 1. Cluster: 1 servidor (plano de controle) + 2 agentes = 3 nós, cada um um contêiner Docker.
#    A porta 8081 da máquina chega à porta 80 do cluster, onde o Traefik (Ingress) escuta.
$existente = @(k3d cluster list -o json | ConvertFrom-Json) | Where-Object { $_.name -eq $Cluster }
if (-not $existente) {
    k3d cluster create $Cluster --agents 2 -p "8081:80@loadbalancer"
    Exigir "k3d cluster create"
}
kubectl config use-context "k3d-$Cluster" | Out-Null
kubectl wait --for=condition=Ready nodes --all --timeout=120s
Exigir "nós prontos"

# 2. Imagens com tag fixa, importadas nos nós
& "$PSScriptRoot\k8s-build.ps1" -Versao "1.1.0" -Cluster $Cluster

# 3. Namespace e Secret. O Secret vem do .env (fora do Git); o repositório só leva o modelo.
if (-not (Test-Path .env)) {
    Copy-Item .env.example .env
    Write-Host ">> .env criado a partir do .env.example"
}
$conteudo = (Get-Content .env -Raw) -replace "`r", ""     # CRLF grudaria um \r no fim de cada senha
foreach ($chave in "POSTGRES_USER", "POSTGRES_PASSWORD", "RABBITMQ_USER", "RABBITMQ_PASSWORD") {
    if ($conteudo -notmatch "(?m)^$chave=") { throw "Falta $chave no .env (veja o .env.example)" }
}
kubectl apply -f k8s/00-namespace.yaml
Exigir "namespace"
# Arquivo temporário em UTF-8 SEM BOM: com BOM, a primeira linha viraria uma chave inválida
$temporario = [IO.Path]::GetTempFileName()
[IO.File]::WriteAllText($temporario, $conteudo, (New-Object Text.UTF8Encoding $false))
kubectl create secret generic $Secret -n $NS "--from-env-file=$temporario" --dry-run=client -o yaml | kubectl apply -f -
$codigo = $LASTEXITCODE
Remove-Item $temporario
if ($codigo -ne 0) { throw "Falhou: Secret" }

# 4. Todo o resto, em ordem alfabética dos arquivos
kubectl apply -f k8s/
Exigir "kubectl apply -f k8s/"

# 5. Espera cada peça ficar pronta
kubectl rollout status statefulset/postgres -n $NS --timeout=180s; Exigir "postgres"
kubectl rollout status statefulset/rabbitmq -n $NS --timeout=240s; Exigir "rabbitmq"
foreach ($d in "redis", "air-quality-api", "flooding-api", "thermal-inversion-api", "web-client") {
    kubectl rollout status "deployment/$d" -n $NS --timeout=180s
    Exigir $d
}

kubectl get all,ingress,pvc,hpa -n $NS -o wide
Write-Host ""
Write-Host "Pronto. Cliente web: http://localhost:8081/"
Write-Host "Swagger: http://localhost:8081/api/v1/air-quality/swagger  (flooding, thermal-inversion)"
Write-Host "Verificação: .\scripts\k8s-verificar.ps1"
