# Experimento: escala

Data: 2026-11-05T23:43:46 · comando: `carga/experimento.py escala --rapido --sem-janela` · **modo rápido (durações reduzidas)**

## Hipótese (sugerida, revise antes de entregar)

Com N réplicas a vazão cresce quase N vezes enquanto o gargalo é a CPU de cada pod (500m); a partir de algum N o ganho cai, porque banco, gateway e a CPU da máquina são compartilhados.

## Procedimento

- **1 réplica:** `POST /api/v1/air-quality/particulate`, 128 trabalhadores em 4 gerador(es), 20 s, 10 s de aquecimento descartados
- **2 réplicas:** `POST /api/v1/air-quality/particulate`, 128 trabalhadores em 4 gerador(es), 20 s, 10 s de aquecimento descartados
- **4 réplicas:** `POST /api/v1/air-quality/particulate`, 128 trabalhadores em 4 gerador(es), 20 s, 10 s de aquecimento descartados

## Resultados

### 5.1 Escalabilidade horizontal manual — rota: `POST /api/v1/air-quality/particulate` · trabalhadores: 128 · duração: 20 s

| Réplicas | Vazão (req/s) | p50 (ms) | p95 (ms) | Erros (%) | Ganho medido | Ganho ideal | s estimado (Amdahl) | CPU API (m) | CPU banco (m) |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 1 | 675,3 | 190,5 | 254,4 | 0,00 | 1,00 | 1 | — | 228 | 207 |
| 2 | 456,2 | 90,3 | 623,3 | 0,00 | 0,68 | 2 | 1,961 | 289 | 88 |
| 4 | 923,5 | 47,6 | 530,0 | 0,00 | 1,37 | 4 | 0,642 | 803 | 598 |

**Lei de Amdahl:** Ganho(N) = 1 / (s + (1 − s)/N). Fração serial estimada s ≈ 1,302 (média das estimativas) → ganho máximo teórico ≈ 0,8×. s representa o que não se divide entre as réplicas: o banco único, a fila, o gateway e a CPU da máquina.

## Evidências (nesta pasta)

- `graficos/`: um gráfico por medida, comparação entre cenários
- `eventos.csv`: tudo o que o Kubernetes fez, com horário (pods criados, prontos, removidos; decisões do HPA; ações)
- `replicas.csv`, `hpa.csv`: réplicas prontas e estado do HPA a cada segundo
- `*-requisicoes.csv.gz`, `*-segundos.csv`, `*-resumo.json`: arquivos brutos de cada gerador

## Análise crítica (escrever)

A hipótese se confirmou? Se não, por quê? Qual recurso limitou? O que mudaria o resultado?
