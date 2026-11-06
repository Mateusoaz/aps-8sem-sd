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
SECRET=aps-credenciais

# 1. Cluster: 1 servidor (plano de controle) + 2 agentes = 3 nós, cada um um contêiner Docker.
#    A porta 8081 da máquina chega à porta 80 do cluster, onde o Traefik (Ingress) escuta.
if ! k3d cluster list "$CLUSTER" >/dev/null 2>&1; then
  k3d cluster create "$CLUSTER" --agents 2 -p "8081:80@loadbalancer"
fi
kubectl config use-context "k3d-$CLUSTER" >/dev/null
kubectl wait --for=condition=Ready nodes --all --timeout=120s

# 2. Imagens com tag fixa, importadas nos nós
./scripts/k8s-build.sh 1.1.0

# 3. Namespace e Secret. O Secret vem do .env (fora do Git); o repositório só leva o modelo.
[ -f .env ] || { cp .env.example .env; echo ">> .env criado a partir do .env.example"; }
for key in POSTGRES_USER POSTGRES_PASSWORD RABBITMQ_USER RABBITMQ_PASSWORD; do
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
kubectl rollout status statefulset/rabbitmq -n "$NS" --timeout=240s
for d in redis air-quality-api flooding-api thermal-inversion-api web-client; do
  kubectl rollout status deployment/"$d" -n "$NS" --timeout=180s
done

kubectl get all,ingress,pvc,hpa -n "$NS" -o wide
echo
echo "Pronto. Cliente web: http://localhost:8081/"
echo "Swagger: http://localhost:8081/api/v1/air-quality/swagger  (flooding, thermal-inversion)"
echo "Verificação: ./scripts/k8s-verificar.sh"
