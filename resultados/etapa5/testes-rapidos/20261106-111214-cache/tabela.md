# Experimento: cache

Data: 2026-11-06T11:12:14 · comando: `carga/experimento.py cache --rapido --sem-janela` · **modo rápido (durações reduzidas)**

## Hipótese (sugerida, revise antes de entregar)

Com o cache, quase todas as consultas são respondidas pelo Redis: a vazão sobe, a latência cai e a CPU do banco fica perto de zero. Sem cache, o banco vira o gargalo.

## Procedimento

- **com cache:** `GET /api/v1/air-quality/areas/CENTRO/average?hours=24`, 32 trabalhadores em 2 gerador(es), 20 s, 10 s de aquecimento descartados
- **sem cache:** `GET /api/v1/air-quality/areas/CENTRO/average?hours=24`, 32 trabalhadores em 2 gerador(es), 20 s, 10 s de aquecimento descartados

## Resultados

### 5.5 Cache — rota: `GET /api/v1/air-quality/areas/CENTRO/average?hours=24` · trabalhadores: 32

| Cenário | Vazão (req/s) | p50 (ms) | p95 (ms) | Erros (%) | CPU do banco (m) | CPU da API (m) | Cache HIT (%) | Fila ao fim |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| com cache | 1.368,1 | 6,3 | 88,0 | 0,00 | 413 | 844 | 99,8 | — |
| sem cache | 10,7 | 2.078,1 | 4.974,5 | 2,73 | 1.925 | 187 | 0,0 | — |

## Evidências (nesta pasta)

- `graficos/`: um gráfico por medida, comparação entre cenários
- `eventos.csv`: tudo o que o Kubernetes fez, com horário (pods criados, prontos, removidos; decisões do HPA; ações)
- `replicas.csv`, `hpa.csv`: réplicas prontas e estado do HPA a cada segundo
- `*-requisicoes.csv.gz`, `*-segundos.csv`, `*-resumo.json`: arquivos brutos de cada gerador

## Análise crítica (escrever)

A hipótese se confirmou? Se não, por quê? Qual recurso limitou? O que mudaria o resultado?
