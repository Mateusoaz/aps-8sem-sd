# Experimento: no-drenado

Data: 2026-11-06T11:28:10 · comando: `carga/experimento.py no-drenado --rapido --sem-janela` · **modo rápido (durações reduzidas)**

## Hipótese (sugerida, revise antes de entregar)

O drain despeja os pods com aviso (encerramento gracioso + preStop): poucas ou nenhuma falha; os pods são recriados nos outros nós. Com a outra réplica atendendo, o serviço não para.

## Procedimento

- **nó drenado:** `POST /api/v1/air-quality/particulate`, 32 trabalhadores em 2 gerador(es), 40 s, 5 s de aquecimento descartados

## Resultados

### 5.3 Resiliência e 5.4 Rolling update

| Cenário | Requisições | Falhas | Tempo até pod substituto pronto | Tempo até patamar normal | Versões vistas |
|---|---:|---:|---:|---:|---|
| nó drenado: k3d-aps-agent-1 | 79082 | 67853 | 24,6 s | — | — |

Vazão normal antes da ação: 755 req/s · p95 normal: 67,7 ms · falhas depois da ação: 67853 · erros por tipo: {'http_503': 67853}
Segundos com pelo menos uma falha: 13 · segundos sem nenhuma resposta OK (serviço fora do ar): 11
Todos os substitutos prontos em: 34,0 s

Pods retirados:

- air-quality-api-56554d84f6-248jl (k3d-aps-agent-1, 11:29:30)
- flooding-api-5d857877db-cw7dv (k3d-aps-agent-1, 11:29:30)
- redis-55d4876657-lh28r (k3d-aps-agent-1, 11:29:30)
- thermal-inversion-api-78f959d969-jmtkj (k3d-aps-agent-1, 11:29:30)
- web-client-78787d6459-m2gwg (k3d-aps-agent-1, 11:29:30)
- air-quality-api-56554d84f6-brw5k (k3d-aps-agent-1, 11:29:57)

Pods criados:

- air-quality-api-56554d84f6-4qh59 -> k3d-aps-agent-0 pronto às 11:29:54
- air-quality-api-56554d84f6-gq7db -> k3d-aps-server-0 pronto às 11:30:03

Critério de "patamar normal": numa janela de 5 s, vazão média ≥ 85% e mediana do p95 ≤ 1,5× os valores (medianas) dos segundos anteriores à ação.

## Evidências (nesta pasta)

- `graficos/`: um gráfico por medida, linha do tempo com os eventos marcados
- `eventos.csv`: tudo o que o Kubernetes fez, com horário (pods criados, prontos, removidos; decisões do HPA; ações)
- `replicas.csv`, `hpa.csv`: réplicas prontas e estado do HPA a cada segundo
- `*-requisicoes.csv.gz`, `*-segundos.csv`, `*-resumo.json`: arquivos brutos de cada gerador

## Análise crítica (escrever)

A hipótese se confirmou? Se não, por quê? Qual recurso limitou? O que mudaria o resultado?
