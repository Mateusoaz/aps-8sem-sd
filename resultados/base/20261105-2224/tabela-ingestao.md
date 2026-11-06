# Linha de base: ingestao

Rota: `POST http://127.0.0.1:8081/api/v1/air-quality/particulate` · 1 réplica de cada serviço, HPA removido · 30 s por degrau, 5 s de aquecimento descartados · 3 repetições (média ± desvio-padrão)

| Trabalhadores | Requisições | Vazão (req/s) | p50 (ms) | p95 (ms) | p99 (ms) | Erros (%) | CPU do pod (air-quality-api, top) | CPU do banco (top) |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 1 | 4.111 | 164,4 ± 61,6 | 5,0 ± 1,1 | 18,1 ± 20,4 | 29,7 ± 15,3 | 0,00 | 265m | 103m |
| 2 | 4.400 | 176,0 ± 72,9 | 7,7 ± 3,7 | 40,2 ± 24,8 | 48,7 ± 23,9 | 0,00 | 454m | 173m |
| 4 | 7.032 | 281,3 ± 47,4 | 7,3 ± 0,9 | 53,1 ± 4,9 | 67,2 ± 7,9 | 0,00 | 480m | 231m |
| 8 | 11.002 | 440,1 ± 65,9 | 8,4 ± 0,6 | 60,4 ± 5,0 | 68,7 ± 8,2 | 0,00 | 496m | 275m |
| 16 | 18.106 | 724,3 ± 11,1 | 11,3 ± 0,4 | 57,6 ± 3,5 | 70,2 ± 3,2 | 0,00 | 496m | 317m |
| 32 | 18.134 | 725,4 ± 78,5 | 41,6 ± 12,1 | 79,1 ± 1,5 | 86,7 ± 0,2 | 0,00 | 495m | 319m |
| 64 | 18.877 | 755,1 ± 26,2 | 88,2 ± 2,4 | 112,7 ± 7,8 | 139,8 ± 13,7 | 0,00 | 479m | 286m |

**Ponto de saturação:** a partir de 2 trabalhadores · vazão máxima 755,1 req/s (com 64 trabalhadores) · p95 nesse ponto 112,7 ms

Critério do joelho: dobrar os trabalhadores aumentou a vazão em menos de 15%, ou os erros passaram de 1%.

CPU do gerador: até 19,1% de um núcleo (perto de 100%, o limite medido pode ser o do próprio gerador).

Ambiente: AMD Ryzen 9 5900X 12-Core Processor · 24 núcleos lógicos · 31.9 GB de RAM · Windows 11 · gerador na mesma máquina do cluster.

Comando (exemplo de uma repetição): `carga/loadgen.py http://127.0.0.1:8081/api/v1/air-quality/particulate -X POST --corpo ar --degraus 1,2,4,8,16,32,64 --duracao-degrau 30 --aquecimento 5 --timeout 5 --top --top-intervalo 3 --saida resultados/base/20261105-2224/ingestao-rep1`
