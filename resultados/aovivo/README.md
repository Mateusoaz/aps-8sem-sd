# Verificação ao vivo (13/11/2026)

Execução da seção 6 das fichas das Etapas 4 e 5, já no sistema sem Redis, RabbitMQ e cliente web, em `POST /air-quality/api/v1/air-quality/particulate`. A hora de cada comando está em `log.txt`, e os números usados nas fichas estão em `resultado.json`. Nenhuma requisição falhou.

| Teste | Configuração | Resultado |
|---|---|---|
| `etapa4` | 2 réplicas, 8 trabalhadores, 20 s, um processo do `loadgen.py` | 417 req/s, p95 de 78,1 ms; 3.125 requisições em cada pod; maior latência 99,88 ms |
| `etapa5-escala` | 64 trabalhadores, 120 s; de 1 para 4 réplicas aos 40 s | 456 req/s com 1 réplica (10 a 39 s) e 736 com 4 (70 a 117 s), média por segundo |
| `etapa5-pod` | 2 réplicas, 16 trabalhadores, 60 s; `kubectl delete pod` aos 20 s | 0 falhas em 24.950 requisições |
| `etapa5-versao-update` / `-undo` | 3 réplicas, 16 trabalhadores, 70 s cada; `set image` 1.2.0 e depois `rollout undo`, com `preStop` | 1.1.0 e 1.2.0 juntas por 8 s no update e 7 s no undo; 0 falhas em 32.573 e 36.179 |

O ganho de 1,61× com 4 réplicas é menor que o do experimento 5.1 (1,91×) porque é uma execução só, com os pods novos ainda aquecendo depois da escala. Os testes da Etapa 5 usam 4 processos do gerador, como em `carga/experimentos.py`. Os CSVs por requisição da Etapa 5 estão compactados (`.csv.gz`).

A verificação anterior, de 06/11, com Redis e RabbitMQ, está em `../antes-da-remocao/aovivo/`.
