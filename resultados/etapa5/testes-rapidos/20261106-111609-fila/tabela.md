# Experimento: fila

Data: 2026-11-06T11:16:09 · comando: `carga/experimento.py fila --rapido --sem-janela` · **modo rápido (durações reduzidas)**

## Hipótese (sugerida, revise antes de entregar)

Com a fila, o POST só grava e publica: responde mais rápido. Sem a fila, cada POST também avalia a regra de alerta no banco: latência maior e vazão menor, mas sem atraso nos alertas.

## Procedimento

- **fila (assíncrono):** `POST /api/v1/air-quality/particulate`, 32 trabalhadores em 2 gerador(es), 20 s, 10 s de aquecimento descartados
- **sem fila (síncrono):** `POST /api/v1/air-quality/particulate`, 32 trabalhadores em 2 gerador(es), 20 s, 10 s de aquecimento descartados

## Resultados

### 5.5 Processamento assíncrono (fila) — rota: `POST /api/v1/air-quality/particulate` · trabalhadores: 32

| Cenário | Vazão (req/s) | p50 (ms) | p95 (ms) | Erros (%) | CPU do banco (m) | CPU da API (m) | Cache HIT (%) | Fila ao fim |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| fila (assíncrono) | 817,6 | 39,5 | 93,4 | 0,00 | 10 | 517 | — | 11396 mensagens pendentes ao fim da carga, 22 s para esvaziar |
| sem fila (síncrono) | 473,6 | 62,6 | 190,8 | 0,00 | 111 | 374 | — | 0 mensagens pendentes ao fim da carga, 1 s para esvaziar |

## Evidências (nesta pasta)

- `graficos/`: um gráfico por medida, comparação entre cenários
- `eventos.csv`: tudo o que o Kubernetes fez, com horário (pods criados, prontos, removidos; decisões do HPA; ações)
- `replicas.csv`, `hpa.csv`: réplicas prontas e estado do HPA a cada segundo
- `*-requisicoes.csv.gz`, `*-segundos.csv`, `*-resumo.json`: arquivos brutos de cada gerador

## Análise crítica (escrever)

A hipótese se confirmou? Se não, por quê? Qual recurso limitou? O que mudaria o resultado?
