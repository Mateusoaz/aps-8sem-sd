# Experimento: demo

Data: 2026-11-06T11:44:50 · comando: `carga/experimento.py demo --duracao 80 --trabalhadores 32 --sem-janela`

## Hipótese (sugerida, revise antes de entregar)

Demonstração ao vivo: ao escalar, a vazão sobe depois que os pods novos passam na readiness; ao apagar um pod, o ReplicaSet recria outro e quase nada falha; na troca de versão, as duas versões atendem juntas.

## Procedimento

- **demonstração:** `POST /api/v1/air-quality/particulate`, 32 trabalhadores em 2 gerador(es), 80 s, 5 s de aquecimento descartados

## Resultados

### Demonstração ao vivo (seção 6 da ficha)

| Requisições | Falhas | Segundos com falha | Segundos sem resposta OK | Réplicas prontas (mín.–máx.) | Versões que responderam |
|---:|---:|---:|---:|---|---|
| 40950 | 0 | 0 | 1 | 1–3 | 1.1.0 (30664), 1.2.0 (10286) |

Erros por tipo: nenhum

O que o Kubernetes fez com os pods da API, com horário:

- 11:46:33 pod criado: air-quality-api-54f5f47fb-wtkq6 (k3d-aps-agent-0, versão 1.1.0)
- 11:46:33 pod criado: air-quality-api-54f5f47fb-wwmzm (k3d-aps-agent-1, versão 1.1.0)
- 11:46:39 pod pronto: air-quality-api-54f5f47fb-wtkq6 (k3d-aps-agent-0, versão 1.1.0)
- 11:46:39 pod pronto: air-quality-api-54f5f47fb-wwmzm (k3d-aps-agent-1, versão 1.1.0)
- 11:46:53 pod criado: air-quality-api-54f5f47fb-5cplk (k3d-aps-server-0, versão 1.1.0)
- 11:46:53 pod terminando: air-quality-api-54f5f47fb-wrb8w (k3d-aps-server-0, versão 1.1.0)
- 11:46:59 pod pronto: air-quality-api-54f5f47fb-5cplk (k3d-aps-server-0, versão 1.1.0)
- 11:47:00 pod removido: air-quality-api-54f5f47fb-wrb8w (k3d-aps-server-0, versão 1.1.0)
- 11:47:08 pod criado: air-quality-api-c77676687-jx9gr (k3d-aps-agent-1, versão 1.2.0)
- 11:47:14 pod terminando: air-quality-api-54f5f47fb-wwmzm (k3d-aps-agent-1, versão 1.1.0)
- 11:47:14 pod pronto: air-quality-api-c77676687-jx9gr (k3d-aps-agent-1, versão 1.2.0)
- 11:47:14 pod criado: air-quality-api-c77676687-ljhm9 (k3d-aps-agent-1, versão 1.2.0)
- 11:47:18 pod terminando: air-quality-api-54f5f47fb-5cplk (k3d-aps-server-0, versão 1.1.0)
- 11:47:18 pod criado: air-quality-api-c77676687-8zxvz (k3d-aps-server-0, versão 1.2.0)
- 11:47:18 pod pronto: air-quality-api-c77676687-ljhm9 (k3d-aps-agent-1, versão 1.2.0)
- 11:47:20 pod removido: air-quality-api-54f5f47fb-wwmzm (k3d-aps-agent-1, versão 1.1.0)
- 11:47:24 pod terminando: air-quality-api-54f5f47fb-wtkq6 (k3d-aps-agent-0, versão 1.1.0)
- 11:47:24 pod pronto: air-quality-api-c77676687-8zxvz (k3d-aps-server-0, versão 1.2.0)
- 11:47:24 pod removido: air-quality-api-54f5f47fb-5cplk (k3d-aps-server-0, versão 1.1.0)
- 11:47:30 pod removido: air-quality-api-54f5f47fb-wtkq6 (k3d-aps-agent-0, versão 1.1.0)

## Evidências (nesta pasta)

- `graficos/`: um gráfico por medida, linha do tempo com os eventos marcados
- `eventos.csv`: tudo o que o Kubernetes fez, com horário (pods criados, prontos, removidos; decisões do HPA; ações)
- `replicas.csv`, `hpa.csv`: réplicas prontas e estado do HPA a cada segundo
- `*-requisicoes.csv.gz`, `*-segundos.csv`, `*-resumo.json`: arquivos brutos de cada gerador

## Análise crítica (escrever)

A hipótese se confirmou? Se não, por quê? Qual recurso limitou? O que mudaria o resultado?
