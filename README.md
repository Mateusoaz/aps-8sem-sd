# APS 2026 — Gerenciamento de Informações Ambientais Urbanas

Três APIs REST em **.NET 8 (C#)**, cada uma cuidando de um domínio ambiental, gravando num **PostgreSQL**, tudo rodando em contêineres Docker orquestrados pelo **Docker Compose**.

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
 │  air-quality-api :8080 ─┐                                            │
 │  flooding-api    :8080 ─┼──► postgres:5432 ──► volume postgres-data  │
 │  thermal-inv-api :8080 ─┘    (3 bancos, 1 por API)                   │
 └──────────────────────────────────────────────────────────────────────┘
      ▲ 5001        ▲ 5002        ▲ 5003        ▲ 5432
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

Depois abra o Swagger de cada API para testar pelo navegador:

- http://localhost:5001/swagger — Qualidade do ar
- http://localhost:5002/swagger — Alagamento
- http://localhost:5003/swagger — Inversão térmica

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

## Estrutura do repositório

```
aps-8sem-sd/
├── docker-compose.yml          # sobe a pilha inteira
├── .env.example                # modelo das variáveis (o .env real não vai pro git)
├── ApsSd.sln                   # abre as 3 APIs juntas no Visual Studio/Rider
├── tools/
│   └── load-generator/         # gerador de carga em Python (dados aleatórios)
└── src/
    ├── AirQuality.Api/
    ├── Flooding.Api/
    └── ThermalInversion.Api/
        ├── Dockerfile          # build multi-stage
        ├── .dockerignore
        ├── Program.cs          # configuração: banco, health checks, swagger
        ├── ApiRoutes.cs        # prefixo das rotas (api/v1/<domínio>)
        ├── Controllers/        # rotas HTTP
        ├── Models/             # entidades = tabelas do banco
        ├── Dtos/               # formato do que entra (POST) e sai (respostas agregadas)
        ├── Data/               # DbContext, criação do banco, filtros reutilizáveis
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

| Rota | Pergunta | Verifica o banco? | Se falhar... |
|---|---|---|---|
| `/health/live` | O processo está vivo? | Não | o orquestrador **reinicia** o contêiner |
| `/health/ready` | Está apto a receber tráfego? | Sim | o orquestrador **tira do balanceamento** |

O liveness **não pode** consultar o banco. Se consultasse, uma queda rápida do banco faria o orquestrador reiniciar todas as réplicas ao mesmo tempo, e um incidente pequeno virava queda total.

## Regras de alerta

Limites configuráveis pelo `.env`, sem recompilar:

| API | Regra | Variável |
|---|---|---|
| Qualidade do ar | PM2.5 acima do limite por **N leituras seguidas** da mesma estação | `AIR_PM25_LIMIT`, `AIR_PM25_CONSECUTIVE_READINGS` |
| Alagamento | nível da água **cruza** a cota de transbordamento | `FLOODING_OVERFLOW_LEVEL_CM` |
| Inversão térmica | temp. superior **maior** que a da superfície | `THERMAL_MIN_INVERSION_GRADIENT_C` |

O alerta é gerado **uma vez por episódio**, e não a cada leitura acima do limite. Exemplo com cota de 300 cm e leituras 250 → 320 → 350 → 200 → 310: são emitidos 2 alertas, um no 320 e outro no 310.

Por enquanto a regra roda dentro do próprio POST. Numa etapa futura ela vai para um serviço separado, alimentado por uma **fila de mensagens**, que é o processamento assíncrono pedido pela APS.

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
