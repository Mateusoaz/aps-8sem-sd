#!/usr/bin/env bash
# Sobe a aplicação inteira no Kubernetes local (k3d), do zero:
#   cluster de 3 nós -> imagens -> namespace + Secret -> manifestos -> espera tudo ficar pronto.
# Pode rodar de novo: o que já existe é mantido ou atualizado.
#
# Requisitos: Docker em execução, kubectl e k3d (v5+). No Windows, rodar no Git Bash.
set -euo pipefail
cd "$(dirname "$0")/.."

CLUSTER="${CLUSTER:-aps}"
NS=aps
SECRET=banco-credenciais

# 1. Cluster: 1 servidor + 2 agentes = 3 nós, cada um um contêiner Docker.
#    O servidor ganha a marca (taint) de plano de controle: fica com o Kubernetes em si e os
#    componentes do sistema (Traefik, CoreDNS, metrics-server), e os pods da aplicação vão para os agentes.
#    A porta 8081 da máquina chega à porta 80 do cluster, onde o Traefik (Ingress) escuta.
if ! k3d cluster list "$CLUSTER" >/dev/null 2>&1; then
  k3d cluster create "$CLUSTER" --agents 2 -p "8081:80@loadbalancer" \
    --k3s-arg "--node-taint=node-role.kubernetes.io/control-plane:NoSchedule@server:0"
fi
kubectl config use-context "k3d-$CLUSTER" >/dev/null
kubectl wait --for=condition=Ready nodes --all --timeout=120s

# 2. Imagens com tag fixa, importadas nos nós
bash scripts/k8s-build.sh 1.1.0

# 3. Namespace e Secret. O Secret vem do .env (fora do Git); o repositório só leva o modelo.
[ -f .env ] || { cp .env.example .env; echo ">> .env criado a partir do .env.example"; }
for key in POSTGRES_USER POSTGRES_PASSWORD; do
  grep -q "^$key=" .env || { echo "ERRO: falta $key no .env (veja o .env.example)"; exit 1; }
done
kubectl apply -f k8s/00-namespace.yaml
# tr -d '\r': um .env salvo no Windows (CRLF) grudaria um \r no fim de cada senha
env_file="$(mktemp)"
tr -d '\r' < .env > "$env_file"
kubectl create secret generic "$SECRET" -n "$NS" --from-env-file="$env_file" \
  --dry-run=client -o yaml | kubectl apply -f -
rm -f "$env_file"

# 4. Todo o resto, em ordem alfabética dos arquivos
kubectl apply -f k8s/

# 5. Espera cada peça ficar pronta
kubectl rollout status statefulset/postgres -n "$NS" --timeout=180s
for d in air-quality-api flooding-api thermal-inversion-api; do
  kubectl rollout status deployment/"$d" -n "$NS" --timeout=180s
done

kubectl get pods -n "$NS" -o wide
echo
echo "Pronto. Swagger: http://localhost:8081/air-quality/swagger  (ou /flooding, /thermal-inversion)"
echo "Verificação: bash scripts/k8s-verificar.sh"
