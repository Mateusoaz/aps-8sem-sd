# Linha de base: consulta

Rota: `GET http://127.0.0.1:8081/api/v1/air-quality/stations/{{escolha:EST-01|EST-02|EST-03|EST-04|EST-05|EST-06|EST-07|EST-08|EST-09|EST-10}}/latest` · 1 réplica de cada serviço, HPA removido · 30 s por degrau, 5 s de aquecimento descartados · 3 repetições (média ± desvio-padrão)

| Trabalhadores | Requisições | Vazão (req/s) | p50 (ms) | p95 (ms) | p99 (ms) | Erros (%) | CPU do pod (air-quality-api, top) | CPU do banco (top) |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 1 | 16.883 | 675,3 ± 22,4 | 1,4 ± 0,0 | 1,7 ± 0,1 | 2,1 ± 0,2 | 0,00 | 261m | 17m |
| 2 | 27.921 | 1.116,8 ± 41,9 | 1,5 ± 0,0 | 1,9 ± 0,1 | 10,7 ± 1,6 | 0,00 | 482m | 10m |
| 4 | 28.239 | 1.129,6 ± 11,6 | 1,6 ± 0,0 | 14,3 ± 6,5 | 45,7 ± 3,8 | 0,00 | 500m | 9m |
| 8 | 31.954 | 1.278,1 ± 11,3 | 2,0 ± 0,0 | 55,3 ± 7,9 | 61,9 ± 5,7 | 0,00 | 499m | 10m |
| 16 | 35.080 | 1.403,2 ± 3,5 | 3,6 ± 0,1 | 62,1 ± 1,4 | 66,2 ± 1,7 | 0,00 | 497m | 12m |
| 32 | 38.788 | 1.551,5 ± 5,6 | 8,3 ± 0,4 | 66,0 ± 5,1 | 72,3 ± 3,5 | 0,00 | 498m | 11m |
| 64 | 46.656 | 1.866,3 ± 29,6 | 22,9 ± 1,6 | 75,6 ± 3,4 | 83,6 ± 5,1 | 0,00 | 498m | 12m |

**Ponto de saturação:** a partir de 4 trabalhadores · vazão máxima 1.866,3 req/s (com 64 trabalhadores) · p95 nesse ponto 75,6 ms

Critério do joelho: dobrar os trabalhadores aumentou a vazão em menos de 15%, ou os erros passaram de 1%.

CPU do gerador: até 37,6% de um núcleo (perto de 100%, o limite medido pode ser o do próprio gerador).

Ambiente: AMD Ryzen 9 5900X 12-Core Processor · 24 núcleos lógicos · 31.9 GB de RAM · Windows 11 · gerador na mesma máquina do cluster.

Comando (exemplo de uma repetição): `carga/loadgen.py 'http://127.0.0.1:8081/api/v1/air-quality/stations/{{escolha:EST-01|EST-02|EST-03|EST-04|EST-05|EST-06|EST-07|EST-08|EST-09|EST-10}}/latest' --degraus 1,2,4,8,16,32,64 --duracao-degrau 30 --aquecimento 5 --timeout 5 --top --top-intervalo 3 --saida resultados/base/20261105-2224/consulta-rep1`
