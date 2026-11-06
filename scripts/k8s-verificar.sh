#!/usr/bin/env bash
# Verificação rápida da aplicação no cluster, sempre PELO GATEWAY (http://localhost:8081).
# Confere: cliente web, readiness das 3 APIs, POST com alerta via fila, cache (MISS -> HIT),
# distribuição das requisições entre os pods (X-Pod) e métricas (kubectl top).
set -uo pipefail

GW="${GW:-http://localhost:8081}"
NS=aps
falhas=0

ok()   { printf '  \033[32mOK\033[0m   %s\n' "$*"; }
erro() { printf '  \033[31mERRO\033[0m %s\n' "$*"; falhas=$((falhas + 1)); }
header() { curl -s -o /dev/null -D - "$@" | tr -d '\r'; }
valor() { grep -i "^$1:" | head -1 | cut -d' ' -f2-; }

echo "== Cliente web"
code=$(curl -s -o /dev/null -w '%{http_code}' "$GW/")
[ "$code" = 200 ] && ok "GET / -> 200" || erro "GET / -> $code"

declare -A POST_PATH=(
  [air-quality]="particulate|{\"stationId\":\"EST-VERIF\",\"sensorId\":\"SEN-PM-01\",\"areaId\":\"VERIF\",\"pm25\":12.5,\"pm10\":20}"
  [flooding]="water-level|{\"monitoringPointId\":\"PT-VERIF\",\"sensorId\":\"SEN-N-01\",\"waterLevelCm\":120}"
  [thermal-inversion]="temperature-profile|{\"stationId\":\"EST-VERIF\",\"areaId\":\"VERIF\",\"surfaceSensorId\":\"S1\",\"upperSensorId\":\"S2\",\"surfaceTemperatureC\":15,\"upperTemperatureC\":12}"
)
declare -A QUERY_PATH=(
  [air-quality]="areas/VERIF/average?hours=24"
  [flooding]="monitoring-points/PT-VERIF/latest"
  [thermal-inversion]="areas/VERIF/thermal-profile?hours=24"
)

for svc in air-quality flooding thermal-inversion; do
  base="$GW/api/v1/$svc"
  echo "== $svc"

  body=$(curl -s -w '\n%{http_code}' "$base/health/ready")
  code=${body##*$'\n'}
  [ "$code" = 200 ] && ok "readiness 200: ${body%$'\n'*}" || erro "readiness -> $code: ${body%$'\n'*}"

  IFS='|' read -r path json <<< "${POST_PATH[$svc]}"
  h=$(header -X POST -H 'Content-Type: application/json' -d "$json" "$base/$path")
  code=$(echo "$h" | head -1 | cut -d' ' -f2)
  modo=$(echo "$h" | valor X-Alerta)
  [ "$code" = 201 ] && ok "POST /$path -> 201 (alerta: $modo)" || erro "POST /$path -> $code"
  [ "$modo" = fila ] || erro "alerta não passou pela fila (X-Alerta: $modo)"

  c1=$(header "$base/${QUERY_PATH[$svc]}" | valor X-Cache)
  c2=$(header "$base/${QUERY_PATH[$svc]}" | valor X-Cache)
  [ "$c2" = HIT ] && ok "cache: 1ª $c1, 2ª $c2" || erro "cache: 1ª $c1, 2ª $c2 (esperado HIT na 2ª)"

  pods=$(for i in $(seq 10); do header "$base/health/live" | valor X-Pod; done | sort | uniq -c)
  n=$(echo "$pods" | wc -l)
  [ "$n" -ge 2 ] && ok "10 requisições em $n pods:" || erro "10 requisições caíram em $n pod(s):"
  echo "$pods" | sed 's/^/         /'
done

echo "== Métricas (metrics-server)"
if kubectl top pod -n "$NS" >/dev/null 2>&1; then
  ok "kubectl top pod responde"; kubectl top pod -n "$NS" | sed 's/^/         /'
else
  erro "kubectl top pod ainda sem dados (espere ~1 min depois de subir)"
fi

echo
[ "$falhas" -eq 0 ] && echo "Tudo certo." || echo "$falhas verificação(ões) falharam."
exit "$falhas"
