# APS — APIs de Sistemas Distribuídos

O projeto contém quatro APIs independentes, todas em C#/.NET 9. Cada uma recebe dados de um sensor por `POST`, valida a origem, grava a leitura no seu SQLite local e responde com o identificador da ingestão.

| Pasta | Domínio | Porta | Rota POST |
|---|---|---:|---|
| `api1` | Qualidade do ar | 3001 | `/api/v1/sensores/sensor-ar-01/leituras` |
| `api2` | Alagamentos e inundações | 3002 | `/api/v1/sensores/sensor-agua-01/ocorrencias` |
| `api3` | Trânsito e transporte | 3003 | `/api/v1/sensores/sensor-radar-01/eventos` |
| `api4` | Inversão térmica | 3004 | `/api/v1/sensores/sensor-termico/leituras` |

## Requisitos

- .NET SDK 9 ou superior;
- Python 3.10 ou superior (apenas para os scripts de envio).

Para a execução com contêineres, basta ter Docker Desktop com Docker Compose; o .NET SDK não é necessário no computador que vai executar as imagens.

## Executar com Docker

Na raiz do projeto, no PowerShell:

```powershell
Copy-Item .env.example .env
docker compose up -d --build
docker compose ps
```

O Compose cria quatro imagens versionadas (`1.0.0`), uma por API, e quatro volumes nomeados independentes para os bancos SQLite. As APIs ficam disponíveis nas portas 3001 a 3004. Se uma porta do computador estiver ocupada, altere apenas o valor `API*_HOST_PORT` no arquivo `.env`. Esse arquivo não deve ser enviado ao GitHub.

Para verificar as rotas de saúde:

```powershell
Invoke-RestMethod http://127.0.0.1:3001/health/live
Invoke-RestMethod http://127.0.0.1:3001/health/ready
docker compose ps
```

Troque `3001` por `3002`, `3003` ou `3004` para conferir as demais APIs. `/health/live` indica que o processo está respondendo; `/health/ready` também consulta o SQLite e retorna HTTP 503 se ele estiver indisponível.

Os clientes Python continuam na máquina e podem enviar dados aos contêineres:

```powershell
python .\api1\scripts\enviar_dados.py --amostras 10 --docker
```

Troque `api1` por `api2`, `api3` ou `api4`. A opção `--docker` evita consultar o banco SQLite local: no Compose, ele fica no volume do serviço.

```powershell
docker compose logs api1
docker compose exec api1 id
docker compose down
```

`down` preserva os volumes, portanto os dados sobrevivem à recriação dos contêineres. **Não use `docker compose down -v` se quiser manter os bancos:** essa opção apaga os quatro volumes.

Nota: o roteiro da aula usa PostgreSQL, cache e fila em um projeto de exemplo. Este projeto usa SQLite embutido em cada API e ainda não tem cache nem fila; o Compose reflete a arquitetura real, sem criar serviços fictícios.

## Executar

Em terminais separados, inicie as APIs desejadas:

```powershell
.\api1\scripts\iniciar.bat
.\api2\scripts\iniciar.bat
.\api3\scripts\iniciar.bat
.\api4\scripts\iniciar.bat
```

Cada API cria automaticamente seu banco SQLite em `data/`. Não é necessário servidor de banco de dados.

Para enviar leituras de exemplo:

```powershell
python .\api1\scripts\enviar_dados.py --amostras 10
```

Troque `api1` por `api2`, `api3` ou `api4` conforme a API iniciada.

## Contrato comum

- O sensor presente na URL deve ser igual a `fonte.id` do JSON.
- Se enviado, o cabeçalho `X-Source-Id` também deve ser igual a `fonte.id`.
- O campo opcional da organização é `"organização"` (UTF-8).
- Um payload idêntico é idempotente: retorna `200` com `status: "já recebido"`; um novo payload retorna `201`.
