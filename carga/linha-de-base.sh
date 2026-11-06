#!/usr/bin/env bash
# Linha de base da Etapa 4: 1 réplica de cada serviço, HPA removido, carga em degraus até saturar.
#   ./carga/linha-de-base.sh                 3 repetições, 30 s por degrau (~30 min no total)
#   REPS=1 DURACAO=15 ./carga/linha-de-base.sh   rodada rápida para conferir
#
# Rotas medidas (pelo gateway):
#   ingestao  POST /api/v1/air-quality/particulate      o serviço que o HPA escala: escrita no banco + fila
#   consulta  GET  /api/v1/air-quality/stations/{id}/latest   leitura com custo estável (índice), com cache Redis
# Ao terminar, devolve o cluster ao normal (HPAs de volta, mínimo de 2 réplicas).
set -euo pipefail
cd "$(dirname "$0")/.."

NS=aps
GW="${GW:-http://127.0.0.1:8081}"
REPS="${REPS:-3}"
DURACAO="${DURACAO:-30}"
AQUECIMENTO="${AQUECIMENTO:-5}"
DEGRAUS="${DEGRAUS:-1,2,4,8,16,32,64}"
PY="${PYTHON:-python}"
export PYTHONIOENCODING=utf-8
SAIDA="resultados/base/$(date +%Y%m%d-%H%M)"
APIS=(air-quality-api flooding-api thermal-inversion-api)
ESTACOES="EST-01|EST-02|EST-03|EST-04|EST-05|EST-06|EST-07|EST-08|EST-09|EST-10"

# O POST responde antes de o alerta ser avaliado: ao fim da ingestão a fila ainda tem mensagens, e os
# consumidores seguem gastando CPU da API e do banco. Medir a próxima rota antes de a fila esvaziar
# contaminaria o resultado. O tempo até esvaziar também é um dado: quanto o consumidor ficou para trás.
esperar_fila() {
  local arquivo="$1" inicio=$SECONDS total primeiro=""
  while :; do
    total=$(kubectl exec -n "$NS" rabbitmq-0 -- rabbitmqctl -q list_queues messages 2>/dev/null | awk 'NR>1{s+=$1} END{print s+0}')
    [ -z "$primeiro" ] && primeiro=$total
    [ "$total" -eq 0 ] && break
    [ $((SECONDS - inicio)) -ge 600 ] && { echo "   fila ainda com $total mensagens após 600 s"; break; }
    sleep 3
  done
  echo "mensagens na fila ao fim da carga: $primeiro | segundos até esvaziar: $((SECONDS - inicio))" | tee "$arquivo"
  sleep 20   # deixa a CPU baixar e o metrics-server atualizar antes da próxima rodada
}

restaurar() {
  echo ">> devolvendo o cluster ao normal (HPAs de volta)"
  kubectl apply -f k8s/40-hpa.yaml >/dev/null
}
trap restaurar EXIT

mkdir -p "$SAIDA"
echo ">> resultados em $SAIDA"

# 1. Uma réplica de cada serviço. O HPA desfaria a escala manual: sai antes.
kubectl delete hpa --all -n "$NS" --ignore-not-found
for d in "${APIS[@]}"; do kubectl scale deployment "$d" -n "$NS" --replicas=1; done
for d in "${APIS[@]}"; do kubectl rollout status deployment "$d" -n "$NS" --timeout=120s; done
sleep 10   # espera os pods que estão saindo terminarem (preStop) e o gateway atualizar os destinos

# 2. Estado do cluster durante a medição (evidência do item 10 da ficha)
{
  echo "# $(date '+%d/%m/%Y %H:%M:%S')"
  kubectl get deploy,hpa -n "$NS" -o wide 2>&1
  echo
  kubectl get pods -n "$NS" -o wide
  echo
  kubectl get nodes -o wide
} > "$SAIDA/estado-do-cluster.txt"
cat "$SAIDA/estado-do-cluster.txt"

# 3. Garante que existe ao menos uma leitura de cada estação (a consulta devolveria 404 sem elas)
for i in $(seq -w 1 10); do
  curl -s -o /dev/null -X POST "$GW/api/v1/air-quality/particulate" -H 'Content-Type: application/json' \
    -d "{\"stationId\":\"EST-$i\",\"sensorId\":\"SEN-PM-1\",\"areaId\":\"CENTRO\",\"pm25\":10,\"pm10\":20}"
done

# 4. Degraus, REPS vezes cada rota, alternando as rotas entre as repetições
for rep in $(seq 1 "$REPS"); do
  echo; echo "================ repetição $rep/$REPS: ingestão ================"
  "$PY" carga/loadgen.py "$GW/api/v1/air-quality/particulate" -X POST --corpo ar \
    --degraus "$DEGRAUS" --duracao-degrau "$DURACAO" --aquecimento "$AQUECIMENTO" --timeout 5 \
    --top --top-intervalo 3 --saida "$SAIDA/ingestao-rep$rep"
  esperar_fila "$SAIDA/ingestao-rep$rep-fila.txt"
  echo; echo "================ repetição $rep/$REPS: consulta ================"
  "$PY" carga/loadgen.py "$GW/api/v1/air-quality/stations/{{escolha:$ESTACOES}}/latest" \
    --degraus "$DEGRAUS" --duracao-degrau "$DURACAO" --aquecimento "$AQUECIMENTO" --timeout 5 \
    --top --top-intervalo 3 --saida "$SAIDA/consulta-rep$rep"
  esperar_fila "$SAIDA/consulta-rep$rep-fila.txt"
done

# 5. Tabelas e gráficos
"$PY" carga/graficos.py "$SAIDA"
echo; echo ">> pronto: $SAIDA (tabela-*.md, grafico-*.png, linha-de-base.json e os arquivos brutos)"
