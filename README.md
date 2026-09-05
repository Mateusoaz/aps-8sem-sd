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
