# Linha de base da Etapa 4: 1 réplica de cada serviço, HPA removido, carga em degraus até saturar.
# Abre sozinho a janela com os gráficos ao vivo.
#
#   .\carga\linha-de-base.ps1                          3 repetições, 30 s por degrau (~30 min)
#   .\carga\linha-de-base.ps1 -Repeticoes 1 -Duracao 15   rodada rápida para conferir
#   .\carga\linha-de-base.ps1 -SemJanela               sem a janela ao vivo
#
# Rotas medidas (pelo gateway):
#   ingestao  POST /api/v1/air-quality/particulate            o serviço que o HPA escala: escrita no banco + fila
#   consulta  GET  /api/v1/air-quality/stations/{id}/latest   leitura com custo estável (índice), com cache Redis
# Ao terminar (ou se for interrompido), devolve o cluster ao normal: HPAs de volta, mínimo de 2 réplicas.
param(
    [int]$Repeticoes = 3,
    [int]$Duracao = 30,
    [int]$Aquecimento = 5,
    [string]$Degraus = "1,2,4,8,16,32,64",
    [string]$Gateway = "http://127.0.0.1:8081",
    [string]$Python = "python",
    [switch]$SemJanela
)
Set-Location (Split-Path $PSScriptRoot -Parent)
$NS = "aps"
$env:PYTHONIOENCODING = "utf-8"
$saida = "resultados/base/" + (Get-Date -Format "yyyyMMdd-HHmm")
$apis = "air-quality-api", "flooding-api", "thermal-inversion-api"
$estacoes = (1..10 | ForEach-Object { "EST-{0:D2}" -f $_ }) -join "|"

function Exigir([string]$descricao) {
    if ($LASTEXITCODE -ne 0) { throw "Falhou: $descricao" }
}

# O POST responde antes de o alerta ser avaliado: ao fim da ingestão a fila ainda tem mensagens, e os
# consumidores seguem gastando CPU da API e do banco. Medir a próxima rota antes de a fila esvaziar
# contaminaria o resultado. O tempo até esvaziar também é um dado: quanto o consumidor ficou para trás.
function Esperar-Fila([string]$arquivo) {
    $inicio = Get-Date
    $primeiro = $null
    while ($true) {
        $linhas = kubectl exec -n $NS rabbitmq-0 -- rabbitmqctl -q list_queues messages 2>$null
        $total = ($linhas | Select-Object -Skip 1 | Where-Object { $_ -match '^\d+$' } | Measure-Object -Sum).Sum
        if ($null -eq $total) { $total = 0 }
        if ($null -eq $primeiro) { $primeiro = $total }
        $passados = [int]((Get-Date) - $inicio).TotalSeconds
        if ($total -eq 0) { break }
        if ($passados -ge 600) { Write-Host "   fila ainda com $total mensagens após 600 s"; break }
        Start-Sleep -Seconds 3
    }
    $texto = "mensagens na fila ao fim da carga: $primeiro | segundos até esvaziar: $passados"
    Write-Host $texto
    Set-Content -Path $arquivo -Value $texto -Encoding UTF8
    Start-Sleep -Seconds 20   # deixa a CPU baixar e o metrics-server atualizar antes da próxima rodada
}

New-Item -ItemType Directory -Force $saida | Out-Null
Write-Host ">> resultados em $saida"
if (-not $SemJanela) {
    Start-Process $Python -ArgumentList "carga/ao_vivo.py", "resultados/base"
}

try {
    # 1. Uma réplica de cada serviço. O HPA desfaria a escala manual: sai antes.
    kubectl delete hpa --all -n $NS --ignore-not-found
    foreach ($d in $apis) { kubectl scale deployment $d -n $NS --replicas=1; Exigir "scale $d" }
    foreach ($d in $apis) { kubectl rollout status deployment $d -n $NS --timeout=120s; Exigir "rollout $d" }
    Start-Sleep -Seconds 10   # espera os pods que estão saindo terminarem (preStop) e o gateway atualizar

    # 2. Estado do cluster durante a medição (evidência do item 10 da ficha)
    $estado = @("# " + (Get-Date -Format "dd/MM/yyyy HH:mm:ss"))
    $estado += kubectl get deploy,hpa -n $NS -o wide 2>&1
    $estado += ""
    $estado += kubectl get pods -n $NS -o wide
    $estado += ""
    $estado += kubectl get nodes -o wide
    $estado | Set-Content -Path "$saida/estado-do-cluster.txt" -Encoding UTF8
    $estado | ForEach-Object { Write-Host $_ }

    # 3. Garante que existe ao menos uma leitura de cada estação (a consulta devolveria 404 sem elas)
    foreach ($i in 1..10) {
        $corpo = '{"stationId":"EST-' + ("{0:D2}" -f $i) + '","sensorId":"SEN-PM-1","areaId":"CENTRO","pm25":10,"pm10":20}'
        Invoke-WebRequest -UseBasicParsing -Method Post -Uri "$Gateway/api/v1/air-quality/particulate" `
            -ContentType "application/json" -Body $corpo | Out-Null
    }

    # 4. Degraus, várias vezes cada rota, alternando as rotas entre as repetições
    foreach ($rep in 1..$Repeticoes) {
        Write-Host ""; Write-Host "================ repetição $rep/${Repeticoes}: ingestão ================"
        & $Python carga/loadgen.py "$Gateway/api/v1/air-quality/particulate" -X POST --corpo ar `
            --degraus $Degraus --duracao-degrau $Duracao --aquecimento $Aquecimento --timeout 5 `
            --top --top-intervalo 3 --saida "$saida/ingestao-rep$rep"
        Exigir "loadgen ingestão"
        Esperar-Fila "$saida/ingestao-rep$rep-fila.txt"

        Write-Host ""; Write-Host "================ repetição $rep/${Repeticoes}: consulta ================"
        & $Python carga/loadgen.py "$Gateway/api/v1/air-quality/stations/{{escolha:$estacoes}}/latest" `
            --degraus $Degraus --duracao-degrau $Duracao --aquecimento $Aquecimento --timeout 5 `
            --top --top-intervalo 3 --saida "$saida/consulta-rep$rep"
        Exigir "loadgen consulta"
        Esperar-Fila "$saida/consulta-rep$rep-fila.txt"
    }

    # 5. Tabelas e gráficos
    & $Python carga/graficos.py $saida
    Write-Host ""; Write-Host ">> pronto: $saida (tabela-*.md, grafico-*.png, graficos-*/, linha-de-base.json e os arquivos brutos)"
}
finally {
    Write-Host ">> devolvendo o cluster ao normal (HPAs de volta)"
    kubectl apply -f k8s/40-hpa.yaml | Out-Null
}
