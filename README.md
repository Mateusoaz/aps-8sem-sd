# APS — Monitoramento ambiental distribuído

O projeto possui **três APIs independentes** em Python para os simuladores de sensores e ASP.NET Minimal API no servidor, compartilhando **um único PostgreSQL** chamado `aps_monitoramento`.

## Arquitetura

| Serviço | Porta | Schema PostgreSQL | Responsabilidade |
|---|---:|---|---|
| Air Quality API | 3001 | `air_quality` | Material particulado, gases e ambiente |
| Overflow API | 3002 | `overflow` | Nível da água, chuva e vazão |
| Thermal Inversion API | 3003 | `thermal_inversion` | Perfil térmico, umidade, pressão, vento e ocorrências |

As três APIs usam o mesmo contêiner PostgreSQL. Cada domínio possui tabelas próprias. O volume nomeado
`aps-sistemas-distribuidos_postgres-data` mantém os dados após `restart`, `stop`, `down` e reinicialização do computador.
Não execute `docker compose down -v`, pois a opção `-v` apaga o volume e os dados.

O domínio antigo de trânsito permanece no histórico do código, mas não é iniciado pelo Compose desta versão.

## Iniciar

1. Copie `.env.example` para `.env` caso ainda não exista.
2. Defina uma senha forte em `POSTGRES_PASSWORD`.
3. Execute:

```powershell
docker compose up -d --build
docker compose ps
```

Em instalações que já possuíam o volume da versão anterior, crie o banco compartilhado uma única vez:

```powershell
docker compose exec postgres sh -c 'PGPASSWORD="$POSTGRES_PASSWORD" createdb -U postgres aps_monitoramento'
```

Se a resposta disser que o banco já existe, nenhuma ação adicional é necessária.

## Rotas

### Qualidade do ar — http://localhost:3001

- `POST/GET /api/v1/air-quality/particulate`
- `POST/GET /api/v1/air-quality/gases`
- `POST/GET /api/v1/air-quality/environment`
- `GET /api/v1/air-quality/sensors`
- `GET /api/v1/air-quality/stations`
- `GET /api/v1/air-quality/sensors/{id}/readings`
- `GET /api/v1/air-quality/stations/{id}/readings`
- `GET /api/v1/air-quality/areas/{id}/average`
- `GET /api/v1/air-quality/alerts`

### Alagamento — http://localhost:3002

- `POST/GET /api/v1/overflow/water-level`
- `POST/GET /api/v1/overflow/rainfall`
- `POST/GET /api/v1/overflow/flow-rate`
- `GET /api/v1/overflow/sensors`
- `GET /api/v1/overflow/monitoring-points`
- `GET /api/v1/overflow/monitoring-points/{id}/latest`
- `GET /api/v1/overflow/monitoring-points/{id}/readings`
- `GET /api/v1/overflow/alerts`

### Inversão térmica — http://localhost:3003

- `POST/GET /api/v1/thermal-inversion/temperature-profile`
- `POST/GET /api/v1/thermal-inversion/soil-moisture`
- `POST/GET /api/v1/thermal-inversion/air-humidity`
- `POST/GET /api/v1/thermal-inversion/atmospheric-pressure`
- `POST/GET /api/v1/thermal-inversion/wind-speed`
- `GET /api/v1/thermal-inversion/stations`
- `GET /api/v1/thermal-inversion/sensors`
- `GET /api/v1/thermal-inversion/stations/{id}/latest`
- `GET /api/v1/thermal-inversion/stations/{id}/readings`
- `GET /api/v1/thermal-inversion/areas/{id}/thermal-profile`
- `GET /api/v1/thermal-inversion/alerts`
- `POST/GET /api/v1/thermal-inversion/occurrences`

Todas as APIs também expõem `GET /health/live` e `GET /health/ready`.

## Teste automático

Com os contêineres ativos:

```powershell
python .\testar_apis.py
```

O script envia uma leitura para cada uma das três APIs e consulta os dados persistidos.

## Conferir a persistência

```powershell
python .\testar_apis.py
docker compose restart
python .\testar_apis.py --somente-consulta
```

As leituras enviadas antes do reinício devem continuar sendo retornadas.

## Parar sem apagar dados

```powershell
docker compose down
```

Para iniciar novamente:

```powershell
docker compose up -d
```
