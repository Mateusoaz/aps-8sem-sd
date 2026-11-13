#!/usr/bin/env bash
# Verificação rápida da aplicação no cluster, sempre PELO GATEWAY (http://localhost:8081).
# Confere: readiness das 3 APIs, POST e consulta, divisão das requisições entre os pods (X-Pod),
# 404 sem o prefixo do serviço, pods por nó e métricas (kubectl top).
set -uo pipefail
GW="${GW:-http://127.0.0.1:8081}"
NS=aps
falhas=0
ok()   { printf '  \033[32mOK\033[0m   %s\n' "$1"; }
erro() { printf '  \033[31mERRO\033[0m %s\n' "$1"; falhas=$((falhas + 1)); }
status() { curl -s -o /dev/null -w '%{http_code}' "$@"; }

verificar() {
  local nome="$1" post="$2" consulta="$3" json="$4"
  local base="$GW/$nome" api="$GW/$nome/api/v1/$nome" s
  echo "== $nome"
  s=$(status "$base/health/ready");  [ "$s" = 200 ] && ok "readiness 200" || erro "readiness -> $s"
  s=$(status -X POST "$api/$post" -H 'Content-Type: application/json' -d "$json")
  [ "$s" = 201 ] && ok "POST /$post -> 201" || erro "POST /$post -> $s"
  s=$(status "$api/$consulta");      [ "$s" = 200 ] && ok "GET /$consulta -> 200" || erro "GET /$consulta -> $s"
  local pods
  pods=$(for _ in $(seq 20); do curl -s -o /dev/null -D - "$base/health/live" | tr -d '\r' | awk -F': ' 'tolower($1)=="x-pod"{print $2}'; done | sort | uniq -c)
  [ "$(echo "$pods" | wc -l)" -ge 2 ] && ok "20 requisições divididas entre os pods:" || erro "20 requisições caíram num pod só:"
  echo "$pods" | sed 's/^/       /'
}

verificar air-quality particulate "areas/VERIF/average?hours=24" \
  '{"stationId":"EST-VERIF","sensorId":"SEN-PM-01","areaId":"VERIF","pm25":12.5,"pm10":20}'
verificar flooding water-level "monitoring-points/PT-VERIF/latest" \
  '{"monitoringPointId":"PT-VERIF","sensorId":"SEN-N-01","waterLevelCm":120}'
verificar thermal-inversion temperature-profile "areas/VERIF/thermal-profile?hours=24" \
  '{"stationId":"EST-VERIF","areaId":"VERIF","surfaceSensorId":"S1","upperSensorId":"S2","surfaceTemperatureC":15,"upperTemperatureC":12}'

echo "== Sem o prefixo do serviço"
s=$(status "$GW/api/v1/flooding/water-level")
[ "$s" = 404 ] && ok "GET /api/v1/flooding/water-level (sem /flooding) -> 404" || erro "sem prefixo -> $s (esperado 404)"

echo "== Pods por nó"
kubectl get pods -n "$NS" -o custom-columns='POD:.metadata.name,NO:.spec.nodeName,PRONTO:.status.containerStatuses[0].ready' | sed 's/^/       /'

echo "== Métricas (metrics-server)"
if top=$(kubectl top pod -n "$NS" 2>/dev/null) && [ -n "$top" ]; then
  ok "kubectl top pod responde"; echo "$top" | sed 's/^/       /'
else
  erro "kubectl top pod ainda sem dados (espere ~1 min depois de subir)"
fi

echo
[ "$falhas" -eq 0 ] && echo "Tudo certo." || echo "$falhas verificação(ões) falharam."
exit "$falhas"
