# Etapa 5 — protocolo dos experimentos

Este roteiro automatiza a coleta do gerador, mas não contém resultados fabricados. Cada rodada precisa gerar arquivos próprios; preencher as conclusões somente depois de executar no cluster do grupo.

## Preparação

1. Subir o cluster e as APIs conforme o README principal.
2. Conferir ambiente: `kubectl get nodes -o wide`, `kubectl get pods -n aps -o wide`, versão do Docker, CPU e RAM do computador.
3. Deixar o gerador no mesmo computador em todas as rodadas e anotar essa condição. Fechar tarefas concorrentes.
4. Usar o mesmo endpoint, corpo, timeout, duração, aquecimento e concorrência nas comparações.
5. Guardar `kubectl top pods -n aps` e horário dos eventos junto dos CSV/JSON do gerador.

Endpoint de ingestão (POST): `http://127.0.0.1:8081/api/v1/flooding/water-level`.

Endpoint de consulta agregada (GET): `http://127.0.0.1:8081/api/v1/air-quality/areas/CENTRO/average?hours=24`.

## 5.1 — escala horizontal manual

Hipótese a registrar antes de medir: mais réplicas da API podem aumentar a vazão, até o banco ou a máquina hospedeira se tornar o limite. Ganho ideal N× é referência, não promessa.

Remova o HPA para ele não alterar a quantidade de pods. Em cada repetição, execute a mesma carga e altere só as réplicas:

```powershell
kubectl delete hpa flooding-api -n aps --ignore-not-found
kubectl scale deployment/flooding-api -n aps --replicas=1
python carga/loadgen.py http://127.0.0.1:8081/api/v1/flooding/water-level -c 16 -d 35 --warmup 5 --prefixo resultados/manual-r1
kubectl scale deployment/flooding-api -n aps --replicas=2
python carga/loadgen.py http://127.0.0.1:8081/api/v1/flooding/water-level -c 16 -d 35 --warmup 5 --prefixo resultados/manual-r2
kubectl scale deployment/flooding-api -n aps --replicas=4
python carga/loadgen.py http://127.0.0.1:8081/api/v1/flooding/water-level -c 16 -d 35 --warmup 5 --prefixo resultados/manual-r4
kubectl scale deployment/flooding-api -n aps --replicas=8
python carga/loadgen.py http://127.0.0.1:8081/api/v1/flooding/water-level -c 16 -d 35 --warmup 5 --prefixo resultados/manual-r8
```

Faça pelo menos três rodadas por configuração. O `X-Pod` no CSV confirma quais pods atenderam. Registre mediana/variação entre as repetições e compare ganho medido com N×.

## 5.2 — HPA

Reaplique `k8s/30-hpa-flooding.yaml`; confirme `kubectl top pods -n aps` e `kubectl get hpa -n aps`. Em um terminal acompanhe `kubectl get hpa -n aps -w`; em outro rode:

```powershell
python carga/loadgen.py http://127.0.0.1:8081/api/v1/flooding/water-level -c 32 -d 120 --rampa --warmup 0 --prefixo resultados/hpa
```

Anote horário do início da rampa, primeira decisão de escala, pods novos `1/1`, p95 de volta ao patamar anterior e início da redução. Consulte `kubectl describe hpa flooding-api -n aps` para os eventos.

## 5.3 — pod apagado sob carga

```powershell
python carga/loadgen.py http://127.0.0.1:8081/api/v1/flooding/water-level -c 16 -d 120 --prefixo resultados/pod
```

Durante a carga, em outro terminal, apague um dos pods da API: `kubectl delete pod -n aps <pod>`. Use os horários da série CSV e `kubectl get pods -n aps -w` para calcular erros e tempo até o substituto ficar `1/1` e a latência voltar ao patamar normal.

## 5.4 — nó drenado

