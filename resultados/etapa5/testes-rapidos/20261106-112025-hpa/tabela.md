# Experimento: hpa

Data: 2026-11-06T11:20:25 · comando: `carga/experimento.py hpa --rapido --sem-janela` · **modo rápido (durações reduzidas)**

## Hipótese (sugerida, revise antes de entregar)

Com a carga em rampa, o HPA aumenta as réplicas em alguns ciclos de 15 s; o p95 sobe enquanto os pods novos não estão prontos e volta ao patamar quando eles entram no Service. A redução só começa ~5 min depois.

## Procedimento

- **rampa com HPA:** `POST /api/v1/air-quality/particulate`, 128 trabalhadores em 4 gerador(es), 100 s, rampa de 40 s, 0 s de aquecimento descartados

## Resultados

### 5.2 HPA — linha do tempo

| Evento | Hora | t (s) | Réplicas | Observação |
|---|---|---:|---:|---|
| Início da carga (rampa) | 11:20:56 | 0,0 | 2 | CPU 21% |
| Primeira decisão de escala (SuccessfulRescale) | 11:21:30 | 34,0 | 2 | 2 -> 4 réplicas (CPU 431%) |
| Novos pods prontos (1/1) | 11:21:36 | 40,4 | 2 | p95 1.460,3 ms |
| Latência p95 de volta ao patamar aceitável (≤ 100 ms por 10 s) | — | — | — |  |
| Fim da carga / início da redução | 11:22:38 | 102,0 | 10 | redução não observada |

Réplicas máximas: 10 · requisições: 85832 · falhas: 0

Decisões do HPA:

- 11:21:30 2 -> 4 réplicas (CPU 431%)
- 11:21:46 4 -> 8 réplicas (CPU 479%)
- 11:22:02 8 -> 10 réplicas (CPU 495%)

## Evidências (nesta pasta)

- `graficos/`: um gráfico por medida, linha do tempo com os eventos marcados
- `eventos.csv`: tudo o que o Kubernetes fez, com horário (pods criados, prontos, removidos; decisões do HPA; ações)
- `replicas.csv`, `hpa.csv`: réplicas prontas e estado do HPA a cada segundo
- `*-requisicoes.csv.gz`, `*-segundos.csv`, `*-resumo.json`: arquivos brutos de cada gerador

## Análise crítica (escrever)

A hipótese se confirmou? Se não, por quê? Qual recurso limitou? O que mudaria o resultado?
