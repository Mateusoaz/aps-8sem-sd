# APS 2026 — Gerenciamento de Informações Ambientais Urbanas

Três APIs REST em **.NET 8 (C#)**, cada uma cuidando de um domínio ambiental. Os dados ficam num **PostgreSQL**, as consultas agregadas num cache **Redis** e os alertas são avaliados de forma assíncrona por uma fila **RabbitMQ**. Um **cliente web** leve consome tudo pelo gateway.

A mesma aplicação roda de dois jeitos:

- **Kubernetes** (Etapa 3): cluster local de 3 nós com o k3d, atrás de um Ingress. Veja [Kubernetes](#kubernetes-etapa-3).
- **Docker Compose**: para desenvolver sem cluster.

| API | Domínio | Prefixo das rotas (= regra do Ingress) | Porta no Compose | Banco |
|---|---|---|---|---|
| `air-quality-api` | Qualidade do ar | `/api/v1/air-quality` | 5001 | `air_quality` |
| `flooding-api` | Alagamento e inundação | `/api/v1/flooding` | 5002 | `flooding` |
| `thermal-inversion-api` | Inversão térmica | `/api/v1/thermal-inversion` | 5003 | `thermal_inversion` |
| `web-client` | Cliente web (nginx) | `/` | 8080 | — |

## Kubernetes (Etapa 3)

### O cluster: contêineres fazendo papel de máquinas

O k3d cria um cluster Kubernetes (k3s) em que **cada nó é um contêiner Docker**:

| Contêiner | Papel |
|---|---|
| `k3d-aps-server-0` | Plano de controle (API server, scheduler, controladores, etcd) e também recebe pods |
| `k3d-aps-agent-0`, `k3d-aps-agent-1` | Nós de trabalho |
| `k3d-aps-serverlb` | Liga a porta **8081** da máquina à porta 80 dos nós, onde o Traefik (Ingress) escuta |

```
 navegador / gerador de carga
            │  http://localhost:8081
            ▼
   Ingress "gateway" (Traefik, camada 7: lê a URL e distribui requisição a requisição)
     /api/v1/air-quality        /api/v1/flooding        /api/v1/thermal-inversion        /
            │                         │                          │                       │
   Service air-quality-api   Service flooding-api   Service thermal-inversion-api   Service web-client
     (2 a 10 pods, HPA)        (2 a 10 pods, HPA)       (2 a 10 pods, HPA)          (2 pods nginx)
            └──────────────┬──────────┴──────────────┬───────────┘
                           │                         │
      StatefulSet postgres (PVC 1 GiB)    Deployment redis    StatefulSet rabbitmq (PVC 1 GiB)
        3 bancos, 1 por API               cache das consultas   fila de avaliação de alertas
```

### Subir do zero

Requisitos: **Docker** em execução, **kubectl** e **k3d** v5+ (Windows: `winget install k3d.k3d`). No Windows, rode no **Git Bash**.

```bash
git clone <repositório>
cd aps-8sem-sd
cp .env.example .env                 # ajuste as senhas
./scripts/k8s-up.sh                  # cluster + imagens + Secret + manifestos, e espera tudo ficar pronto
./scripts/k8s-verificar.sh           # confere tudo pelo gateway
```

Depois abra **http://localhost:8081/** (cliente web). Swagger de cada API pelo gateway: `http://localhost:8081/api/v1/air-quality/swagger` (troque pelo prefixo de `flooding` ou `thermal-inversion`).

O `k8s-up.sh` faz, em ordem, o mesmo que estes comandos (o roteiro de verificação da Aula Prática 3):

```bash
k3d cluster create aps --agents 2 -p "8081:80@loadbalancer"
./scripts/k8s-build.sh 1.1.0         # docker build das 4 imagens + k3d image import
kubectl apply -f k8s/00-namespace.yaml
kubectl create secret generic aps-credenciais -n aps --from-env-file=.env
kubectl apply -f k8s/
```

> O cluster **não enxerga** as imagens do Docker da máquina: cada nó tem o próprio depósito. Por isso o `k3d image import` depois de cada build. Os manifestos pedem a tag fixa `1.1.0`.

### Os manifestos (`k8s/`, aplicados em ordem alfabética)

| Arquivo | Objetos | Destaques |
|---|---|---|
| `00-namespace.yaml` | Namespace `aps` | `kubectl delete namespace aps` apaga tudo |
| `01-configmap.yaml` | ConfigMap `aps-config` | hosts, pool de conexões, cache e fila liga/desliga, regras de alerta |
| `10-postgres.yaml` | StatefulSet + Service headless | PVC `dados-postgres-0`; `max_connections=300` |
| `11-redis.yaml` | Deployment + Service | sem volume (cache é descartável), 64 MB com descarte LRU |
| `12-rabbitmq.yaml` | StatefulSet + Service headless | PVC `dados-rabbitmq-0`; fila durável |
| `20/21/22-*-api.yaml` | Deployment + Service por API | tag fixa, requests/limits, startup/liveness/readiness, RollingUpdate (`maxSurge 1`, `maxUnavailable 0`), `preStop` de 5 s, réplicas espalhadas pelos nós |
| `23-web-client.yaml` | Deployment + Service | nginx sem root |
| `30-ingress.yaml` | Ingress `gateway` | roteamento por caminho para os 4 Services |
| `40-hpa.yaml` | 3 HPAs | mín. 2, máx. 10, meta de 50% da CPU |

O Secret **não** está em `k8s/`: ele é criado a partir do `.env`, que não vai para o Git. O repositório leva só o modelo `secret.example.yaml`.

### Probes: o que cada uma verifica

| Probe | Rota | Verifica | Se falhar |
|---|---|---|---|
| startup | `/health/live` | o processo subiu (até 60 s) | segura as outras duas |
| liveness | `/health/live` | só o processo, **nenhuma** dependência | o kubelet **reinicia** o contêiner |
| readiness | `/health/ready` | banco, cache e fila **a cada chamada** | o pod **sai do Service**, sem reiniciar |

Na readiness, o banco fora do ar dá `503` (o pod sai do balanceamento). Cache ou fila fora do ar dão `Degraded` com `200`: a API continua atendendo, consultando direto no banco e avaliando o alerta dentro do POST. O corpo mostra o estado de cada dependência:

```json
{"status":"Healthy","instancia":"air-quality-api-7c9d8-x2k4q","versao":"1.1.0",
 "dependencias":{"banco":{"status":"Healthy","detalhe":"conectado"},
                 "cache":{"status":"Healthy","detalhe":"ping 0.4 ms"},
                 "fila":{"status":"Healthy","detalhe":"conectada"}}}
```

A criação do banco roda em segundo plano (`DatabaseInitializer`). No Kubernetes não existe `depends_on`: se a API esperasse o Postgres antes de abrir a porta, a liveness falharia e o pod entraria em `CrashLoopBackOff`.

### Cabeçalhos de evidência

| Cabeçalho | Em quais respostas | Para quê |
|---|---|---|
| `X-Pod` | todas | qual pod atendeu: evidência do balanceamento |
| `X-Versao` | todas | versão da imagem: mostra as duas versões convivendo no rolling update |
| `X-Cache` | consultas agregadas | `HIT`, `MISS`, `OFF` (desligado) ou `BYPASS` (Redis fora do ar) |
| `X-Alerta` | POST com regra de alerta | `fila` (assíncrono) ou `sincrono` (avaliado no POST) |

```bash
for i in $(seq 10); do
  curl -s -o /dev/null -D - http://localhost:8081/api/v1/flooding/health/live | grep -i x-pod
done | sort | uniq -c
```

### Comandos dos testes da banca

```bash
kubectl get all,ingress,pvc,hpa -n aps -o wide                 # visão geral
kubectl get pods -n aps -l tier=api -o wide -w                 # acompanhar os pods das APIs

kubectl delete pod -n aps <pod-de-uma-api>                     # o ReplicaSet recria sozinho
kubectl scale statefulset postgres -n aps --replicas=0         # APIs ficam 0/1 com RESTARTS 0; gateway dá 503
kubectl scale statefulset postgres -n aps --replicas=1         # voltam sozinhas, dados preservados

kubectl delete hpa air-quality-api -n aps                      # o HPA desfaria a escala manual
kubectl scale deployment air-quality-api -n aps --replicas=4

kubectl top pod -n aps                                         # metrics-server (já vem no k3s)
kubectl describe hpa air-quality-api -n aps                    # decisões de escala
curl "http://localhost:8081/api/v1/air-quality/cpu-work?n=2000000"   # gasta CPU para acionar o HPA

kubectl port-forward -n aps svc/rabbitmq 15672                 # painel da fila: http://localhost:15672
```

Rolling update e rollback:

```bash
./scripts/k8s-build.sh 1.2.0
kubectl set image deployment/air-quality-api -n aps api=aps-sd/air-quality-api:1.2.0
kubectl rollout status deployment/air-quality-api -n aps
kubectl rollout undo deployment/air-quality-api -n aps
```

Para desligar o cache ou a fila nos experimentos: mude `Cache__Enabled` ou `Queue__Enabled` para `"false"` no `01-configmap.yaml`, depois rode `kubectl apply -f k8s/01-configmap.yaml` e `kubectl rollout restart deployment -n aps`.

Limpeza: `kubectl delete namespace aps` apaga a aplicação e os volumes; `k3d cluster delete aps` apaga o cluster; `k3d cluster stop aps` / `start aps` pausa sem apagar.

## Docker Compose (sem cluster)

Só precisa de **Docker** instalado. O .NET SDK não é necessário na máquina: o build acontece dentro do contêiner.

```bash
git clone <repositório>
cd aps-8sem-sd
cp .env.example .env
docker compose up -d --build
```

Sobem 7 contêineres: Postgres, Redis, RabbitMQ, as 3 APIs e o cliente web. Sem Ingress, o nginx do cliente faz o papel do gateway (`src/WebClient/nginx.compose.conf`).

- http://localhost:8080 — cliente web
- http://localhost:5001/api/v1/air-quality/swagger — Swagger da qualidade do ar
- http://localhost:5002/api/v1/flooding/swagger — Swagger do alagamento
- http://localhost:5003/api/v1/thermal-inversion/swagger — Swagger da inversão térmica
- http://localhost:15672 — painel do RabbitMQ (usuário e senha do `.env`)

### Comandos do dia a dia

```bash
docker compose ps                      # status dos contêineres (healthy/unhealthy)
docker compose logs -f flooding-api    # acompanhar os logs de uma API
docker compose up -d --build           # rebuild depois de mudar código
docker compose restart                 # reinicia tudo (dados continuam)
docker compose down                    # derruba tudo (dados continuam no volume)
docker compose down -v                 # derruba e APAGA os dados
```

> Mudou uma entidade (coluna nova, por exemplo)? Rode `docker compose down -v` e suba de novo.
> As tabelas são criadas com `EnsureCreated`, que não altera tabelas já existentes.

## Gerador de carga (dados aleatórios)

`tools/load-generator/generator.py` simula estações e pontos de monitoramento mandando leituras para as 3 APIs. Usa só a biblioteca padrão do Python, então não precisa de `pip install`.

Os valores não são sorteados do zero a cada leitura. Cada estação guarda o seu estado, e os valores "andam" aos poucos (passeio aleatório), como num sensor de verdade. De vez em quando começa um **episódio** que dispara os alertas:

- **Poluição:** o PM2.5 sobe para ~60 µg/m³.
- **Chuva forte:** o nível do córrego sobe na direção de ~380 cm.
- **Inversão térmica:** o ar de cima fica mais quente que o da superfície, com vento fraco e pressão alta.

**Rodando com o Python da máquina** (as APIs precisam estar no ar):

```bash
python tools/load-generator/generator.py                            # 20 leituras/s até Ctrl+C
python tools/load-generator/generator.py --rate 100 --duration 60   # 6.000 leituras em 1 minuto
python tools/load-generator/generator.py --apis flooding,thermal    # só algumas APIs
python tools/load-generator/generator.py --dry-run --duration 2     # só mostra o JSON, não envia
python tools/load-generator/generator.py --gateway http://127.0.0.1:8081 --rate 50   # Kubernetes, pelo Ingress
python tools/load-generator/generator.py --help                     # todas as opções
```

**Rodando em contêiner**, sem precisar de Python instalado. O serviço fica no profile `load`, então **não** sobe junto com `docker compose up`:

```bash
docker compose run --rm load-generator                          # padrão: 50/s por 60 s
docker compose run --rm load-generator --rate 300 --duration 120
```

A cada 5 s ele mostra quantas leituras foram enviadas, os erros, a taxa real e a latência (média e p95). Esses números vão para o relatório do teste de carga.

| Opção | Padrão | O que faz |
|---|---|---|
| `--rate` | 20 | leituras por segundo, somando todas as APIs |
| `--duration` | 0 | segundos de execução (0 = até Ctrl+C) |
| `--apis` | `air,flooding,thermal` | quais APIs alimentar |
| `--entities` | 5 | estações/pontos simulados por API |
| `--workers` | 20 | requisições simultâneas |
| `--seed` | — | repete exatamente a mesma sequência aleatória |
| `--dry-run` | — | só imprime, sem enviar |
| `--gateway` | — | manda tudo para o Ingress (ex.: `http://127.0.0.1:8081`) em vez das portas do Compose |

## Estrutura do repositório

```
aps-8sem-sd/
├── docker-compose.yml          # sobe a pilha inteira sem cluster
├── .env.example                # modelo das variáveis (o .env real não vai pro git)
├── secret.example.yaml         # modelo do Secret do Kubernetes (documentação, não é aplicado)
├── ApsSd.sln                   # abre as 3 APIs juntas no Visual Studio/Rider
├── k8s/                        # manifestos do Kubernetes (kubectl apply -f k8s/)
├── scripts/
│   ├── k8s-up.sh               # sobe tudo no k3d, do zero
│   ├── k8s-build.sh            # constrói as imagens com uma tag e importa no cluster
│   └── k8s-verificar.sh        # confere a aplicação pelo gateway
├── tools/
│   └── load-generator/         # gerador de carga em Python (dados aleatórios)
└── src/
    ├── WebClient/              # cliente web: index.html + nginx (sem root)
    ├── AirQuality.Api/
    ├── Flooding.Api/
    └── ThermalInversion.Api/
        ├── Dockerfile          # build multi-stage; APP_VERSION vai para o cabeçalho X-Versao
        ├── .dockerignore
        ├── Program.cs          # configuração: banco, cache, fila, health checks, swagger, X-Pod
        ├── ApiRoutes.cs        # nome do serviço e prefixo das rotas (api/v1/<domínio>)
        ├── Controllers/        # rotas HTTP
        ├── Models/             # entidades = tabelas do banco
        ├── Dtos/               # formato do que entra (POST) e sai (respostas agregadas)
        ├── Data/               # DbContext, criação do banco em segundo plano, filtros reutilizáveis
        ├── Infrastructure/     # cache Redis, fila RabbitMQ (publicação e consumidor), health checks
        ├── Services/           # regra de alerta
        └── Options/            # limites configuráveis dos alertas
```

As três APIs têm **a mesma estrutura**. Quem entende uma, entende as três.

## Rotas

Toda API segue o padrão `/api/v1/<domínio>/<recurso>`. Cada tipo de leitura tem:

- `POST /<recurso>`: grava uma leitura e responde `201 Created`.
- `GET /<recurso>`: lista as leituras, com filtros opcionais `?from=&to=&limit=`.
- `GET /<recurso>/{id}`: busca uma leitura pelo id.

### Qualidade do ar — `/api/v1/air-quality`

| Método | Rota | Descrição |
|---|---|---|
| POST/GET | `/particulate` | PM2.5 e PM10 (µg/m³) |
| POST/GET | `/gases` | CO2 (ppm) e TVOC (ppb) |
| POST/GET | `/environment` | temperatura (°C) e umidade (%) |
| GET | `/stations/{stationId}/latest` | última leitura de cada tipo da estação |
| GET | `/stations/{stationId}/readings` | leituras da estação |
| GET | `/sensors/{sensorId}/readings` | leituras do sensor |
| GET | `/areas/{areaId}/average?hours=24` | médias da área (bairro) no período |
| GET | `/alerts` | alertas de PM2.5 |

```json
POST /api/v1/air-quality/particulate
{ "stationId": "EST-01", "sensorId": "SEN-PM-01", "areaId": "CENTRO", "pm25": 32.5, "pm10": 60 }
```

### Alagamento — `/api/v1/flooding`

| Método | Rota | Descrição |
|---|---|---|
| POST/GET | `/water-level` | nível da água (cm) |
| POST/GET | `/rainfall` | chuva acumulada (mm) |
| POST/GET | `/flow-rate` | vazão (m³/s) |
| GET | `/monitoring-points/{id}/latest` | nível atual do ponto de monitoramento |
| GET | `/monitoring-points/{id}/readings` | histórico do ponto |
| GET | `/alerts` | alertas de transbordamento |

```json
POST /api/v1/flooding/water-level
{ "monitoringPointId": "PT-01", "sensorId": "SEN-N-01", "waterLevelCm": 320 }
```

### Inversão térmica — `/api/v1/thermal-inversion`

| Método | Rota | Descrição |
|---|---|---|
| POST/GET | `/temperature-profile` | temp. na superfície e na altitude superior (°C) |
| POST/GET | `/soil-moisture` | umidade do solo (%) |
| POST/GET | `/air-humidity` | umidade do ar (%) |
| POST/GET | `/atmospheric-pressure` | pressão (hPa) |
| POST/GET | `/wind-speed` | velocidade do vento (m/s) |
| GET | `/stations/{stationId}/latest` | última leitura de cada tipo |
| GET | `/stations/{stationId}/readings` | leituras da estação |
| GET | `/areas/{areaId}/thermal-profile?hours=24` | perfil térmico médio da área |
| GET | `/alerts` | alertas de inversão |
| GET | `/occurrences` | nº de inversões por estação no período |

```json
POST /api/v1/thermal-inversion/temperature-profile
{ "stationId": "EST-T1", "areaId": "CENTRO", "surfaceSensorId": "S-SUP", "upperSensorId": "S-ALT",
  "surfaceTemperatureC": 12, "upperTemperatureC": 16 }
```

O `timestamp` é **opcional** em todo POST. Sem ele, vale o horário atual. Com ele, o formato é ISO 8601, por exemplo `"2026-09-23T20:00:00-03:00"`, e a API converte para UTC antes de gravar.

### Health checks (as três APIs)

| Rota | Pergunta | Verifica dependências? | Se falhar... |
|---|---|---|---|
| `/health/live` | O processo está vivo? | Não | o orquestrador **reinicia** o contêiner |
| `/health/ready` | Está apto a receber tráfego? | Banco, cache e fila, a cada chamada | o orquestrador **tira do balanceamento** |

As duas também existem sob o prefixo de cada API (`/api/v1/<domínio>/health/live` e `/ready`), para serem chamadas pelo gateway. As probes do Kubernetes chamam a versão sem prefixo, direto no pod.

O liveness **não pode** consultar o banco. Se consultasse, uma queda rápida do banco faria o orquestrador reiniciar todas as réplicas ao mesmo tempo, e um incidente pequeno virava queda total.

## Regras de alerta

Limites configuráveis pelo `.env`, sem recompilar:

| API | Regra | Variável |
|---|---|---|
| Qualidade do ar | PM2.5 acima do limite por **N leituras seguidas** da mesma estação | `AIR_PM25_LIMIT`, `AIR_PM25_CONSECUTIVE_READINGS` |
| Alagamento | nível da água **cruza** a cota de transbordamento | `FLOODING_OVERFLOW_LEVEL_CM` |
| Inversão térmica | temp. superior **maior** que a da superfície | `THERMAL_MIN_INVERSION_GRADIENT_C` |

O alerta é gerado **uma vez por episódio**, e não a cada leitura acima do limite. Exemplo com cota de 300 cm e leituras 250 → 320 → 350 → 200 → 310: são emitidos 2 alertas, um no 320 e outro no 310.

### Processamento assíncrono (fila) e cache

**Fila.** O POST grava a leitura, publica o id dela na fila `<serviço>.alert-evaluation` do RabbitMQ e responde `201` sem esperar a regra de alerta. Um consumidor dentro de cada réplica (`Infrastructure/AlertConsumer.cs`) avalia a regra. Todas as réplicas consomem a mesma fila (consumidores concorrentes), e cada mensagem vai para uma réplica só.

- **Confirmação depois de avaliar.** Se o pod morrer no meio, a mensagem volta para a fila e outra réplica avalia. A entrega é "pelo menos uma vez", então o `AlertService` é **idempotente**: não grava o mesmo alerta duas vezes.
- **Fila fora do ar ou desligada** (`Queue__Enabled=false`): o alerta é avaliado dentro do próprio POST. O cabeçalho `X-Alerta` diz qual caminho foi usado.

**Cache.** As consultas agregadas ficam no Redis por `Cache__TtlSeconds` segundos (cache-aside). Como o Redis fica fora dos pods, todas as réplicas aproveitam o mesmo resultado.

| API | Rotas com cache |
|---|---|
| Qualidade do ar | `/areas/{id}/average`, `/stations/{id}/latest` |
| Alagamento | `/monitoring-points/{id}/latest` |
| Inversão térmica | `/areas/{id}/thermal-profile` |

O custo: o dado pode estar até TTL segundos desatualizado. Redis fora do ar não derruba a consulta, que vai direto ao banco (`X-Cache: BYPASS`). `Cache__Enabled=false` desliga o cache para comparar com e sem.

## Convenções de nomenclatura

| Onde | Padrão | Exemplo |
|---|---|---|
| Rotas HTTP | kebab-case, recurso no singular/plural consistente, versão no prefixo | `/api/v1/flooding/water-level` |
| JSON | camelCase | `waterLevelCm`, `monitoringPointId` |
| C# (classes, propriedades) | PascalCase | `WaterLevelReading.WaterLevelCm` |
| Projetos .NET | `Dominio.Api` | `Flooding.Api` |
| Serviços do Compose / imagens | kebab-case | `flooding-api`, `aps-sd/flooding-api:1.0.0` |
| Banco (tabelas, colunas) | snake_case | `water_level_readings.monitoring_point_id` |
| Variáveis de ambiente | MAIÚSCULAS_COM_UNDERSCORE | `FLOODING_OVERFLOW_LEVEL_CM` |
| Config .NET via env | seção + `__` + chave | `ConnectionStrings__Default`, `Alerts__OverflowLevelCm` |
| Campos com medida | **unidade no nome** | `rainfallMm`, `pressureHpa`, `windSpeedMs` |
| Tipos de alerta | MAIÚSCULAS_COM_UNDERSCORE | `WATER_LEVEL_ABOVE_OVERFLOW` |

## Como funciona — conceitos

**Compose não é "contêiner dentro de contêiner".** O `docker-compose.yml` descreve 4 contêineres **irmãos** (postgres + 3 APIs) e o Compose sobe todos juntos, com um comando. Eles ficam numa rede virtual própria (`backend`) com DNS interno. Por isso a API encontra o banco pelo nome `postgres` (`Host=postgres`), sem IP fixo e sem `localhost`. Dentro de um contêiner, `localhost` é o **próprio** contêiner.

**`depends_on` + `healthcheck`.** No Compose, as APIs só iniciam depois que Postgres, Redis e RabbitMQ respondem aos seus healthchecks. Mesmo assim, a API cria o banco em segundo plano e com novas tentativas (`DatabaseInitializer`), porque no Kubernetes não existe `depends_on`.

**Volume.** O Postgres grava em `/var/lib/postgresql/data`, que está mapeado para o volume nomeado `postgres-data`. O contêiner pode ser recriado que os dados continuam. Só `docker compose down -v` apaga o volume.

**Dockerfile multi-stage.**
1. Estágio `build`: usa a imagem `sdk:8.0` (1,23 GB), restaura os pacotes e compila.
2. Estágio `final`: usa a imagem `aspnet:8.0-alpine` (158 MB), que só **roda** .NET, e copia apenas as DLLs publicadas. O SDK e o código-fonte não vão para a imagem final.

**Cache de camadas.** O Dockerfile copia **primeiro só o `.csproj`** e roda `dotnet restore`, e só depois copia o resto do código. Quando só o código muda, o Docker reaproveita a camada de restore e não baixa os pacotes de novo.

**Usuário não-root.** `USER $APP_UID` faz o processo rodar como `app` (uid 1654), usuário que já vem na imagem oficial. Se alguém invadir a API, não é root dentro do contêiner.

**Configuração por ambiente.** Nenhuma senha está no código nem no `appsettings.json`. O `.env` (fora do git) alimenta o `docker-compose.yml`, que repassa os valores como variáveis de ambiente para os contêineres. O .NET lê `ConnectionStrings__Default` como se fosse `ConnectionStrings:Default` do appsettings.

## Checklist da Etapa 2 — evidências

| # | Requisito | Onde / como comprovar |
|---|---|---|
| 1 | Um Dockerfile por serviço (mín. 3) | `src/*/Dockerfile` |
| 2 | Multi-stage | dois `FROM` em cada Dockerfile (`build` e `final`) |
| 3 | Imagem final enxuta, sem SDK/fonte | `docker images` → 171 MB (SDK: 1,23 GB) |
| 4 | Usuário não-root | `docker compose exec flooding-api id` → `uid=1654(app)` |
| 5 | Imagens versionadas por tag | `docker images` → `aps-sd/*:1.0.0` (`APP_VERSION` no `.env`) |
| 6 | `.dockerignore` | `src/*/.dockerignore` (exclui `bin/`, `obj/`, `.git`) |
| 7 | Compose sobe a pilha completa | `docker compose up -d` |
| 8 | Comunicação por nome | `Host=postgres` no `docker-compose.yml` |
| 9 | Volume: dados sobrevivem ao restart | `docker compose restart` e depois `GET /alerts` continua retornando os dados |
| 10 | Config por variáveis de ambiente | `.env.example` versionado, `.env` no `.gitignore` |
| 11 | Nenhuma credencial no código | senha só no `.env` |
| 12 | Liveness e readiness distintos | `curl localhost:5002/health/live` e `/health/ready` |
| 13 | Cliente leve consumindo a API | Swagger UI (`/swagger`); um cliente dedicado pode ser adicionado |

### Dados para a ficha (seções 5 e 6)

| Serviço | Linguagem/runtime | Imagem:tag | Tamanho | Imagem base do runtime |
|---|---|---|---|---|
| air-quality-api | C# / .NET 8 | `aps-sd/air-quality-api:1.0.0` | 171 MB | `aspnet:8.0-alpine` (158 MB) |
| flooding-api | C# / .NET 8 | `aps-sd/flooding-api:1.0.0` | 171 MB | `aspnet:8.0-alpine` (158 MB) |
| thermal-inversion-api | C# / .NET 8 | `aps-sd/thermal-inversion-api:1.0.0` | 171 MB | `aspnet:8.0-alpine` (158 MB) |

| Componente | Imagem | Volume | Observação |
|---|---|---|---|
| Banco de dados | `postgres:16-alpine` | `postgres-data` | 1 instância, 1 banco por API |
