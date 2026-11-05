# Guia de funcionamento do sistema e tour pelo código

Este guia foi escrito para explicar o código em voz alta. Comece pelo caminho de uma requisição, depois abra os arquivos na ordem indicada. A implementação está na cópia `aps-8sem-sd`; o original em `Documents` não foi alterado.

## 1. Resumo em uma frase

O sistema recebe leituras ambientais por HTTP, valida o JSON, grava as medidas no PostgreSQL, avalia regras de alerta e devolve a resposta ao cliente. Docker Compose organiza os contêineres no desenvolvimento local; Kubernetes organiza réplicas, rede, entrada, armazenamento e escala no cluster. Um gerador separado envia carga e registra os dados necessários para analisar desempenho.

```text
sensor / cliente / loadgen
          │ POST ou GET
          ▼
     Ingress (no cluster)
          │ escolhe o domínio pela URL
          ▼
     Service Kubernetes
          │ seleciona um pod pronto
          ▼
   API REST em .NET 8 ─────► Redis (cache de consultas, se ativado)
          │
          ├── regra de alerta do domínio
          ▼
   PostgreSQL ─────────────► leitura e alerta persistidos
          │
          ▼
  HTTP status + JSON + X-Pod + X-Versao
```

No Compose, o Ingress e os Services Kubernetes não existem: o host acessa cada API por uma porta publicada. O caminho para o banco e Redis usa DNS interno do Compose (`postgres`, `redis`).

## 2. Exemplo completo: uma leitura do nível da água

O endpoint de ingestão é `POST /api/v1/flooding/water-level`. Corpo de exemplo:

```json
{
  "monitoringPointId": "PT-01",
  "sensorId": "SEN-N-01",
  "waterLevelCm": 320,
  "timestamp": "2026-11-05T10:00:00-03:00"
}
```

### Passo 1 — a rota encontra o controller

`[Route(ApiRoutes.Base + "/water-level")]` no [WaterLevelController.cs](src/Flooding.Api/Controllers/WaterLevelController.cs) combina com o prefixo versionado declarado em `ApiRoutes.cs`. O método `Create` com `[HttpPost]` recebe o JSON. `[ApiController]` ativa a conversão e validação automáticas dos campos do DTO; se faltar um campo obrigatório ou um valor estiver fora do `[Range]`, ASP.NET responde `400 Bad Request` antes de entrar no método.

### Passo 2 — DTO vira entidade

`CreateWaterLevelReadingRequest` é o formato da entrada HTTP. `WaterLevelReading` é a entidade que representa uma linha da tabela. O controller copia os valores, converte o timestamp para UTC (ou usa a hora atual) e adiciona a entidade ao `FloodingDbContext`.

### Passo 3 — EF Core grava

`SaveChangesAsync` transforma as alterações rastreadas pelo EF Core em SQL e envia ao PostgreSQL. O banco gera o `Id`. A leitura persistida já pode ser encontrada pela regra de alerta.

### Passo 4 — a regra decide se há um novo episódio

`AlertService.EvaluateWaterLevelAsync` compara o nível com a cota configurada. Se for maior, busca a leitura anterior do mesmo ponto:

- anterior abaixo (ou inexistente) → a cota acabou de ser cruzada: cria alerta;
- anterior já acima → o episódio já começou: não duplica o alerta;
- leitura atual igual/abaixo do limite → encerra a avaliação.

Essa regra é **síncrona**: a requisição só termina depois da avaliação. A leitura já foi gravada antes da regra rodar; se a gravação do alerta falhar, a leitura continua no banco.

### Passo 5 — HTTP responde

O controller devolve `201 Created`, o JSON da leitura e a URL do recurso criado. Um middleware em `Program.cs` inclui `X-Pod` e `X-Versao` no cabeçalho. No Kubernetes, `X-Pod` mostra qual réplica respondeu; `X-Versao` identifica a versão da imagem.

## 3. Por que existem DTO, model, DbContext e controller

