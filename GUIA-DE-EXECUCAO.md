# Guia de execução: como rodar e mostrar tudo

Roteiro para subir o projeto do zero, demonstrar cada funcionalidade ao professor e rodar as medições das Etapas 3, 4 e 5. Cada passo tem dois jeitos:

- **pelo script**: um comando que faz tudo;
- **à mão**: os comandos separados que o script executa. Saber fazer à mão é o que a banca cobra.

Todos os comandos são para o **PowerShell**, na pasta do projeto (`aps-8sem-sd`).

---

## Sumário

1. [O que é cada peça](#1-o-que-é-cada-peça)
2. [Preparar o computador (uma vez)](#2-preparar-o-computador-uma-vez)
3. [Subir tudo](#3-subir-tudo)
4. [Conferir se está funcionando](#4-conferir-se-está-funcionando)
5. [As funcionalidades da aplicação](#5-as-funcionalidades-da-aplicação)
6. [Etapa 3: os testes da banca no Kubernetes](#6-etapa-3-os-testes-da-banca-no-kubernetes)
7. [Etapa 4: gerador de carga e linha de base](#7-etapa-4-gerador-de-carga-e-linha-de-base)
8. [Etapa 5: os experimentos](#8-etapa-5-os-experimentos)
9. [Demonstração ao vivo para o professor (seção 6 da ficha)](#9-demonstração-ao-vivo-para-o-professor-seção-6-da-ficha)
10. [Achados para a análise crítica](#10-achados-para-a-análise-crítica)
11. [Desligar, religar e problemas comuns](#11-desligar-religar-e-problemas-comuns)
12. [Cola de comandos](#12-cola-de-comandos)

---

## 1. O que é cada peça

### A arquitetura

```
 navegador / gerador de carga
            │  http://localhost:8081
            ▼
 Ingress "gateway" (Traefik, 2 réplicas): lê a URL e manda cada requisição para o serviço certo
   /api/v1/air-quality      /api/v1/flooding      /api/v1/thermal-inversion       /
          │                       │                         │                    │
   air-quality-api           flooding-api          thermal-inversion-api     web-client
   (2 a 10 pods, HPA)        (2 a 10 pods, HPA)     (2 a 10 pods, HPA)        (2 pods)
          └──────────────┬────────┴───────────────┬─────────┘
                         │                        │
   postgres (StatefulSet + disco)      redis (cache)      rabbitmq (StatefulSet + disco, fila)
```

### As "máquinas"

O cluster tem 3 nós, e **cada nó é um contêiner do Docker** fazendo papel de máquina (é o que o k3d faz):

| Contêiner | Papel |
|---|---|
| `k3d-aps-server-0` | plano de controle (o "cérebro": API server, scheduler, controladores) e também roda pods |
| `k3d-aps-agent-0`, `k3d-aps-agent-1` | nós de trabalho: rodam um *kubelet* (o agente) que liga e desliga os pods |
| `k3d-aps-serverlb` | liga a porta 8081 do PC ao gateway dentro do cluster |

Os pods da aplicação rodam **dentro** desses contêineres, num nível abaixo. Por isso o Docker Desktop mostra só os 4 contêineres do k3d, e não os pods.

### Os arquivos

| Pasta / arquivo | O que tem |
|---|---|
| `src/` | as 3 APIs (.NET 8) e o cliente web |
| `k8s/` | os manifestos do Kubernetes, aplicados com `kubectl apply -f k8s/` |
| `scripts/` | `k8s-up` (sobe tudo), `k8s-build` (imagens), `k8s-verificar` (confere), em `.ps1` e `.sh` |
| `carga/loadgen.py` | o gerador de carga: o instrumento de medição |
| `carga/ao_vivo.py` | a janela com os gráficos redesenhados a cada segundo |
| `carga/linha-de-base.ps1` | roda a linha de base da Etapa 4 inteira |
| `carga/experimento.py` | roda cada experimento da Etapa 5 (e a demo ao vivo) |
| `carga/graficos.py`, `carga/analise_etapa5.py` | geram tabelas e gráficos a partir dos resultados |
| `resultados/` | o que foi medido: arquivos brutos, tabelas e gráficos |

---

## 2. Preparar o computador (uma vez)

```powershell
winget install -e --id Docker.DockerDesktop
winget install -e --id k3d.k3d
winget install -e --id Git.Git
winget install -e --id Python.Python.3.13
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
```

Depois:

1. **Feche e abra o PowerShell**, para ele achar os programas novos.
2. **Abra o Docker Desktop** e espere aparecer "Engine running". Na primeira vez ele pode pedir o WSL2 e uma reinicialização.
3. Instale a biblioteca dos gráficos: `python -m pip install matplotlib`.
4. Confira se os três respondem com uma versão:

```powershell
docker version --format '{{.Server.Version}}'
kubectl version --client
k3d version
```

Só se instala o que roda **no PC**. Tudo o que a aplicação usa (.NET 8, PostgreSQL 16, Redis, RabbitMQ, nginx e o próprio Kubernetes) vem em imagens com versão fixa, baixadas sozinhas na primeira vez, como no Docker Compose.

---

## 3. Subir tudo

```powershell
git clone -b gulosao https://github.com/Mateusoaz/aps-8sem-sd.git
cd aps-8sem-sd
Copy-Item .env.example .env
```

### Pelo script

```powershell
.\scripts\k8s-up.ps1
```

Na primeira vez leva uns 5 minutos. Pode rodar de novo quando quiser, por exemplo depois de mudar o código: o que já existe é mantido ou atualizado.

### À mão (a sequência da banca, roteiro "Como será verificado" da Prática 3)

```powershell
# 1. As 3 "máquinas": 1 servidor + 2 agentes; a porta 8081 do PC vai para o gateway
k3d cluster create aps --agents 2 -p "8081:80@loadbalancer"
kubectl get nodes

# 2. As imagens. O cluster NÃO enxerga as imagens do Docker do PC: cada nó tem o próprio depósito
docker build --build-arg APP_VERSION=1.1.0 -t aps-sd/air-quality-api:1.1.0 src/AirQuality.Api
docker build --build-arg APP_VERSION=1.1.0 -t aps-sd/flooding-api:1.1.0 src/Flooding.Api
docker build --build-arg APP_VERSION=1.1.0 -t aps-sd/thermal-inversion-api:1.1.0 src/ThermalInversion.Api
docker build -t aps-sd/web-client:1.1.0 src/WebClient
k3d image import -c aps aps-sd/air-quality-api:1.1.0 aps-sd/flooding-api:1.1.0 aps-sd/thermal-inversion-api:1.1.0 aps-sd/web-client:1.1.0

# 3. A "pasta" aps e o Secret com as senhas (vem do .env, que não vai para o Git)
kubectl apply -f k8s/00-namespace.yaml
kubectl create secret generic aps-credenciais -n aps --from-env-file=.env

# 4. Todo o resto: banco, cache, fila, APIs, cliente, gateway, HPA, PDB
kubectl apply -f k8s/

# 5. Esperar ficar tudo 1/1 Running (Ctrl+C sai)
kubectl get pods -n aps -w
```

O que o script faz a mais que a sequência à mão:

| O script… | À mão você precisaria… |
|---|---|
| pula a criação do cluster se ele já existe | não repetir o passo 1 (dá "already exists") |
| recria o Secret se ele já existe | rodar `kubectl delete secret aps-credenciais -n aps` antes |
| confere se o `.env` tem as 4 senhas | descobrir pelo erro `CreateContainerConfigError` |
| se a senha do `.env` mudou e o banco já existe, atualiza a senha no Postgres e no RabbitMQ | ver a seção 10, "a senha no volume" |
| espera cada peça ficar pronta e para no primeiro erro | acompanhar com `kubectl get pods -w` |

---

## 4. Conferir se está funcionando

### Pelo script

```powershell
.\scripts\k8s-verificar.ps1
```

Ele confere tudo pelo gateway e termina com **"Tudo certo."**:
- o cliente web;
- a readiness das 3 APIs;
- um POST com o alerta passando pela fila;
- o cache (`MISS` na primeira consulta, `HIT` na segunda);
- 10 requisições divididas entre os pods;
- o `kubectl top`.

### À mão

```powershell
kubectl get nodes -o wide                                # 3 nós Ready
kubectl get all,ingress,pvc,hpa,pdb -n aps -o wide       # tudo: pods (e em qual nó), Services, Ingress, discos, HPA
curl.exe -s http://localhost:8081/api/v1/air-quality/health/ready
kubectl top pod -n aps                                   # CPU e memória de cada pod (metrics-server)
```

### Os endereços

| O quê | Endereço |
|---|---|
| Cliente web | http://localhost:8081/ |
| Swagger da qualidade do ar | http://localhost:8081/api/v1/air-quality/swagger |
| Swagger do alagamento | http://localhost:8081/api/v1/flooding/swagger |
| Swagger da inversão térmica | http://localhost:8081/api/v1/thermal-inversion/swagger |
| Painel do RabbitMQ | rode `kubectl port-forward -n aps svc/rabbitmq 15672` e abra http://localhost:15672 (usuário e senha do `.env`) |

---

## 5. As funcionalidades da aplicação

### As 3 APIs

| API | Domínio | Recebe leituras de | Consultas | Regra de alerta |
|---|---|---|---|---|
| `air-quality-api` | qualidade do ar | `particulate` (PM2.5/PM10), `gases`, `environment` | última leitura da estação, média do bairro, alertas | PM2.5 acima do limite por 3 leituras seguidas |
| `flooding-api` | alagamento | `water-level`, `rainfall`, `flow-rate` | nível atual do ponto, histórico, alertas | nível da água cruza a cota de transbordamento |
| `thermal-inversion-api` | inversão térmica | `temperature-profile`, umidade, pressão, vento | perfil térmico do bairro, ocorrências, alertas | ar de cima mais quente que o da superfície |

O alerta sai **uma vez por episódio**, não a cada leitura acima do limite.

### Como mostrar cada funcionalidade

**Pelo cliente web** (http://localhost:8081/):
- cada card mostra a readiness da API, com o estado de cada dependência;
- **Enviar leitura** manda um POST;
- **Consultar** faz a consulta agregada e mostra se veio do cache;
- **Alertas** lista os últimos alertas;
- o quadro **Balanceamento** dispara N requisições e conta por pod e versão;
- a tabela **Últimas requisições** mostra os cabeçalhos de cada resposta.

**À mão**, uma funcionalidade por vez:

```powershell
$gw = "http://localhost:8081/api/v1/air-quality"

# Gravar uma leitura (201). O cabeçalho X-Alerta diz se o alerta foi pela fila ou dentro do POST
$r = Invoke-WebRequest -UseBasicParsing -Method Post -Uri "$gw/particulate" -ContentType "application/json" `
     -Body '{"stationId":"EST-01","sensorId":"S1","areaId":"CENTRO","pm25":30,"pm10":50}'
$r.StatusCode; $r.Headers["X-Pod"]; $r.Headers["X-Alerta"]

# Disparar um alerta: 3 leituras seguidas acima de 25 na mesma estação
30, 35, 40 | ForEach-Object { Invoke-RestMethod -Method Post -Uri "$gw/particulate" -ContentType "application/json" `
     -Body "{`"stationId`":`"EST-DEMO`",`"sensorId`":`"S1`",`"areaId`":`"CENTRO`",`"pm25`":$_,`"pm10`":50}" | Out-Null }
Invoke-RestMethod "$gw/alerts?stationId=EST-DEMO"

# Cache: a 1ª consulta vem do banco (MISS), a 2ª do Redis (HIT)
(Invoke-WebRequest -UseBasicParsing "$gw/areas/CENTRO/average?hours=24").Headers["X-Cache"]
(Invoke-WebRequest -UseBasicParsing "$gw/areas/CENTRO/average?hours=24").Headers["X-Cache"]

# Readiness: o estado do banco, do cache e da fila, e qual pod respondeu
Invoke-RestMethod "$gw/health/ready" | ConvertTo-Json -Depth 4

# Balanceamento: 10 requisições, contadas por pod
1..10 | ForEach-Object { (Invoke-WebRequest -UseBasicParsing "$gw/health/live").Headers["X-Pod"] } | Group-Object | Select-Object Count, Name

# A fila: mensagens pendentes e consumidores (um por réplica)
kubectl exec -n aps rabbitmq-0 -- rabbitmqctl -q list_queues name messages consumers
```

### Os cabeçalhos de evidência

| Cabeçalho | Em quais respostas | Para quê |
|---|---|---|
| `X-Pod` | todas | qual pod atendeu: prova do balanceamento |
| `X-Versao` | todas | a versão da imagem: mostra as duas versões juntas no rolling update |
| `X-Cache` | consultas agregadas | `HIT` (Redis), `MISS` (banco), `OFF` (cache desligado), `BYPASS` (Redis fora do ar) |
| `X-Alerta` | POST com regra de alerta | `fila` (assíncrono) ou `sincrono` (avaliado no POST) |

### O que explicar sobre cada peça

- **Liveness × readiness.** A liveness (`/health/live`) só pergunta "o processo está vivo?"; se falha, o kubelet reinicia o contêiner. A readiness (`/health/ready`) verifica banco, cache e fila **a cada chamada**; se falha, o pod sai do Service sem ser reiniciado. Banco fora → 503 (sai do balanceamento). Cache ou fila fora → `Degraded` com 200 (continua atendendo, só mais devagar).
- **Cache (Redis).** As consultas agregadas ficam guardadas 10 s. Todas as réplicas usam o mesmo cache, porque ele fica fora dos pods. O custo é o dado poder estar até 10 s desatualizado.
- **Fila (RabbitMQ).** O POST grava, publica o id na fila e responde na hora. Um consumidor em cada réplica avalia o alerta depois. Se o pod morrer no meio, a mensagem volta para a fila, e por isso a avaliação é à prova de repetição. Com a fila fora do ar, o alerta é avaliado dentro do próprio POST.
- **Banco criado em segundo plano.** No Kubernetes não existe `depends_on`. A API abre a porta na hora (a liveness passa) e só fica pronta quando o banco existe (a readiness espera). Sem isso, o pod entraria em `CrashLoopBackOff` se subisse antes do Postgres.

---

## 6. Etapa 3: os testes da banca no Kubernetes

A banca vai: subir tudo num cluster novo (seção 3, à mão), abrir o cliente pelo Ingress, mostrar o `X-Pod` alternando, apagar um pod de qualquer serviço e mostrar o novo ficando pronto, e escalar um serviço para 4 réplicas.

Deixe um terminal com `kubectl get pods -n aps -o wide -w` aberto o tempo todo.

**Abrir o cliente pelo Ingress.** http://localhost:8081/. "O Ingress é o gateway único: ele lê a URL e manda `/api/v1/air-quality` para um Service, `/api/v1/flooding` para outro, e o que sobrar (`/`) para o cliente web. É camada 7: distribui requisição por requisição."

**`X-Pod` alternando.** No cliente, quadro **Balanceamento**, botão **Disparar**. Ou no terminal:

```powershell
1..10 | ForEach-Object { (Invoke-WebRequest -UseBasicParsing http://localhost:8081/api/v1/flooding/health/live).Headers["X-Pod"] } | Group-Object | Select-Object Count, Name
```

"10 requisições, 5 para cada réplica: o Traefik distribui em rodízio."

**Apagar um pod de qualquer serviço.**

```powershell
kubectl get pods -n aps -l app=flooding-api
kubectl delete pod -n aps <nome de um deles>
```

"O ReplicaSet viu uma réplica a menos e criou outra. O pod novo tem outro nome e outro IP; o apagado não 'volta'. Durante os segundos em que o novo está `0/1`, o Service não manda requisições para ele."

**Escalar para 4.**

```powershell
kubectl delete hpa thermal-inversion-api -n aps        # o HPA desfaria a escala manual
kubectl scale deployment thermal-inversion-api -n aps --replicas=4
kubectl get pods -n aps -l app=thermal-inversion-api -o wide
```

"As réplicas foram espalhadas pelos 3 nós (regra `topologySpreadConstraints`)." No fim: `kubectl apply -f k8s/40-hpa.yaml`.

### As evidências que a Prática 3 pede para o relatório

| Evidência | Comando |
|---|---|
| Aplicação completa | `kubectl get all,ingress,pvc,hpa -n aps -o wide` |
| Distribuição por pod | o laço do `X-Pod` acima |
| Pod apagado até o substituto `1/1` | `kubectl get pods -n aps -w` enquanto apaga (ou `python carga/experimento.py pod-apagado`, que guarda a linha do tempo) |
| Queda do banco: `0/1` com `RESTARTS 0` e dados preservados | a sequência "derrubar o banco" da seção 9 |
| `kubectl top pod` | `kubectl top pod -n aps` |
| Eventos do HPA | `kubectl describe hpa air-quality-api -n aps` (ou o experimento `hpa`) |
| Diagrama de implantação | `kubectl get pods -n aps -o wide` mostra cada pod e seu nó; o desenho da seção 1 mostra os Services |

---

## 7. Etapa 4: gerador de carga e linha de base

### O que é o gerador

O `carga/loadgen.py` simula **trabalhadores**: cada um é um cliente que envia uma requisição, espera a resposta inteira e só então envia a próxima (laço fechado). O número de trabalhadores define a **concorrência**: quantas requisições estão em andamento ao mesmo tempo. A vazão (req/s) é o **resultado**, e segue a **Lei de Little**: vazão ≈ trabalhadores ÷ latência média.

Ele registra de cada requisição a latência, o status, o erro, o `X-Pod` e o `X-Versao`. Calcula p50, p95 e p99, vazão e taxa de erro, e grava em CSV e JSON.

### Pelo script (a linha de base inteira, ~30 min)

```powershell
.\carga\linha-de-base.ps1
```

1. Deixa 1 réplica de cada serviço e remove o HPA.
2. Aquece os pods (carga descartada).
3. Sobe os degraus de 1 a 64 trabalhadores, 30 s cada, 3 vezes, na ingestão (POST) e na consulta (GET).
4. Gera tabelas e gráficos e devolve o cluster ao normal.

A janela ao vivo abre sozinha. O resultado sai em `resultados\base\<data-hora>\`:

| Arquivo | O que é |
|---|---|
| `tabela-ingestao.md`, `tabela-consulta.md` | a tabela da seção 5 da ficha, com o ponto de saturação |
| `grafico-ingestao.png`, `grafico-consulta.png` | latência, vazão e erros num gráfico só |
| `graficos-ingestao\`, `graficos-consulta\` | um gráfico por medida |

### À mão

```powershell
# 1. Uma réplica e sem HPA (o HPA desfaria a escala)
kubectl delete hpa --all -n aps
kubectl scale deployment air-quality-api flooding-api thermal-inversion-api -n aps --replicas=1
kubectl get deploy,hpa -n aps

# 2. Num segundo terminal, a janela ao vivo
python carga/ao_vivo.py resultados/manual

# 3. Os degraus (uma repetição da ingestão)
python carga/loadgen.py http://127.0.0.1:8081/api/v1/air-quality/particulate -X POST --corpo ar `
       --degraus 1,2,4,8,16,32,64 --duracao-degrau 30 --aquecimento 5 --top --saida resultados/manual/ingestao-rep1

# 4. Um teste avulso, como na verificação ao vivo da ficha da Etapa 4 ("8 trabalhadores por 20 s")
python carga/loadgen.py http://127.0.0.1:8081/api/v1/air-quality/health/live -c 8 -d 20 --saida resultados/manual/rapido

# 5. Tabela e gráficos de uma pasta com resumos
python carga/graficos.py resultados/manual

# 6. Devolver o cluster ao normal
kubectl apply -f k8s/
```

Ajuda de todas as opções: `python carga/loadgen.py --help`.

### O que explicar

- **p95:** 95% das requisições responderam em até esse tempo. A média esconde os lentos; o p95 mostra o pior caso frequente.
- **Ponto de saturação (joelho):** até ali, dobrar os trabalhadores quase dobra a vazão. Depois dele, a vazão para de crescer e só a latência sobe: as requisições extras ficam na fila.
- **O que saturou primeiro:** a CPU do pod da API, presa no limite de 500m (o `kubectl top` mostra). O banco estava longe do limite.
- **p95 muito acima do p50:** quando o pod bate no limite de CPU, o kernel congela o contêiner até o fim do período de 100 ms (*throttling*), e algumas requisições pagam essa espera.
- **A medição é confiável:** a Lei de Little fecha (a latência média medida bate com trabalhadores ÷ vazão), e a CPU do próprio gerador ficou longe de 100%.

---

## 8. Etapa 5: os experimentos

### Pelo script

```powershell
python carga/experimento.py escala                # ~10 min
python carga/experimento.py hpa                   # ~14 min (inclui a redução, que só começa 5 min depois)
python carga/experimento.py pod-apagado           # ~3 min
python carga/experimento.py no-drenado            # ~4 min
python carga/experimento.py rolling               # ~5 min
python carga/experimento.py rolling-sem-prestop   # ~5 min
python carga/experimento.py cache                 # ~5 min
python carga/experimento.py fila                  # ~5 min
python carga/experimento.py todos                 # todos em sequência (~50 min)
```

Cada um:
1. prepara o cluster;
2. abre a janela ao vivo;
3. executa a ação no segundo certo;
4. registra com horário tudo o que o Kubernetes fez;
5. devolve o cluster ao normal;
6. gera o resultado em `resultados\etapa5\<data-hora>-<experimento>\`:
   - `tabela.md`: a seção 5 da ficha, com hipótese sugerida, procedimento e evidências;
   - `graficos\`: um gráfico por medida, com os eventos marcados na linha do tempo;
   - `eventos.csv`: o diário do Kubernetes.

`--rapido` divide as durações por 3, só para conferir o fluxo. **Não use os números do modo rápido no relatório.**

### À mão, experimento por experimento

Em todos: janela ao vivo num terminal, carga em outro, ação num terceiro.

```powershell
# Janela ao vivo (deixe aberta)
python carga/ao_vivo.py resultados/manual

# Carga contínua, 5 min (troque -c e -d como precisar)
python carga/loadgen.py http://127.0.0.1:8081/api/v1/air-quality/particulate -X POST --corpo ar -c 32 -d 300 --top --saida resultados/manual/carga
```

| Experimento | Ação, num terceiro terminal |
|---|---|
| **Escala manual** (5.1) | `kubectl delete hpa air-quality-api -n aps`, depois `kubectl scale deployment air-quality-api -n aps --replicas=1` (rode a carga), repita com `--replicas=2`, `4` e `8`, e compare a vazão de cada resumo |
| **HPA** (5.2) | `kubectl apply -f k8s/40-hpa.yaml`; carga em rampa: `python carga/loadgen.py <url> -X POST --corpo ar -c 128 -d 300 --rampa 120`; acompanhe com `kubectl get hpa -n aps -w` e, no fim, `kubectl describe hpa air-quality-api -n aps` |
| **Pod apagado** (5.3) | `kubectl delete pod -n aps <nome>` |
| **Nó drenado** (5.3) | `kubectl drain k3d-aps-agent-1 --ignore-daemonsets --delete-emptydir-data`; no fim, `kubectl uncordon k3d-aps-agent-1` |
| **Rolling update** (5.4) | `.\scripts\k8s-build.ps1 -Versao 1.2.0`, `kubectl set image deployment/air-quality-api -n aps api=aps-sd/air-quality-api:1.2.0`, `kubectl rollout status deployment/air-quality-api -n aps` |
| **Rollback** (5.4) | `kubectl rollout undo deployment/air-quality-api -n aps` e `kubectl rollout history deployment/air-quality-api -n aps` |
| **Sem preStop** (5.4) | antes do rolling update, remova o `preStop` com o patch abaixo |
| **Cache** (5.5) | desligue com o patch abaixo, depois `kubectl rollout restart deployment air-quality-api -n aps`; rode a carga em `GET /api/v1/air-quality/areas/CENTRO/average?hours=24`, com e sem |
| **Fila** (5.5) | o mesmo, trocando `Cache__Enabled` por `Queue__Enabled` |

Os patches vão por arquivo (`--patch-file`). No Windows PowerShell 5.1, o `-p '{"data":...}'` não funciona: o PowerShell tira as aspas duplas do JSON antes de passar para o `kubectl`, e ele responde "invalid character".

```powershell
# Desligar o cache (para religar, troque "false" por "true")
'{"data":{"Cache__Enabled":"false"}}' | Set-Content patch.json
kubectl patch configmap aps-config -n aps --type merge --patch-file patch.json
kubectl rollout restart deployment air-quality-api -n aps

# Remover o preStop
'[{"op":"remove","path":"/spec/template/spec/containers/0/lifecycle"}]' | Set-Content patch.json
kubectl patch deployment air-quality-api -n aps --type=json --patch-file patch.json
```

Depois de qualquer experimento à mão: `kubectl apply -f k8s/` (e `kubectl rollout restart deployment -n aps` se mexeu no ConfigMap). Apague o `patch.json` no fim.

> Rode a linha de base e os experimentos **na mesma máquina**, sem outras cargas pesadas no PC. As 3 "VMs" dividem os núcleos dele, e outra máquina dá outros números.

---

## 9. Demonstração ao vivo para o professor (seção 6 da ficha)

### Pelo script: o modo demo

Um terminal só para a demo:

```powershell
python carga/experimento.py demo
```

1. Constrói a versão 1.2.0.
2. Deixa **1 réplica** sem HPA.
3. Aquece o pod.
4. Liga 64 trabalhadores no POST de ingestão, por até 15 min.
5. Abre a janela de gráficos e imprime os comandos para você digitar.
6. **Espera.**

Num **segundo terminal**, você faz as verificações à mão, e a janela mostra e marca cada coisa que o Kubernetes fizer: pod criado, pronto, saindo, réplicas prontas, versão nova. Para encerrar: **Ctrl+C uma vez** no terminal da demo. O cluster volta ao normal, e saem a tabela e os gráficos da demonstração em `resultados\etapa5\<data-hora>-demo\`.

Opções: `--replicas 2`, `--trabalhadores 32`, `--duracao 600`, `--rota consulta`, `--com-hpa`, `--sem-restaurar`.

### Sem o script

Janela ao vivo + carga + ação, como na seção 8. Antes, deixe 1 réplica sem HPA:

```powershell
kubectl delete hpa air-quality-api -n aps
kubectl scale deployment air-quality-api -n aps --replicas=1
.\scripts\k8s-build.ps1 -Versao 1.2.0
```

### O roteiro das 4 verificações da ficha

Deixe um terminal mostrando os pods: `kubectl get pods -n aps -l app=air-quality-api -o wide -w`.

**① Escalar de 1 para 4 réplicas e mostrar a vazão subir**

```powershell
kubectl scale deployment air-quality-api -n aps --replicas=4
```

- **Mostre:** os 3 pods novos de `0/1` para `1/1` em uns 5 s; o gráfico **Réplicas prontas** subindo para 4; a **Vazão** subindo. Anote o "agora: …" do gráfico de vazão antes e depois: ______ → ______ req/s.
- **Diga:** "O Deployment criou as réplicas, e elas só recebem tráfego depois de passar na readiness. Repare que, logo que os pods novos entram, a vazão **cai por 1 ou 2 segundos** antes de subir: o pod novo está 'frio'. O .NET ainda está compilando o código e abrindo as conexões, e as primeiras requisições que caem nele demoram."

**② Apagar um pod e contar as falhas**

```powershell
kubectl delete pod -n aps <nome de um pod da lista>
```

- **Mostre:** o pod virando `Terminating`, nascendo outro com nome novo; o gráfico **Erros por segundo** em zero.
- **Diga:** "Ninguém mandou criar esse pod: o ReplicaSet viu 3 onde deveriam ser 4 e criou outro. É o laço de controle. Não houve falha por causa do `preStop`: ao receber a ordem de parar, o pod espera 5 s antes de encerrar, e nesse tempo o gateway já o tirou da lista." Falhas: ______ (no teste: 0).

**③ Publicar nova versão e mostrar as duas coexistindo**

```powershell
kubectl set image deployment/air-quality-api -n aps api=aps-sd/air-quality-api:1.2.0
```

- **Mostre:** os pods trocados um a um; o gráfico **Respostas da versão nova (%)** subindo de 0 a 100. Para ver as duas versões respondendo no terminal:

```powershell
1..30 | ForEach-Object { (Invoke-WebRequest -UseBasicParsing http://localhost:8081/api/v1/air-quality/health/live).Headers["X-Versao"] } | Group-Object | Select-Object Count, Name
```

- **Diga:** "Com `maxSurge: 1` e `maxUnavailable: 0`, o Kubernetes sobe um pod novo, espera ele ficar pronto e só então tira um antigo. Durante a troca, as duas versões atendem." Para voltar: `kubectl rollout undo deployment/air-quality-api -n aps`.

**④ Explicar por que 8 réplicas não deram 8×** (sem consultar)

"Três motivos:
1. **A máquina é uma só.** As 3 'VMs' são contêineres no mesmo PC e dividem os mesmos núcleos.
2. **O banco é um só.** Toda escrita vai para o mesmo Postgres, que não se replica com `kubectl scale`. Cada réplica ainda tem um pool de 8 conexões com ele.
3. **O resto também é compartilhado:** o gateway, a fila e o próprio gerador.

Pela **Lei de Amdahl**, Ganho(N) = 1 / (s + (1 − s)/N), em que s é a fração do trabalho que não se divide entre as réplicas. Com o ganho medido, s ≈ ___, e o ganho máximo fica em 1/s ≈ ___×." Os números estão no `tabela.md` do experimento `escala`.

**No fim:** `kubectl apply -f k8s/` (o modo demo faz isso sozinho).

### Outras demonstrações que impressionam

```powershell
# As "VMs" e o agente dentro delas
docker ps --filter name=k3d-aps
docker exec k3d-aps-agent-0 ps -o args | Select-String "k3s agent"
docker exec k3d-aps-agent-0 crictl ps          # os pods DENTRO da "VM"

# Derrubar o banco: APIs ficam 0/1 com RESTARTS 0 (readiness, não liveness), o gateway dá 503
kubectl scale statefulset postgres -n aps --replicas=0
kubectl get pods -n aps -l tier=api
curl.exe -s -o NUL -w "%{http_code}`n" http://localhost:8081/api/v1/air-quality/alerts
kubectl scale statefulset postgres -n aps --replicas=1     # voltam sozinhas; os dados continuam lá

# O Secret não esconde a senha: Base64 não é criptografia
kubectl get secret aps-credenciais -n aps -o jsonpath='{.data.POSTGRES_PASSWORD}'
```

---

## 10. Achados para a análise crítica

A Prática 3 avisa: "resultado ruim explicado não reduz a nota; resultado não explicado, sim". Os testes revelaram estes problemas, todos com evidência guardada e quase todos corrigidos:

| Achado | O que aconteceu | Correção / explicação | Evidência |
|---|---|---|---|
| **Gateway era ponto único de falha** | o drain despejou a única réplica do Traefik; a nova levou ~12 s só para baixar a imagem e ninguém entrava no cluster, mesmo com a API saudável | `k8s/05-gateway-ha.yaml`: 2 réplicas em nós diferentes + PodDisruptionBudget | `resultados/etapa5/testes-rapidos/*ACHADO-gateway-unico` |
| **Readiness derrubava a última réplica** | sob carga, as requisições ocupavam o pool de 8 conexões; a readiness, que usava o mesmo pool, dava timeout, e o kubelet tirava o pod do Service: 11 s de 503 | a readiness usa um pool separado, só dela | `testes-rapidos/*ACHADO-readiness-no-pool` |
| **Sem `preStop`, a troca de versão falha** | 160 e 312 falhas (502 e timeout) no rolling update e no undo; com `preStop`, 0 | o pod espera 5 s antes do SIGTERM, enquanto o gateway o tira da lista | experimentos `rolling` × `rolling-sem-prestop` |
| **Pod novo é "frio"** | ao entrar, a vazão cai 1 a 2 s; 2 réplicas com uma recém-criada renderam **menos** que 1 aquecida | JIT do .NET em camadas + pools vazios; os experimentos aquecem antes de medir | gráficos da demo e do HPA |
| **Throttling de CPU** | p95 de 50 a 60 ms com p50 de 5 a 10 ms já com poucos trabalhadores | ao atingir o limite de 500m, o contêiner é congelado até o fim do período de 100 ms | linha de base |
| **A fila fica para trás** | com 1 réplica, ~69 mil alertas pendentes ao fim da carga, ~137 s para esvaziar | o consumidor divide os 500m de CPU com o HTTP; é a fila absorvendo o pico, ao custo de atraso nos alertas | `*-fila.txt` da linha de base |
| **A senha fica no volume** | trocar a senha no `.env` com o banco já criado deixou os pods novos `0/1` ("password authentication failed") | o Postgres e o RabbitMQ guardam a senha da 1ª inicialização; o `k8s-up` agora atualiza as duas | — |
| **Disco preso ao nó** | o Postgres e o RabbitMQ usam `local-path`: drenar o nó deles os deixa `Pending` até o `uncordon` | o experimento escolhe um nó sem eles; serviço com estado não se replica à vontade | `eventos.csv` do `no-drenado` |
| **HPA no limite da máquina** | com 10 réplicas a CPU continuou acima da meta | as réplicas disputam os mesmos núcleos do PC (Amdahl) | experimento `hpa` |

---

## 11. Desligar, religar e problemas comuns

| Quero | Comando |
|---|---|
| Pausar sem perder nada | `k3d cluster stop aps` |
| Religar | abrir o Docker Desktop e `k3d cluster start aps` (às vezes ele volta sozinho com o Docker) |
| Devolver a configuração dos manifestos | `kubectl apply -f k8s/` |
| Depois de mudar o código | `.\scripts\k8s-up.ps1` de novo |
| Apagar a aplicação e os dados | `kubectl delete namespace aps` |
| Apagar o cluster inteiro | `k3d cluster delete aps` |

| Sintoma | Causa provável | Solução |
|---|---|---|
| `k3d` ou `kubectl` "não reconhecido" | PowerShell aberto antes da instalação | fechar e abrir o PowerShell |
| `python` abre a Microsoft Store | atalho do Windows | usar `py` no lugar, ou desligar em Configurações → Aplicativos → Aliases de execução |
| "a execução de scripts foi desabilitada" | política do Windows | `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` |
| `failed to connect to the docker API` | Docker Desktop fechado | abrir o Docker Desktop e esperar "Engine running" |
| `k3d cluster create` falha | porta 8081 ocupada | fechar o programa que usa a 8081 |
| Pods `ImagePullBackOff` | imagem não importada no cluster | `.\scripts\k8s-up.ps1` (reconstrói e reimporta) |
| Pods `0/1` com "password authentication failed" no log | senha do `.env` diferente da do banco | `.\scripts\k8s-up.ps1` (sincroniza as senhas) |
| `CreateContainerConfigError` | Secret ausente ou sem uma chave | conferir o `.env` e rodar `.\scripts\k8s-up.ps1` |
| `kubectl scale` "não funciona" | o HPA desfaz a escala manual | `kubectl delete hpa <nome> -n aps` antes |
| `kubectl` falando com outro cluster | contexto trocado (ex.: Kubernetes do Docker Desktop) | `kubectl config use-context k3d-aps` |
| Descobrir por que um pod não sobe | — | `kubectl describe pod -n aps <nome>` (veja "Events") e `kubectl logs -n aps <nome>` |

---

## 12. Cola de comandos

```powershell
# ---------- subir / conferir ----------
.\scripts\k8s-up.ps1
.\scripts\k8s-verificar.ps1
kubectl get all,ingress,pvc,hpa,pdb -n aps -o wide
kubectl top pod -n aps

# ---------- observar ----------
kubectl get pods -n aps -o wide -w
kubectl describe pod -n aps <pod>
kubectl logs -n aps <pod>
kubectl get events -n aps --sort-by=.lastTimestamp

# ---------- escala / HPA ----------
kubectl delete hpa air-quality-api -n aps
kubectl scale deployment air-quality-api -n aps --replicas=4
kubectl apply -f k8s/40-hpa.yaml
kubectl get hpa -n aps -w
kubectl describe hpa air-quality-api -n aps

# ---------- falhas ----------
kubectl delete pod -n aps <pod>
kubectl drain k3d-aps-agent-1 --ignore-daemonsets --delete-emptydir-data
kubectl uncordon k3d-aps-agent-1
kubectl scale statefulset postgres -n aps --replicas=0      # e depois --replicas=1

# ---------- versões ----------
.\scripts\k8s-build.ps1 -Versao 1.2.0
kubectl set image deployment/air-quality-api -n aps api=aps-sd/air-quality-api:1.2.0
kubectl rollout status deployment/air-quality-api -n aps
kubectl rollout history deployment/air-quality-api -n aps
kubectl rollout undo deployment/air-quality-api -n aps

# ---------- medição ----------
python carga/ao_vivo.py resultados/manual
python carga/loadgen.py http://127.0.0.1:8081/api/v1/air-quality/particulate -X POST --corpo ar -c 32 -d 60 --top
.\carga\linha-de-base.ps1
python carga/experimento.py <escala|hpa|pod-apagado|no-drenado|rolling|rolling-sem-prestop|cache|fila|todos|demo>

# ---------- voltar ao normal ----------
kubectl apply -f k8s/
```
