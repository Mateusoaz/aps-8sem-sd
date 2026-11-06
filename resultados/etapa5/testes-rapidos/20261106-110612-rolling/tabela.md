# Experimento: rolling

Data: 2026-11-06T11:06:12 · comando: `carga/experimento.py rolling --rapido --sem-janela` · **modo rápido (durações reduzidas)**

## Hipótese (sugerida, revise antes de entregar)

Com maxUnavailable 0 e preStop de 5 s, a troca de versão não gera falhas e as duas versões atendem ao mesmo tempo durante a transição.

## Procedimento

- **rolling update:** `POST /api/v1/air-quality/particulate`, 32 trabalhadores em 2 gerador(es), 60 s, 5 s de aquecimento descartados

## Resultados

### 5.3 Resiliência e 5.4 Rolling update

| Cenário | Requisições | Falhas | Tempo até pod substituto pronto | Tempo até patamar normal | Versões vistas |
|---|---:|---:|---:|---:|---|
| rolling update | 18931 | 0 | — | 1,0 s | 1.1.0, 1.2.0 (13 s com as duas) |
| rollout undo | 11773 | 0 | — | 0,3 s | 1.1.0, 1.2.0 (12 s com as duas) |

rolling update: começou em t = 7,0 s, levou 15,7 s; erros: nenhum

rollout undo: começou em t = 32,7 s, levou 16,2 s; erros: nenhum

Critério de "patamar normal": numa janela de 5 s, vazão média ≥ 85% e mediana do p95 ≤ 1,5× os valores (medianas) dos segundos anteriores à ação.

## Evidências (nesta pasta)

- `graficos/`: um gráfico por medida, linha do tempo com os eventos marcados
- `eventos.csv`: tudo o que o Kubernetes fez, com horário (pods criados, prontos, removidos; decisões do HPA; ações)
- `replicas.csv`, `hpa.csv`: réplicas prontas e estado do HPA a cada segundo
- `*-requisicoes.csv.gz`, `*-segundos.csv`, `*-resumo.json`: arquivos brutos de cada gerador

## Análise crítica (escrever)

A hipótese se confirmou? Se não, por quê? Qual recurso limitou? O que mudaria o resultado?