| Peça | Função | Exemplo |
|---|---|---|
| DTO | Contrato que entra ou sai pela API; valida campos HTTP | `Dtos/CreateReadingRequests.cs` |
| Model/entidade | Forma dos dados persistidos e regras de índice/tamanho | `Models/WaterLevelReading.cs` |
| DbContext | Mapeia entidades e tabelas e coordena consultas/gravações | `Data/FloodingDbContext.cs` |
| Controller | Associa rota HTTP à operação; coordena DTO, banco e serviço | `Controllers/WaterLevelController.cs` |
| Service | Regra de negócio reutilizável, fora do controller | `Services/AlertService.cs` |
| Options | Limites configuráveis sem recompilar a regra | `Options/AlertOptions.cs` |

`UseSnakeCaseNamingConvention()` converte nomes C# como `WaterLevelReadings` e `MonitoringPointId` para nomes PostgreSQL como `water_level_readings` e `monitoring_point_id`. Os atributos `[Index]` nas entidades criam índices para os filtros frequentes por ponto/estação, sensor e horário.

## 4. As três regras de alerta

Os limites vêm de variáveis do ambiente, ligadas às classes `AlertOptions` nos `Program.cs`.

### Qualidade do ar

`AirQuality.Api/Services/AlertService.cs` gera alerta quando PM2.5 passa do limite por **N leituras seguidas da mesma estação**. Ele busca N+1 medidas recentes: as N confirmam a sequência e a medida extra verifica se o episódio já estava em curso. O valor padrão é 25 µg/m³ por 3 leituras.

Exemplo com limite 25 e N=3: `27, 31, 34` gera um alerta na terceira medida; `36, 39` não duplicam; uma leitura abaixo do limite encerra o episódio.

### Alagamento

`Flooding.Api/Services/AlertService.cs` alerta quando o nível **cruza** a cota. O padrão é 300 cm. Leituras seguintes acima da cota pertencem ao mesmo episódio; uma nova travessia só gera outro alerta depois que o nível volta para baixo.

### Inversão térmica

`ThermalInversion.Api/Services/AlertService.cs` calcula `temperatura superior − temperatura da superfície`. Se o gradiente passa do limite configurado, há inversão; o alerta é emitido quando o episódio começa, não a cada leitura positiva.

## 5. O que acontece quando uma API inicia

Abra qualquer um dos três `Program.cs`; eles têm o mesmo esqueleto:

1. `WebApplication.CreateBuilder` carrega configuração (ambiente, arquivos e padrões).
2. `GetConnectionString("Default")` busca `ConnectionStrings__Default`; a senha não é escrita no código.
3. `AddDbContext` registra EF Core e Npgsql para o banco lógico daquela API.
4. `Configure<AlertOptions>` liga variáveis como `Alerts__OverflowLevelCm` à regra.
5. `AddScoped<AlertService>` registra a regra para ser criada dentro do escopo de cada requisição.
6. `AddHealthChecks().AddDbContextCheck(...)` cria o teste de conectividade do banco usado pela readiness.
7. `Build` monta a aplicação e `DatabaseInitializer.InitializeAsync` espera o PostgreSQL e cria as tabelas se não existirem.
8. Middlewares registram cabeçalhos, Swagger e (se `CACHE_ENABLED=true`) Output Cache.
9. `MapControllers` publica as rotas; os dois health checks são mapeados; `Run` começa a ouvir HTTP.

O initializer usa `EnsureCreated`, que é conveniente para a APS e bancos novos. Não substitui migrations em uma aplicação com evolução controlada de schema: ele não altera automaticamente tabelas existentes.

### Liveness e readiness

- `/health/live`: responde se o processo está vivo; não pergunta ao banco. Falha faz o orquestrador reiniciar o contêiner.
- `/health/ready`: verifica PostgreSQL. Falha tira o pod do balanceamento sem reiniciar automaticamente o processo.

Separar os dois evita reiniciar todas as APIs quando a dependência comum está temporariamente fora do ar.

