# Testes rápidos (não são resultados finais)

Rodadas com `--rapido` (durações divididas por 3), feitas só para conferir que cada experimento funciona.
**Não use estes números no relatório**: os resultados finais saem das rodadas completas
(`python carga/experimento.py <experimento>`, sem `--rapido`), na pasta `resultados/etapa5/`.

Duas pastas guardam problemas que os testes revelaram e que foram corrigidos. Elas servem de evidência
para a análise crítica ("resultado ruim explicado"):

## `*-no-drenado-ACHADO-gateway-unico`

O drain do nó `k3d-aps-agent-0` despejou a **única réplica do Traefik** (o controlador do Ingress).
A nova réplica foi criada em outro nó, mas precisou baixar a imagem (~12 s), e o gateway ficou fora do ar
até o fim do teste: **0 respostas OK** a partir do segundo 11, mesmo com uma réplica da API saudável em
outro nó. O gateway era um ponto único de falha.

**Correção:** `k8s/05-gateway-ha.yaml` (Traefik com 2 réplicas espalhadas pelos nós, mais um
PodDisruptionBudget) e `k8s/50-pdb.yaml` (PodDisruptionBudget nas APIs).

Neste teste o gerador também não esperava entre tentativas após erro de conexão, então a contagem de
falhas (93 mil) está inflada. Hoje o gerador espera 50 ms, como um cliente real, e a análise mostra
também os "segundos sem resposta OK".

## `*-no-drenado-ACHADO-readiness-no-pool`

Com o gateway corrigido, o drain despejou uma das duas réplicas e a que sobrou recebeu toda a carga.
As requisições ocuparam as 8 conexões do pool com o banco, e a readiness, que verificava o banco **usando
o mesmo pool**, ficou na fila até estourar o tempo. O kubelet concluiu "banco fora" e tirou do Service
a última réplica: **11 s de 503 para todos**, sem nada de errado com o banco.

**Correção:** a readiness usa um pool de conexões separado, só dela (`Infrastructure/HealthChecks.cs`).
Depois disso, o mesmo experimento deu **0 falhas e 0 segundos fora do ar**.
