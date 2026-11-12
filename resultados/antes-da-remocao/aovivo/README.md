# Verificação ao vivo (06/11/2026)

Execução da seção 6 das fichas das Etapas 4 e 5, na ordem do roteiro, em `POST /air-quality/api/v1/air-quality/particulate`. O passo a passo, com hora de cada comando, está em `log.txt`. Nenhuma requisição falhou.

| Teste | Configuração | Resultado |
|---|---|---|
| `etapa4` | 2 réplicas, 8 trabalhadores, 20 s | 319 req/s, p95 de 87,2 ms; 2.393 e 2.392 requisições por pod; maior latência 302,45 ms |
| `etapa5-escala` | 64 trabalhadores, 90 s; de 1 para 4 réplicas aos 30 s | cerca de 663 req/s com 1 réplica e 850 com 4 (média por segundo, fora da transição) |
| `etapa5-pod` | 2 réplicas, 16 trabalhadores, 60 s; `kubectl delete pod` aos 20 s | 0 falhas em 14.957 requisições |
| `etapa5-versao` | 3 réplicas, 16 trabalhadores, 80 s; `set image` 1.2.0 e `rollout undo` | 1.1.0 e 1.2.0 juntas por cerca de 11 s no update e 9 s no undo; 0 falhas |

O ganho de 1,28× é menor que o do experimento 5.1 (2,24×) porque esta é uma execução única, com só cerca de 40 s depois de escalar e os pods novos ainda aquecendo.
Os CSVs por requisição da Etapa 5 estão compactados (`.csv.gz`).
