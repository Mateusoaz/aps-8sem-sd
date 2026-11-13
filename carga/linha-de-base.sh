#!/usr/bin/env bash
# Linha de base da Etapa 4: 1 réplica de cada serviço, HPA removido, carga em degraus até saturar.
#   bash carga/linha-de-base.sh                    3 repetições, 30 s por degrau (~35 min no total)
#   REPS=1 DURACAO=10 bash carga/linha-de-base.sh  rodada rápida para conferir o fluxo
#
# Rotas medidas (pelo gateway):
#   ingestao  POST /air-quality/api/v1/air-quality/particulate
#             CPU do pod + gravação no banco + regra de alerta na própria requisição.
#             As leituras vão para a área CARGA (corpo "carga" do loadgen).
#   consulta  GET  /air-quality/api/v1/air-quality/areas/CENTRO/average?hours=24
#             a consulta agregada mais cara: seis médias sobre três tabelas a cada chamada.
# Ao terminar, devolve o cluster ao normal (2 réplicas e o HPA de volta).
set -euo pipefail
cd "$(dirname "$0")/.."

NS=aps
GW="${GW:-http://127.0.0.1:8081}"
REPS="${REPS:-3}"
DURACAO="${DURACAO:-30}"
AQUECIMENTO="${AQUECIMENTO:-5}"
DEGRAUS="${DEGRAUS:-1,2,4,8,16,32,64,128,256}"
PY="${PYTHON:-python}"
export PYTHONIOENCODING=utf-8
SAIDA="resultados/base/$(date +%Y%m%d-%H%M)"
APIS=(air-quality-api flooding-api thermal-inversion-api)
AR="$GW/air-quality/api/v1/air-quality"
POST="$AR/particulate"
CONSULTA="$AR/areas/CENTRO/average?hours=24"

restaurar() {
  echo ">> devolvendo o cluster ao normal (2 réplicas e o HPA)"
  for d in "${APIS[@]}"; do kubectl scale deployment "$d" -n "$NS" --replicas=2 >/dev/null; done
  kubectl apply -f k8s/40-hpa.yaml >/dev/null
}
trap restaurar EXIT

mkdir -p "$SAIDA/descartado"
echo ">> resultados em $SAIDA"

# 1. Uma réplica de cada serviço. O HPA desfaria a escala manual: sai antes.
kubectl delete hpa --all -n "$NS" --ignore-not-found
for d in "${APIS[@]}"; do kubectl scale deployment "$d" -n "$NS" --replicas=1; done
for d in "${APIS[@]}"; do kubectl rollout status deployment "$d" -n "$NS" --timeout=120s; done
sleep 15   # espera os pods que estão saindo terminarem (preStop) e o gateway atualizar os destinos

# 2. Dados da área CENTRO nas três tabelas da média (a consulta precisa de leituras nas últimas 24 h)
echo ">> semeando a área CENTRO (particulado, gases e ambiente)"
"$PY" carga/loadgen.py "$AR/particulate" -X POST -c 2 -d 4 --aquecimento 0 --saida "$SAIDA/descartado/semente-particulado" \
  --corpo '{"stationId":"EST-{{int:1:5}}","sensorId":"SEN-PM-1","areaId":"CENTRO","pm25":{{num:5:40}},"pm10":{{num:10:70}}}' >/dev/null
"$PY" carga/loadgen.py "$AR/gases" -X POST -c 2 -d 4 --aquecimento 0 --saida "$SAIDA/descartado/semente-gases" \
  --corpo '{"stationId":"EST-{{int:1:5}}","sensorId":"SEN-GAS-1","areaId":"CENTRO","co2":{{num:380:900}},"tvoc":{{num:50:600}}}' >/dev/null
"$PY" carga/loadgen.py "$AR/environment" -X POST -c 2 -d 4 --aquecimento 0 --saida "$SAIDA/descartado/semente-ambiente" \
  --corpo '{"stationId":"EST-{{int:1:5}}","sensorId":"SEN-AMB-1","areaId":"CENTRO","temperatureC":{{num:12:34}},"humidityPercent":{{num:30:90}}}' >/dev/null

# 3. Estado do cluster durante a medição
{
  echo "# $(date '+%d/%m/%Y %H:%M:%S')"
  kubectl get deploy,hpa -n "$NS" -o wide 2>&1
  echo
  kubectl get pods -n "$NS" -o wide
  echo
  kubectl get nodes -o wide
  echo
  echo "# leituras da área CENTRO usadas pela consulta"
  kubectl exec -n "$NS" postgres-0 -- sh -c 'psql -U "$POSTGRES_USER" -d air_quality -At -c "
    SELECT '"'"'particulate'"'"', count(*) FROM particulate_readings WHERE area_id = '"'"'CENTRO'"'"'
    UNION ALL SELECT '"'"'gases'"'"', count(*) FROM gas_readings WHERE area_id = '"'"'CENTRO'"'"'
    UNION ALL SELECT '"'"'environment'"'"', count(*) FROM environment_readings WHERE area_id = '"'"'CENTRO'"'"'"'
} > "$SAIDA/estado-do-cluster.txt"
cat "$SAIDA/estado-do-cluster.txt"

# 4. Aquecimento DESCARTADO: na 1ª medição o .NET ainda compila o caminho da requisição e os pools de
#    conexão e o cache do Postgres estão frios.
echo ">> aquecimento (descartado): 20 s em cada rota"
"$PY" carga/loadgen.py "$POST" -X POST --corpo carga -c 8 -d 20 --aquecimento 0 --saida "$SAIDA/descartado/aquecimento-ingestao" >/dev/null
"$PY" carga/loadgen.py "$CONSULTA" -c 8 -d 20 --aquecimento 0 --saida "$SAIDA/descartado/aquecimento-consulta" >/dev/null
sleep 15

# 5. Degraus, REPS vezes cada rota, alternando as rotas entre as repetições
for rep in $(seq 1 "$REPS"); do
  echo; echo "================ repetição $rep/$REPS: ingestão ================"
  "$PY" carga/loadgen.py "$POST" -X POST --corpo carga \
    --degraus "$DEGRAUS" --duracao-degrau "$DURACAO" --aquecimento "$AQUECIMENTO" --timeout 5 \
    --top --top-intervalo 5 --saida "$SAIDA/ingestao-rep$rep"
  sleep 20   # deixa a CPU baixar e o metrics-server atualizar antes da próxima rodada
  echo; echo "================ repetição $rep/$REPS: consulta ================"
  "$PY" carga/loadgen.py "$CONSULTA" \
    --degraus "$DEGRAUS" --duracao-degrau "$DURACAO" --aquecimento "$AQUECIMENTO" --timeout 5 \
    --top --top-intervalo 5 --saida "$SAIDA/consulta-rep$rep"
  sleep 20
done

# 6. Tabelas e gráficos
"$PY" carga/graficos.py "$SAIDA"
echo; echo ">> pronto: $SAIDA (tabela-*.md, grafico-*.png, linha-de-base.json e os arquivos brutos)"
