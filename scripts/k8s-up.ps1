# Sobe a aplicação inteira no Kubernetes local (k3d), do zero:
#   cluster de 3 nós -> imagens -> namespace + Secret -> manifestos -> espera tudo ficar pronto.
# Pode rodar de novo: o que já existe é mantido ou atualizado.
#
# Uso, no PowerShell, na pasta do projeto:   .\scripts\k8s-up.ps1
# Requisitos: Docker Desktop em execução, kubectl e k3d (winget install k3d.k3d).
param([string]$Cluster = "aps")
Set-Location (Split-Path $PSScriptRoot -Parent)
$NS = "aps"
$Secret = "banco-credenciais"

function Exigir([string]$descricao) {
    if ($LASTEXITCODE -ne 0) { throw "Falhou: $descricao" }
}

# 1. Cluster: 1 servidor + 2 agentes = 3 nós, cada um um contêiner Docker.
#    O servidor ganha a marca (taint) de plano de controle: fica com o Kubernetes em si e os
#    componentes do sistema (Traefik, CoreDNS, metrics-server), e os pods da aplicação vão para os agentes.
#    A porta 8081 da máquina chega à porta 80 do cluster, onde o Traefik (Ingress) escuta.
$existente = @(k3d cluster list -o json | ConvertFrom-Json) | Where-Object { $_.name -eq $Cluster }
if (-not $existente) {
    k3d cluster create $Cluster --agents 2 -p "8081:80@loadbalancer" `
        --k3s-arg "--node-taint=node-role.kubernetes.io/control-plane:NoSchedule@server:0"
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
foreach ($chave in "POSTGRES_USER", "POSTGRES_PASSWORD") {
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
foreach ($d in "air-quality-api", "flooding-api", "thermal-inversion-api") {
    kubectl rollout status "deployment/$d" -n $NS --timeout=180s
    Exigir $d
}

kubectl get pods -n $NS -o wide
Write-Host ""
Write-Host "Pronto. Swagger: http://localhost:8081/air-quality/swagger  (ou /flooding, /thermal-inversion)"
Write-Host "Verificação: .\scripts\k8s-verificar.ps1"
