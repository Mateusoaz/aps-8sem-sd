# Experimento: rolling-sem-prestop

Data: 2026-11-06T11:09:06 · comando: `carga/experimento.py rolling-sem-prestop --rapido --sem-janela` · **modo rápido (durações reduzidas)**

## Hipótese (sugerida, revise antes de entregar)

Sem o preStop, o pod antigo recebe o SIGTERM enquanto o gateway ainda lhe manda requisições: aparecem algumas falhas (502/504) a cada pod trocado.

## Procedimento

- **rolling update sem preStop:** `POST /api/v1/air-quality/particulate`, 32 trabalhadores em 2 gerador(es), 60 s, 5 s de aquecimento descartados

## Resultados

### 5.3 Resiliência e 5.4 Rolling update

| Cenário | Requisições | Falhas | Tempo até pod substituto pronto | Tempo até patamar normal | Versões vistas |
|---|---:|---:|---:|---:|---|
| rolling update (sem preStop) | 9424 | 160 | — | 1,0 s | 1.1.0, 1.2.0 (5 s com as duas) |
| rollout undo (sem preStop) | 10934 | 312 | — | 0,5 s | 1.1.0, 1.2.0 (8 s com as duas) |

rolling update: começou em t = 7,0 s, levou 15,5 s; erros: {'http_502': 72, 'timeout': 88}

rollout undo: começou em t = 32,5 s, levou 15,2 s; erros: {'http_502': 278, 'timeout': 34}

Critério de "patamar normal": numa janela de 5 s, vazão média ≥ 85% e mediana do p95 ≤ 1,5× os valores (medianas) dos segundos anteriores à ação.

## Evidências (nesta pasta)

- `graficos/`: um gráfico por medida, linha do tempo com os eventos marcados
- `eventos.csv`: tudo o que o Kubernetes fez, com horário (pods criados, prontos, removidos; decisões do HPA; ações)
- `replicas.csv`, `hpa.csv`: réplicas prontas e estado do HPA a cada segundo
- `*-requisicoes.csv.gz`, `*-segundos.csv`, `*-resumo.json`: arquivos brutos de cada gerador

## Análise crítica (escrever)

A hipótese se confirmou? Se não, por quê? Qual recurso limitou? O que mudaria o resultado?