## 6. Cache de consultas

As rotas agregadas de qualidade do ar e perfil térmico usam `[OutputCache(Duration = 15)]`. Com `CACHE_ENABLED=false`, a requisição sempre executa a consulta no PostgreSQL. Com `true`, o middleware pode responder do Redis por até 15 segundos.

No início do `Program.cs`, `AddStackExchangeRedisOutputCache` configura Redis como armazenamento compartilhado. `UseOutputCache` adiciona o middleware ao fluxo HTTP. Isso deixa uma resposta disponível para as réplicas da mesma API, mas pode retornar dados até 15 s antigos. Redis é uma instância única local, sem alta disponibilidade. A ingestão e os alertas permanecem síncronos.

## 7. Compose: execução de desenvolvimento

O [docker-compose.yml](docker-compose.yml) declara os serviços e as conexões:

- `postgres`: um contêiner PostgreSQL com volume nomeado `postgres-data`; guarda três bancos lógicos, um para cada API;
- `redis`: backend efêmero do cache, sem persistência de dados;
- três APIs: cada uma constrói sua imagem, recebe sua connection string, portas públicas e limites de alerta;
- `load-generator`: gerador antigo de leituras sintéticas; pertence ao profile `load`, portanto não inicia no `docker compose up` padrão.

Os serviços ficam na rede `backend`. Dentro dessa rede, a API usa `Host=postgres`, não `localhost`: `localhost` dentro de um contêiner apontaria para o próprio contêiner. `depends_on` com `service_healthy` espera os health checks do Postgres e Redis. Reiniciar ou recriar a API não apaga o volume; `docker compose down -v` apaga.

Cada Dockerfile tem dois estágios. `sdk:8.0` restaura e compila; `aspnet:8.0-alpine` recebe só o publish e roda como usuário não-root. `APP_VERSION` é inserida na imagem e aparece em `X-Versao`.

## 8. Kubernetes: execução distribuída

Os manifestos em `k8s/` expressam estado desejado. `kubectl apply` registra os objetos; controladores do Kubernetes tentam continuamente chegar a esse estado.

| Arquivo | O que declara |
|---|---|
| `00-namespace.yaml` | Isola os recursos no namespace `aps`. |
| `01-postgres-init.yaml` | Script que cria os três bancos na primeira inicialização do volume. |
| `02-postgres.yaml` | Serviço headless, Service do banco, StatefulSet e PVC de dados. |
| `03-config.yaml` | ConfigMap com a chave que liga/desliga o cache. |
| `04-redis.yaml` | Redis e Service DNS `redis:6379`. |
| `10`–`12` | Deployment + Service de cada API, imagem fixa, recursos, probes e Secret da conexão. |
| `20-ingress.yaml` | Roteia os prefixos de URL para os três Services. |
| `30-hpa-flooding.yaml` | Escala `flooding-api` entre 2 e 10 pods conforme CPU. |
| `31-pdb-flooding.yaml` | Mantém ao menos um pod disponível em interrupções voluntárias. |

Um Deployment controla pods sem identidade fixa. O Service seleciona pods pelas labels e envia tráfego aos prontos. O Ingress encaminha `/api/v1/flooding/...` para o Service correto. As probes consultam `/health/live` e `/health/ready`. Recursos `requests` participam do agendamento e da conta do HPA; `limits` restringem o máximo de CPU/memória do contêiner.

PostgreSQL é StatefulSet com uma instância e PVC: recriar seu pod preserva dados, mas o banco não tem alta disponibilidade. Redis também é uma instância. O Secret é criado localmente pelo script `scripts/create-k8s-secret.ps1`, a partir de `.env`; valores reais não ficam nos YAMLs versionados.

## 9. Dois geradores, dois propósitos

### `tools/load-generator/generator.py`: gerar leituras simuladas

Simula estações e variáveis ambientais plausíveis (passeio aleatório e episódios de poluição/chuva/inversão). Envia POSTs às três APIs a uma taxa configurada. Serve para popular/alimentar o sistema; não implementa todo o protocolo de medição da ficha da Etapa 4.

