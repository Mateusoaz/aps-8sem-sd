#!/usr/bin/env bash
# Constrói as 4 imagens com a mesma tag e as importa nos nós do cluster k3d.
#   ./scripts/k8s-build.sh          -> tag 1.1.0 (a dos manifestos)
#   ./scripts/k8s-build.sh 1.2.0    -> outra versão, para o rolling update:
#        kubectl set image deployment/air-quality-api -n aps api=aps-sd/air-quality-api:1.2.0
#
# O cluster NÃO enxerga as imagens do Docker da máquina: cada nó tem o próprio depósito.
# Por isso o "k3d image import" depois do build.
set -euo pipefail
cd "$(dirname "$0")/.."

VERSION="${1:-1.1.0}"
CLUSTER="${CLUSTER:-aps}"

declare -A IMAGES=(
  [air-quality-api]=src/AirQuality.Api
  [flooding-api]=src/Flooding.Api
  [thermal-inversion-api]=src/ThermalInversion.Api
  [web-client]=src/WebClient
)

tags=()
for name in "${!IMAGES[@]}"; do
  echo ">> docker build aps-sd/$name:$VERSION"
  docker build --quiet --build-arg APP_VERSION="$VERSION" -t "aps-sd/$name:$VERSION" "${IMAGES[$name]}"
  tags+=("aps-sd/$name:$VERSION")
done

echo ">> k3d image import (${#tags[@]} imagens) no cluster $CLUSTER"
k3d image import -c "$CLUSTER" "${tags[@]}"
