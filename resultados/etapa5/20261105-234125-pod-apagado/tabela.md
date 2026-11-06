# Experimento: pod-apagado

Data: 2026-11-05T23:41:25 · comando: `carga/experimento.py pod-apagado --rapido --sem-janela` · **modo rápido (durações reduzidas)**

## Hipótese (sugerida, revise antes de entregar)

Falham só as requisições que estavam no pod no instante da exclusão; o ReplicaSet cria o substituto em segundos e a vazão volta quando ele passa na readiness.

## Procedimento

- **pod apagado:** `POST /api/v1/air-quality/particulate`, 32 trabalhadores em 2 gerador(es), 30 s, 5 s de aquecimento descartados

## Resultados

### 5.3 Resiliência e 5.4 Rolling update

| Cenário | Requisições | Falhas | Tempo até pod substituto pronto | Tempo até patamar normal | Versões vistas |
|---|---:|---:|---:|---:|---|
| pod apagado: air-quality-api-7c846d4dd8-7fgsc | 15192 | 0 | 6,7 s | 7,9 s | — |

Vazão normal antes da ação: 570 req/s · p95 normal: 103,7 ms · falhas depois da ação: 0 · erros por tipo: nenhum
Todos os substitutos prontos em: 6,7 s

Pods retirados:

- air-quality-api-7c846d4dd8-7fgsc (k3d-aps-agent-0, 23:42:05)

Pods criados:

- air-quality-api-7c846d4dd8-qf78f -> k3d-aps-agent-0 pronto às 23:42:11

Critério de "patamar normal": numa janela de 5 s, vazão média ≥ 85% e mediana do p95 ≤ 1,5× os valores (medianas) dos segundos anteriores à ação.

## Evidências (nesta pasta)

- `graficos/`: um gráfico por medida, linha do tempo com os eventos marcados
- `eventos.csv`: tudo o que o Kubernetes fez, com horário (pods criados, prontos, removidos; decisões do HPA; ações)
- `replicas.csv`, `hpa.csv`: réplicas prontas e estado do HPA a cada segundo
- `*-requisicoes.csv.gz`, `*-segundos.csv`, `*-resumo.json`: arquivos brutos de cada gerador

## Análise crítica (escrever)

A hipótese se confirmou? Se não, por quê? Qual recurso limitou? O que mudaria o resultado?
