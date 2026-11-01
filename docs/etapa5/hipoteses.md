# Etapa 5: hipóteses registradas antes de medir

Escritas em 01/11/2026, antes de executar qualquer experimento. A referência é a linha de base da Etapa 4:
1 réplica, 832 req/s com p95 de 108 ms em 64 trabalhadores, CPU do pod no limite de 500m e fila acumulando.

| Experimento | Hipótese | Por quê |
|---|---|---|
| 5.1 Escala manual | A vazão cresce com as réplicas, mas abaixo do ideal: entre 4× e 6× com 8 réplicas. | O gargalo da Etapa 4 foi a CPU do pod, que se multiplica com as réplicas. Banco, gateway e notebook são únicos e limitam o ganho. |
| 5.1 Fila | Com mais réplicas, a fila acumula menos, porque há mais consumidores e mais CPU. | Na Etapa 4 a API e o consumidor disputavam os mesmos 500m. |
| 5.2 HPA | O HPA chega a 10 réplicas em 1 a 2 minutos, e o p95 só melhora depois que os pods novos ficam prontos. Reduz cerca de 5 minutos após o fim da carga. | Métricas e ciclo do HPA somam até 30 s, mais a partida dos pods. A redução espera a janela de estabilização. |
| 5.3 Pod apagado | Poucas falhas, só nas requisições em andamento, e substituto pronto em 5 a 7 s. | Foi o tempo medido na Etapa 3; a outra réplica segue atendendo. |
| 5.3 Nó drenado sem banco | Poucas falhas, porque o drain encerra os pods com aviso. | Os pods são despejados com encerramento gracioso e recriados em outro nó. |
| 5.3 Nó drenado com banco | O banco fica `Pending` até o `uncordon`, e as APIs respondem `503` nesse intervalo. | O volume `local-path` está preso ao nó. |
| 5.4 Rolling update sem `preStop` | Poucas falhas, e as versões 1.1.0 e 1.2.0 coexistem durante a troca. | `maxSurge: 1` e `maxUnavailable: 0` mantêm réplicas no ar, mas o gateway ainda pode enviar tráfego a um pod encerrando. |
| 5.4 Rolling update com `preStop` | Menos falhas que sem `preStop`, idealmente zero. | A espera dá tempo de o gateway parar de enviar tráfego antes do encerramento. |
| 5.4 Rollout undo | Mesmo comportamento do update, voltando à 1.1.0. | O undo é outro rolling update. |
| 5.5 Fila × síncrono | Sem fila, o POST fica mais lento e a vazão cai, mas não sobra trabalho acumulado. | A avaliação do alerta volta para dentro da requisição. |
