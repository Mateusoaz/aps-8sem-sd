#!/usr/bin/env bash
# Linha de base da Etapa 4: 3 execuções de cada rota, com 1 réplica de cada serviço e sem HPA.
# Grava em resultados/base/ os arquivos do gerador e, a cada 5 s, a CPU dos pods.
# Uso (na raiz do repositório, no Git Bash): bash carga/linha_base.sh
# Depois, para voltar ao normal: kubectl apply -f k8s/
set -u

BASE=http://localhost:8081/air-quality/api/v1/air-quality
DEGRAUS=1,2,4,8,16,32,64,128,256

# Cada execução começa com todos os pods prontos; senão herda trabalho da anterior.
espera_sistema() {
  while true; do
    pendentes=$(kubectl get pods -n aps --no-headers 2>/dev/null | grep -vc '1/1 *Running')
    [ "$pendentes" = 0 ] && break
    echo "$(date +%T) aguardando: pods fora de 1/1=$pendentes"
    sleep 10
  done
  sleep 30
}

amostra() {
  while true; do
    echo "=== $(date +%T)"
    kubectl top pod -n aps --no-headers 2>&1
    sleep 5
  done
}

executa() {  # nome-do-arquivo  argumentos-do-gerador...
  nome=$1; shift
  espera_sistema
  echo "$(date +%T) início de $nome"
  kubectl get pods -n aps -o wide --no-headers > "resultados/base/pods-antes-$nome.txt"
  amostra > "resultados/base/top-$nome.txt" &
  amostrador=$!
  python carga/loadgen.py "$@" --degraus $DEGRAUS -d 30 --aquecimento 5 --prefixo "base/$nome" | tail -18
  kill $amostrador 2>/dev/null
  kubectl get pods -n aps -o wide --no-headers > "resultados/base/pods-depois-$nome.txt"
}

# 1 réplica de cada serviço e o HPA removido (ele criaria réplicas no meio do teste)
kubectl delete hpa air-quality-api -n aps --ignore-not-found
kubectl scale deployment air-quality-api flooding-api thermal-inversion-api -n aps --replicas=1
kubectl rollout status deployment/air-quality-api -n aps --timeout=300s

mkdir -p resultados/base
for n in 1 2 3; do
  executa "post-exec$n" "$BASE/particulate" --payload ar
done
for n in 1 2 3; do
  executa "get-exec$n" "$BASE/areas/CENTRO/average?hours=24"
done
echo "$(date +%T) fim"
