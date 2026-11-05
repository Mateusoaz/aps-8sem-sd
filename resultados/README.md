# Resultados da APS

Guarde aqui, sem sobrescrever, os arquivos brutos de cada execução:

- `*-requisicoes.csv` — uma linha por requisição, incluindo falhas e latência;
- `*-serie.csv` — amostras por segundo com hora, carga, erros, p95 e pods;
- `*-resumo.json` — percentis, vazão, erros e distribuição por pod/versão;
- gráficos PNG produzidos a partir desses arquivos.

Nomeie prefixos com cenário e repetição (`base-r1`, `manual-r4-r2`, `hpa-r1`, `cache-on-r3`). Versione também o comando e a configuração da máquina. Esta pasta começa sem números de experimento; preencha com coletas reais.