### `carga/loadgen.py`: medir o sistema

Este é o gerador de ensaio da APS. O primeiro argumento é a URL completa, que nos ensaios do cluster deve ser o Ingress. `-c` define clientes concorrentes, `-d` define duração, `--rampa` aumenta os trabalhadores ao longo do tempo e `--degraus 1,2,4,...` executa níveis sucessivos.

Por dentro:

1. `argparse` lê e valida parâmetros; o cabeçalho JSON e o corpo de POST são montados.
2. `Sender` abre uma conexão HTTP por thread e a reaproveita com keep-alive. A duração é medida com `perf_counter`; timestamp de parede, status e headers são guardados.
3. Cada trabalhador opera em laço fechado: envia uma requisição, aguarda resposta, registra e só então envia outra. Timeout, conexão recusada e status HTTP ≥400 entram como erro.
4. `run_stage` controla quantos loops estão ativos e, a cada segundo, escreve uma amostra para a linha do tempo.
5. `percentile` usa nearest-rank; `summarize` calcula p50/p95/p99, média, vazão bem-sucedida, taxa de erro e contagens por status, pod e versão.
6. No fim, cada execução salva CSV por requisição, CSV por segundo e JSON de resumo em `resultados/`.

**Trabalhadores não são req/s.** Um trabalhador é uma sessão que aguarda cada resposta; a vazão observada depende da latência e da capacidade da aplicação. O gerador preserva as falhas no total. A vazão considera apenas respostas 2xx.

`carga/plot_results.py` lê esses arquivos e gera PNG para linha de base, comparação e série temporal. Requer matplotlib, instalado por `python -m pip install -r carga/requirements.txt`.

## 10. Como ler os experimentos da Etapa 5

Abra `experimentos/README.md` para os comandos completos. As variáveis mudam uma de cada vez:

- escala manual: 1/2/4/8 réplicas, HPA removido;
- HPA: rampa de carga e anotações de decisão, prontidão dos pods e retorno de latência;
- resiliência: remover um pod e drenar um nó sob carga constante;
- atualização: alterar imagem durante a carga, contar erros e versões, depois `rollout undo`;
- cache: mesma consulta, carga e número de réplicas, Redis ligado e desligado.

Use pelo menos três repetições, descarte o aquecimento, registre CPU/RAM e guarde os arquivos brutos. Não copie números de exemplo da ficha como resultado do grupo.

## 11. Tour de código sugerido para a apresentação

Em 5–7 minutos, abra os arquivos nesta ordem:

1. `src/Flooding.Api/Program.cs` — composição da API e dependências.
2. `src/Flooding.Api/Controllers/WaterLevelController.cs` — entrada POST, EF Core e resposta 201.
3. `src/Flooding.Api/Dtos/CreateReadingRequests.cs` — contrato e validação da entrada.
4. `src/Flooding.Api/Models/WaterLevelReading.cs` + `Data/FloodingDbContext.cs` — entidade, índices e tabela.
5. `src/Flooding.Api/Services/AlertService.cs` — regra de cruzamento da cota.
6. `docker-compose.yml` — rede, nomes DNS, health checks e volume.
7. `k8s/11-flooding.yaml`, `20-ingress.yaml` e `30-hpa-flooding.yaml` — réplica, entrada e escala.
8. `carga/loadgen.py` (`Sender`, `run_stage`, `summarize`) — como o grupo mede em vez de apenas declarar desempenho.

## 12. Limites que devem ser explicados

- A fila de mensagens ainda não está integrada; regras de alerta são síncronas no POST.
- Banco e Redis têm uma instância no cluster local. Replicar as APIs não replica o banco.
- Output Cache pode devolver resposta de até 15 s atrás.
- A cópia contém código e procedimentos de medição, mas os valores de vazão, percentis, falhas e recuperação precisam vir de execução real. Não foram fabricados neste guia.
