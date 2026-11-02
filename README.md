# APS 2026 — Gerenciamento de Informações Ambientais Urbanas

Três APIs REST em **.NET 8 (C#)**, cada uma cuidando de um domínio ambiental, gravando num **PostgreSQL**, com cache no **Redis**, fila no **RabbitMQ** e um cliente web leve. Tudo roda em contêineres: no **Docker Compose** (desenvolvimento) ou num cluster **Kubernetes** (Etapa 3).

| API | Domínio | Porta (host) | Banco |
|---|---|---|---|
| `air-quality-api` | Qualidade do ar | 5001 | `air_quality` |
| `flooding-api` | Alagamento e inundação | 5002 | `flooding` |
| `thermal-inversion-api` | Inversão térmica | 5003 | `thermal_inversion` |

```
                        docker compose (projeto "aps-sd")
 ┌──────────────────────────────────────────────────────────────────────┐
 │  rede "backend" (DNS interno: cada serviço é achado pelo NOME)       │
 │                                                                      │
 │  web-client :80 (página + encaminha os prefixos para as APIs)        │
 │       │                                                              │
 │  air-quality-api :8080 ─┐    ┌─► postgres:5432 ─► volume postgres-data
 │  flooding-api    :8080 ─┼────┼─► redis:6379     (cache das consultas)│
 │  thermal-inv-api :8080 ─┘    └─► rabbitmq:5672  (fila dos alertas)   │
 └──────────────────────────────────────────────────────────────────────┘
   ▲ 8080     ▲ 5001   ▲ 5002   ▲ 5003     ▲ 5432      ▲ 15672
   └──────── portas publicadas no seu computador (localhost) ────────┘
```

## Como rodar (máquina limpa)

Só precisa de **Docker** instalado. O .NET SDK não é necessário na máquina: o build acontece dentro do contêiner.

```bash
git clone <repositório>
cd aps-8sem-sd
cp .env.example .env
docker compose up -d --build
```

Depois abra no navegador:

- http://localhost:8080 — **cliente web** (leituras, alertas e qual instância respondeu)
- http://localhost:5001/swagger — Qualidade do ar
- http://localhost:5002/swagger — Alagamento
- http://localhost:5003/swagger — Inversão térmica
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

## Kubernetes (Etapa 3)

A mesma pilha num cluster local de 3 nós (k3d). Precisa de **Docker**, **kubectl** e **k3d** (v5+). No Windows, rode no **Git Bash**.

```bash
# 1. cluster: 1 servidor + 2 agentes; a porta 8081 da máquina chega ao Ingress
k3d cluster create aps --agents 2 -p "8081:80@loadbalancer"

# 2. construir as imagens e importá-las nos nós (o cluster não enxerga as imagens do Docker)
docker build --build-arg APP_VERSION=1.1.0 -t aps-sd/air-quality-api:1.1.0       ./src/AirQuality.Api
docker build --build-arg APP_VERSION=1.1.0 -t aps-sd/flooding-api:1.1.0          ./src/Flooding.Api
docker build --build-arg APP_VERSION=1.1.0 -t aps-sd/thermal-inversion-api:1.1.0 ./src/ThermalInversion.Api
docker build -t aps-sd/web-client:1.1.0 ./src/WebClient
k3d image import aps-sd/air-quality-api:1.1.0 aps-sd/flooding-api:1.1.0 \
  aps-sd/thermal-inversion-api:1.1.0 aps-sd/web-client:1.1.0 -c aps

# 3. namespace, Secret (a partir do .env, que não vai para o Git) e o resto
cp .env.example .env
kubectl apply -f k8s/00-namespace.yaml
kubectl create secret generic banco-credenciais -n aps --from-env-file=.env
kubectl apply -f k8s/
kubectl rollout status deployment/air-quality-api -n aps
```

> Postgres, Redis e RabbitMQ são baixados pelo próprio cluster na primeira vez (1 a 3 minutos). Enquanto isso as APIs ficam `0/1`, esperando o banco — é a startup probe funcionando, não um erro.

Tudo entra pelo **Ingress** (gateway único), roteado por caminho. O prefixo vem antes da rota normal da API:

| Serviço | Prefixo no gateway | Endereço |
|---|---|---|
| Cliente web | `/` | http://localhost:8081 |
| Qualidade do ar | `/air-quality` | http://localhost:8081/air-quality/swagger |
| Alagamento | `/flooding` | http://localhost:8081/flooding/swagger |
| Inversão térmica | `/thermal-inversion` | http://localhost:8081/thermal-inversion/swagger |

```bash
curl -s http://localhost:8081/air-quality/health/ready
curl -s http://localhost:8081/air-quality/api/v1/air-quality/particulate

# quem atendeu? cada resposta traz o pod (X-Pod) e a versão da imagem (X-Versao)
for i in $(seq 10); do
  curl -s -o /dev/null -D - http://localhost:8081/air-quality/health/live | grep -i x-pod
done | sort | uniq -c

# cache: a 1ª chamada é MISS, as seguintes HIT — mesmo caindo em pods diferentes
curl -s -o /dev/null -D - http://localhost:8081/air-quality/api/v1/air-quality/areas/CENTRO/average | grep -iE "x-cache|x-pod"

# fila: quantas mensagens esperando e quantos consumidores (um por pod de API)
kubectl exec -n aps rabbitmq-0 -- rabbitmqctl -q list_queues name messages consumers

# gerador de carga pelo gateway
python tools/load-generator/generator.py --rate 100 --duration 60 \
  --air-url http://localhost:8081/air-quality \
  --flooding-url http://localhost:8081/flooding \
  --thermal-url http://localhost:8081/thermal-inversion
```

| Arquivo | O que cria |
|---|---|
| `k8s/00-namespace.yaml` | namespace `aps` |
| `k8s/01-configmap.yaml` | configuração comum (hosts, tempo do cache, limites de alerta) |
| `k8s/10-postgres.yaml` | Service headless + StatefulSet do PostgreSQL, com volume de 1 GiB |
| `k8s/11-redis.yaml` | Deployment + Service do Redis (cache, sem volume) |
| `k8s/12-rabbitmq.yaml` | Service headless + StatefulSet do RabbitMQ, com volume de 1 GiB |
| `k8s/20…22-*-api.yaml` | Deployment (2 réplicas, rolling update, probes, `preStop`, requests/limits) + Service de cada API |
| `k8s/23-web-client.yaml` | Deployment (2 réplicas) + Service do cliente web |
| `k8s/30-ingress.yaml` | gateway: os três prefixos das APIs e `/` para o cliente |
| `k8s/40-hpa.yaml` | HPA da API de qualidade do ar (2 a 10 réplicas, CPU a 50%) |
| `secret.example.yaml` | modelo do Secret — documentação, **não** é aplicado |

As evidências dos experimentos (saídas reais) e o diagrama de implantação estão em [`docs/etapa3/`](docs/etapa3/README.md).

`GET /<prefixo>/processar?n=2000000` gasta CPU de propósito, para acionar o HPA. Para limpar: `kubectl delete namespace aps` (apaga a aplicação e os volumes) e `k3d cluster delete aps`.

## Cache e fila

**Cache (Redis).** As consultas agregadas mais pedidas ficam guardadas por alguns segundos (`CACHE_TTL_SECONDS`, padrão 10). É o padrão *cache-aside*: procura no Redis; se não achar, consulta o banco e guarda.

| API | Consulta com cache |
|---|---|
| Qualidade do ar | `GET /areas/{areaId}/average` |
| Alagamento | `GET /monitoring-points/{id}/latest` |
| Inversão térmica | `GET /areas/{areaId}/thermal-profile` |

A resposta leva o cabeçalho `X-Cache`: `HIT` (veio do cache), `MISS` (veio do banco) ou `BYPASS` (Redis fora do ar, foi direto ao banco). Como o cache fica **fora** dos pods, o que um pod guardou vale para todas as réplicas. O preço é o dado poder estar até 10 s desatualizado.

**Fila (RabbitMQ).** O POST da leitura que gera alerta (`particulate`, `water-level`, `temperature-profile`) grava no banco, publica o id da leitura numa fila e responde. A regra de alerta roda depois, num consumidor em segundo plano (`Messaging/AlertConsumer.cs`).

- Cada réplica da API consome a **mesma** fila (consumidores concorrentes): o RabbitMQ entrega cada mensagem a apenas uma delas.
- Fila durável, mensagem persistente e ack manual: se o pod morrer no meio, a mensagem volta para a fila. A garantia é "ao menos uma vez", então uma reentrega pode, em caso raro, repetir um alerta.
- Se o RabbitMQ estiver fora, o POST não falha: o alerta é avaliado ali mesmo, como antes.

Por isso o `/health/ready` verifica **só o banco**: sem cache ou sem fila a API continua atendendo, só que de forma degradada.

## Gerador de carga e linha de base (Etapa 4)

`carga/loadgen.py` é o gerador usado nas medições. Diferente do `tools/load-generator/generator.py`, que simula sensores a uma taxa fixa, ele trabalha em **laço fechado**: cada trabalhador envia uma requisição, espera a resposta, anota e só então envia a próxima. Usa só a biblioteca padrão do Python e aceita apenas alvos em `localhost`.

```bash
# 8 trabalhadores por 20 s, em uma rota de consulta
python carga/loadgen.py http://localhost:8081/flooding/health/live -c 8 -d 20

# ingestão: uma leitura diferente a cada POST
python carga/loadgen.py http://localhost:8081/air-quality/api/v1/air-quality/particulate --payload ar -c 8 -d 20

# degraus de carga, 30 s cada, descartando 5 s de aquecimento
python carga/loadgen.py http://localhost:8081/air-quality/api/v1/air-quality/particulate   --payload ar --degraus 1,2,4,8,16,32,64 -d 30 --aquecimento 5 --prefixo base/teste
```

Cada execução grava em `resultados/` um CSV por requisição, um CSV por segundo e um JSON com o resumo.

Para repetir a linha de base, deixe 1 réplica de cada serviço e remova o HPA. No fim, `kubectl apply -f k8s/` restaura o cluster.

```bash
kubectl delete hpa air-quality-api -n aps
kubectl scale deployment air-quality-api flooding-api thermal-inversion-api web-client -n aps --replicas=1
bash carga/linha_base.sh
python carga/analisa_base.py
```

**Resultado:** com 1 réplica e limite de 500m de CPU, a ingestão chegou a **832 req/s com p95 de 108 ms** em 64 trabalhadores, sem erros. Em 128 trabalhadores, 96% das requisições receberam `503`. O recurso que saturou foi a CPU do pod. Esse valor não é sustentável, porque a fila de alertas acumulou 56 mil mensagens; ela só acompanhou até cerca de 240 req/s. Análise completa em [`docs/etapa4/`](docs/etapa4/README.md).

## Experimentos de escalabilidade e resiliência (Etapa 5)

`carga/experimentos.py` executa os cenários e grava tudo em `resultados/etapa5/`. Ele usa 4 processos do gerador e pula o que já terminou, então pode ser retomado. O rolling update precisa da imagem `1.2.0` no cluster.

```bash
docker build --build-arg APP_VERSION=1.2.0 -t aps-sd/air-quality-api:1.2.0 ./src/AirQuality.Api
k3d image import aps-sd/air-quality-api:1.2.0 -c aps

python carga/experimentos.py 5.3 5.4 5.5 5.1b 5.1g 5.2b   # cenários com o pool corrigido, sem as rodadas antigas
python carga/analisa_etapa5.py                            # tabelas e gráficos
```

| Experimento | Resultado |
|---|---|
| Escala manual (POST, 64 trabalhadores) | 616 req/s com 1 réplica e 1.378 com 4, ganho de 2,24×; o banco chegou ao limite de CPU |
| HPA | De 2 para 10 réplicas em 59 s, 0 falhas em 244.835 requisições |
| Pod apagado | 0 a 29 falhas, substituto pronto em 4 a 5 s |
| Nó drenado sem banco | 6 falhas em 56.713 requisições |
| Nó drenado com banco | Cerca de 53 s fora do ar, porque o volume está preso ao nó |
| Rolling update | 0 falhas com `preStop`; 24 a 47 sem ele |
| Fila × síncrono | Com fila o p50 é menor, mas o trabalho só é adiado (cerca de 34 mil mensagens pendentes) |

Os testes revelaram um defeito: cada pod podia abrir até 100 conexões, e as réplicas esgotavam as 100 vagas do PostgreSQL, derrubando todos os pods ao mesmo tempo. Por isso os manifestos das APIs usam `Maximum Pool Size=8`, e também um `preStop` de 5 s, que elimina as falhas na troca de versão.

Hipóteses em [`docs/etapa5/hipoteses.md`](docs/etapa5/hipoteses.md) e análise em [`docs/etapa5/`](docs/etapa5/README.md). Os CSVs por requisição estão compactados (`.csv.gz`).

## Estrutura do repositório

```
aps-8sem-sd/
├── docker-compose.yml          # sobe a pilha inteira
├── k8s/                        # manifestos do Kubernetes
├── docs/                       # evidências e análises das Etapas 3, 4 e 5
├── carga/                      # gerador de carga, linha de base e experimentos
├── resultados/                 # dados brutos das Etapas 4 e 5
├── secret.example.yaml         # modelo do Secret (o real vem do .env)
├── .env.example                # modelo das variáveis (o .env real não vai pro git)
├── ApsSd.sln                   # abre as 3 APIs juntas no Visual Studio/Rider
├── tools/
│   └── load-generator/         # gerador de carga em Python (dados aleatórios)
└── src/
    ├── WebClient/              # cliente leve: index.html servido por nginx
    ├── AirQuality.Api/
    ├── Flooding.Api/
    └── ThermalInversion.Api/
        ├── Dockerfile          # build multi-stage
        ├── .dockerignore
        ├── Program.cs          # configuração: banco, cache, fila, health checks, swagger
        ├── ApiRoutes.cs        # prefixo das rotas (api/v1/<domínio>)
        ├── Controllers/        # rotas HTTP
        ├── Models/             # entidades = tabelas do banco
        ├── Dtos/               # formato do que entra (POST) e sai (respostas agregadas)
        ├── Data/               # DbContext, criação do banco, filtros reutilizáveis
        ├── Services/           # regra de alerta e cache das consultas
        ├── Messaging/          # fila: publicação da leitura e consumidor dos alertas
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

| Rota | Pergunta | Verifica o banco? | Se falhar... |
|---|---|---|---|
| `/health/live` | O processo está vivo? | Não | o orquestrador **reinicia** o contêiner |
| `/health/ready` | Está apto a receber tráfego? | Sim, a cada chamada | o orquestrador **tira do balanceamento** |

O liveness **não pode** consultar o banco. Se consultasse, uma queda rápida do banco faria o orquestrador reiniciar todas as réplicas ao mesmo tempo, e um incidente pequeno virava queda total.

## Regras de alerta

Limites configuráveis pelo `.env`, sem recompilar:

| API | Regra | Variável |
|---|---|---|
| Qualidade do ar | PM2.5 acima do limite por **N leituras seguidas** da mesma estação | `AIR_PM25_LIMIT`, `AIR_PM25_CONSECUTIVE_READINGS` |
| Alagamento | nível da água **cruza** a cota de transbordamento | `FLOODING_OVERFLOW_LEVEL_CM` |
| Inversão térmica | temp. superior **maior** que a da superfície | `THERMAL_MIN_INVERSION_GRADIENT_C` |

O alerta é gerado **uma vez por episódio**, e não a cada leitura acima do limite. Exemplo com cota de 300 cm e leituras 250 → 320 → 350 → 200 → 310: são emitidos 2 alertas, um no 320 e outro no 310.

A regra roda **fora do POST**: a leitura é publicada numa fila e um consumidor avalia o alerta (veja [Cache e fila](#cache-e-fila)). É o processamento assíncrono pedido pela APS.

## Convenções de nomenclatura

| Onde | Padrão | Exemplo |
|---|---|---|
| Rotas HTTP | kebab-case, recurso no singular/plural consistente, versão no prefixo | `/api/v1/flooding/water-level` |
| JSON | camelCase | `waterLevelCm`, `monitoringPointId` |
| C# (classes, propriedades) | PascalCase | `WaterLevelReading.WaterLevelCm` |
| Projetos .NET | `Dominio.Api` | `Flooding.Api` |
| Serviços do Compose / imagens | kebab-case | `flooding-api`, `aps-sd/flooding-api:1.1.0` |
| Banco (tabelas, colunas) | snake_case | `water_level_readings.monitoring_point_id` |
| Variáveis de ambiente | MAIÚSCULAS_COM_UNDERSCORE | `FLOODING_OVERFLOW_LEVEL_CM` |
| Config .NET via env | seção + `__` + chave | `ConnectionStrings__Default`, `Alerts__OverflowLevelCm` |
| Campos com medida | **unidade no nome** | `rainfallMm`, `pressureHpa`, `windSpeedMs` |
| Tipos de alerta | MAIÚSCULAS_COM_UNDERSCORE | `WATER_LEVEL_ABOVE_OVERFLOW` |

## Como funciona — conceitos

**Compose não é "contêiner dentro de contêiner".** O `docker-compose.yml` descreve 7 contêineres **irmãos** (postgres, redis, rabbitmq, 3 APIs e o cliente web) e o Compose sobe todos juntos, com um comando. Eles ficam numa rede virtual própria (`backend`) com DNS interno. Por isso a API encontra o banco pelo nome `postgres` (`Host=postgres`), sem IP fixo e sem `localhost`. Dentro de um contêiner, `localhost` é o **próprio** contêiner.

**`depends_on` + `healthcheck`.** As APIs só iniciam depois que o Postgres responde ao `pg_isready`. Mesmo assim, a API tem sua própria lógica de nova tentativa (`DatabaseInitializer`), porque no Kubernetes (etapa 3) não existe `depends_on`.

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
| 5 | Imagens versionadas por tag | `docker images` → `aps-sd/*:1.1.0` (`APP_VERSION` no `.env`) |
| 6 | `.dockerignore` | `src/*/.dockerignore` (exclui `bin/`, `obj/`, `.git`) |
| 7 | Compose sobe a pilha completa | `docker compose up -d` |
| 8 | Comunicação por nome | `Host=postgres` no `docker-compose.yml` |
| 9 | Volume: dados sobrevivem ao restart | `docker compose restart` e depois `GET /alerts` continua retornando os dados |
| 10 | Config por variáveis de ambiente | `.env.example` versionado, `.env` no `.gitignore` |
| 11 | Nenhuma credencial no código | senha só no `.env` |
| 12 | Liveness e readiness distintos | `curl localhost:5002/health/live` e `/health/ready` |
| 13 | Cliente leve consumindo a API | Cliente web em `src/WebClient/` e Swagger UI (`/swagger`) |

### Dados para a ficha (seções 5 e 6)

Tamanhos medidos na Etapa 2, com as imagens `1.0.0`. A versão atual é a `1.1.0`.

| Serviço | Linguagem/runtime | Imagem:tag | Tamanho | Imagem base do runtime |
|---|---|---|---|---|
| air-quality-api | C# / .NET 8 | `aps-sd/air-quality-api:1.0.0` | 171 MB | `aspnet:8.0-alpine` (158 MB) |
| flooding-api | C# / .NET 8 | `aps-sd/flooding-api:1.0.0` | 171 MB | `aspnet:8.0-alpine` (158 MB) |
| thermal-inversion-api | C# / .NET 8 | `aps-sd/thermal-inversion-api:1.0.0` | 171 MB | `aspnet:8.0-alpine` (158 MB) |

| Componente | Imagem | Volume | Observação |
|---|---|---|---|
| Banco de dados | `postgres:16-alpine` | `postgres-data` | 1 instância, 1 banco por API |