Primeiro veja a localização do PostgreSQL: `kubectl get pods -n aps -o wide`. Escolha um nó de agente que **não** hospede o PostgreSQL e anote qual foi. Com a mesma carga contínua, drene o nó: `kubectl drain <no-agente> --ignore-daemonsets --delete-emptydir-data`; ao concluir, devolva-o com `kubectl uncordon <no-agente>`. Não use `--force`. O volume local do PostgreSQL pode impedir a mudança do banco; esse comportamento deve ser descrito se observado.

## 5.5 — rolling update e retorno

Construa uma tag nova sem alterar o contrato da API, importe no cluster e acompanhe o tráfego:

```powershell
docker build --build-arg APP_VERSION=1.1.0 -t aps-sd/flooding-api:1.1.0 ./src/Flooding.Api
k3d image import aps-sd/flooding-api:1.1.0 -c aps
kubectl set image deployment/flooding-api api=aps-sd/flooding-api:1.1.0 -n aps
kubectl rollout status deployment/flooding-api -n aps
kubectl rollout history deployment/flooding-api -n aps
kubectl rollout undo deployment/flooding-api -n aps
```

Execute o gerador em outro terminal durante a troca. A tag fixa de cada imagem também define seu `APP_VERSION`, e o cabeçalho `X-Versao` permite contar a coexistência. `rollout undo` retorna para a revisão anterior.

## 5.6 — efeito do cache

O cache implementado é ASP.NET Output Cache com Redis compartilhado, TTL de 15 s, aplicado às consultas agregadas. Pode devolver uma resposta um pouco antiga durante o TTL. Redis usa uma instância sem persistência, suficiente para a comparação desta APS, sem alta disponibilidade.

Faça primeiro a rodada sem cache (`CACHE_ENABLED=false` em `k8s/03-config.yaml`), depois habilite (`true`), aplique a configuração e reinicie somente a API:

```powershell
kubectl apply -f k8s/03-config.yaml
kubectl rollout restart deployment/air-quality-api -n aps
python carga/loadgen.py "http://127.0.0.1:8081/api/v1/air-quality/areas/CENTRO/average?hours=24" -X GET -b "" -c 16 -d 35 --warmup 5 --prefixo resultados/cache-off
```

Repita com `CACHE_ENABLED=true` e o mesmo comando/parâmetros. Compare p50/p95/p99, vazão, erros e `kubectl top pods -n aps`; faça três repetições em cada condição e relate a limitação do Redis de instância única.

## Tabela de resultados a preencher

| Cenário | Réplicas/cache | Trabalhadores | Vazão req/s | p50 ms | p95 ms | p99 ms | Erros % | CPU da API/banco | Evidência |
|---|---:|---:|---:|---:|---:|---:|---:|---|---|
| Base | 1 / off | | | | | | | | |
| Escala | 2 | | | | | | | | |
| Escala | 4 | | | | | | | | |
| Escala | 8 | | | | | | | | |
| Cache desligado | 1 / off | | | | | | | | |
| Cache ligado | 1 / on | | | | | | | | |

## Gráficos PNG

Instale a dependência de visualização uma vez: `python -m pip install -r carga/requirements.txt`.

Uma linha de base com degraus gera latência e vazão por nível de carga:

```powershell
python carga/plot_results.py --modo baseline resultados/linha-base-AAAAmmdd-HHMMSS-resumo.json --saida resultados/linha-base.png
python carga/plot_results.py --modo serie resultados/hpa-AAAAmmdd-HHMMSS-serie.csv --saida resultados/hpa-p95.png
```

Para comparar arquivos de execuções manuais, passe um rótulo por arquivo JSON:

```powershell
python carga/plot_results.py --modo comparacao --rotulos replicas-1,replicas-2,replicas-4,replicas-8 arquivo-r1.json arquivo-r2.json arquivo-r4.json arquivo-r8.json --saida resultados/escala.png
```

Não transcreva valores de exemplo das apostilas como se fossem observados pelo grupo. Inclua os arquivos `*-requisicoes.csv`, `*-serie.csv` e `*-resumo.json`, comandos exatos, configuração da máquina e horários.
