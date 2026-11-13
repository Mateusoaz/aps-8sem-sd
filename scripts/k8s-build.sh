#!/usr/bin/env bash
# Constrói as 3 imagens das APIs com a mesma tag e as importa nos nós do cluster k3d.
#   bash scripts/k8s-build.sh          -> tag 1.1.0 (a dos manifestos)
#   bash scripts/k8s-build.sh 1.2.0    -> outra versão, para o rolling update:
#        kubectl set image deployment/air-quality-api -n aps api=aps-sd/air-quality-api:1.2.0
#
# O cluster NÃO enxerga as imagens do Docker da máquina: cada nó tem o próprio depósito.
# Por isso o "k3d image import" depois do build.
set -euo pipefail
cd "$(dirname "$0")/.."

VERSAO="${1:-1.1.0}"
CLUSTER="${CLUSTER:-aps}"

declare -A IMAGENS=(
  [air-quality-api]=src/AirQuality.Api
  [flooding-api]=src/Flooding.Api
  [thermal-inversion-api]=src/ThermalInversion.Api
)

TAGS=()
for nome in "${!IMAGENS[@]}"; do
  tag="aps-sd/$nome:$VERSAO"
  echo ">> docker build $tag"
  docker build --quiet --build-arg APP_VERSION="$VERSAO" -t "$tag" "${IMAGENS[$nome]}"
  TAGS+=("$tag")
done

echo ">> k3d image import (${#TAGS[@]} imagens) no cluster $CLUSTER"
k3d image import -c "$CLUSTER" "${TAGS[@]}"
