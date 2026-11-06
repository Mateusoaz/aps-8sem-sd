# Experimento: no-drenado

Data: 2026-11-06T11:32:20 · comando: `carga/experimento.py no-drenado --rapido --sem-janela` · **modo rápido (durações reduzidas)**

## Hipótese (sugerida, revise antes de entregar)

O drain despeja os pods com aviso (encerramento gracioso + preStop): poucas ou nenhuma falha; os pods são recriados nos outros nós. Com a outra réplica atendendo, o serviço não para.

## Procedimento

- **nó drenado:** `POST /api/v1/air-quality/particulate`, 32 trabalhadores em 2 gerador(es), 40 s, 5 s de aquecimento descartados

## Resultados

### 5.3 Resiliência e 5.4 Rolling update

| Cenário | Requisições | Falhas | Tempo até pod substituto pronto | Tempo até patamar normal | Versões vistas |
|---|---:|---:|---:|---:|---|
| nó drenado: k3d-aps-agent-1 | 15620 | 0 | 8,9 s | — | — |

Vazão normal antes da ação: 500 req/s · p95 normal: 114,1 ms · falhas depois da ação: 0 · erros por tipo: nenhum
Segundos com pelo menos uma falha: 0 · segundos sem nenhuma resposta OK (serviço fora do ar): 0
Todos os substitutos prontos em: 8,9 s

Pods retirados:

- air-quality-api-54f5f47fb-6vnd9 (k3d-aps-agent-1, 11:33:37)
- flooding-api-68c88dcb6b-kh26w (k3d-aps-agent-1, 11:33:37)
- thermal-inversion-api-7dd5b5855b-ldmcv (k3d-aps-agent-1, 11:33:37)

Pods criados:

- air-quality-api-54f5f47fb-wz222 -> k3d-aps-agent-0 pronto às 11:33:45

Critério de "patamar normal": numa janela de 5 s, vazão média ≥ 85% e mediana do p95 ≤ 1,5× os valores (medianas) dos segundos anteriores à ação.

## Evidências (nesta pasta)

- `graficos/`: um gráfico por medida, linha do tempo com os eventos marcados
- `eventos.csv`: tudo o que o Kubernetes fez, com horário (pods criados, prontos, removidos; decisões do HPA; ações)
- `replicas.csv`, `hpa.csv`: réplicas prontas e estado do HPA a cada segundo
- `*-requisicoes.csv.gz`, `*-segundos.csv`, `*-resumo.json`: arquivos brutos de cada gerador

## Análise crítica (escrever)

A hipótese se confirmou? Se não, por quê? Qual recurso limitou? O que mudaria o resultado?
