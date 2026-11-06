# Experimento: no-drenado

Data: 2026-11-06T11:04:06 · comando: `carga/experimento.py no-drenado --rapido --sem-janela` · **modo rápido (durações reduzidas)**

## Hipótese (sugerida, revise antes de entregar)

O drain despeja os pods com aviso (encerramento gracioso + preStop): poucas ou nenhuma falha; os pods são recriados nos outros nós. Com a outra réplica atendendo, o serviço não para.

## Procedimento

- **nó drenado:** `POST /api/v1/air-quality/particulate`, 32 trabalhadores em 2 gerador(es), 40 s, 5 s de aquecimento descartados

## Resultados

### 5.3 Resiliência e 5.4 Rolling update

| Cenário | Requisições | Falhas | Tempo até pod substituto pronto | Tempo até patamar normal | Versões vistas |
|---|---:|---:|---:|---:|---|
| nó drenado: k3d-aps-agent-0 | 107081 | 93614 | 15,6 s | — | — |

Vazão normal antes da ação: 1.030 req/s · p95 normal: 70,8 ms · falhas depois da ação: 93614 · erros por tipo: {'conexao_encerrada': 93614}
Todos os substitutos prontos em: 15,6 s

Pods retirados:

- air-quality-api-7c846d4dd8-28d5p (k3d-aps-agent-0, 11:05:25)
- flooding-api-75f75d59d5-w44ct (k3d-aps-agent-0, 11:05:25)
- rabbitmq-0 (k3d-aps-agent-0, 11:05:25)
- thermal-inversion-api-79f68869c9-94xmb (k3d-aps-agent-0, 11:05:25)
- web-client-78787d6459-7bxqc (k3d-aps-agent-0, 11:05:25)

Pods criados:

- air-quality-api-7c846d4dd8-tz89f -> k3d-aps-agent-1 pronto às 11:05:39

Critério de "patamar normal": numa janela de 5 s, vazão média ≥ 85% e mediana do p95 ≤ 1,5× os valores (medianas) dos segundos anteriores à ação.

## Evidências (nesta pasta)

- `graficos/`: um gráfico por medida, linha do tempo com os eventos marcados
- `eventos.csv`: tudo o que o Kubernetes fez, com horário (pods criados, prontos, removidos; decisões do HPA; ações)
- `replicas.csv`, `hpa.csv`: réplicas prontas e estado do HPA a cada segundo
- `*-requisicoes.csv.gz`, `*-segundos.csv`, `*-resumo.json`: arquivos brutos de cada gerador

## Análise crítica (escrever)

A hipótese se confirmou? Se não, por quê? Qual recurso limitou? O que mudaria o resultado?
