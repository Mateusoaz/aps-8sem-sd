#!/usr/bin/env python3
"""Junta as execuções da linha de base em uma tabela e um gráfico por rota.

Para cada degrau, tira a média das execuções e cruza com a CPU dos pods e o tamanho
da fila, amostrados a cada 5 s pelo carga/linha_base.sh.
Uso (na raiz do repositório): python carga/analisa_base.py
Grava em resultados/base/: tabela-<rota>.md, grafico-<rota>.png e linha-base.json
"""
import datetime
import glob
import json
import os
import re
import statistics

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

PASTA = "resultados/base"
ROTAS = {"post": "POST /air-quality/api/v1/air-quality/particulate",
         "get": "GET /air-quality/api/v1/air-quality/areas/CENTRO/average?hours=24"}


def le_amostras(caminho, dia):
    """Devolve [(instante, fila, {pod: milicores})] do arquivo top-*.txt."""
    amostras = []
    for linha in open(caminho, encoding="utf-8", errors="replace"):
        cabecalho = re.match(r"=== (\d\d:\d\d:\d\d) fila=(\d*)", linha)
        if cabecalho:
            hora = datetime.datetime.strptime(cabecalho[1], "%H:%M:%S").time()
            fila = int(cabecalho[2]) if cabecalho[2] else None
            amostras.append((datetime.datetime.combine(dia, hora), fila, {}))
            continue
        pod = re.match(r"(\S+)\s+(\d+)m\s", linha)
        if pod and amostras:
            amostras[-1][2][pod[1]] = int(pod[2])
    return amostras


def media(valores):
    return statistics.mean(valores) if valores else None


def recursos_do_degrau(amostras, inicio, fim):
    janela = [a for a in amostras if inicio <= a[0] <= fim]
    cpu = {}
    for nome in ("air-quality-api", "postgres", "rabbitmq", "redis"):
        leituras = [v for a in janela for p, v in a[2].items() if p.startswith(nome)]
        cpu[nome] = max(leituras) if leituras else None
    filas = [a[1] for a in janela if a[1] is not None]
    return cpu, (filas[-1] if filas else None)


def analisa(rota):
    execucoes = []
    for caminho in sorted(glob.glob(f"{PASTA}/{rota}-exec*-resumo.json")):
        resumo = json.load(open(caminho, encoding="utf-8"))
        nome = os.path.basename(caminho).replace("-resumo.json", "")
        inicio = datetime.datetime.fromisoformat(resumo["inicio"])
        amostras = le_amostras(f"{PASTA}/top-{nome}.txt", inicio.date())
        for i, degrau in enumerate(resumo["degraus"]):
            comeco = inicio + datetime.timedelta(seconds=i * 30 + 5)
            degrau["cpu"], degrau["fila"] = recursos_do_degrau(
                amostras, comeco, comeco + datetime.timedelta(seconds=25))
        execucoes.append(resumo)

    linhas = []
    for i, primeiro in enumerate(execucoes[0]["degraus"]):
        grupo = [e["degraus"][i] for e in execucoes]
        coluna = lambda chave: [g[chave] for g in grupo if g[chave] is not None]
        recurso = lambda nome: [g["cpu"][nome] for g in grupo if g["cpu"][nome] is not None]
        vazoes = coluna("vazao_req_s")
        linhas.append({
            "trabalhadores": primeiro["trabalhadores"],
            "requisicoes": round(media(coluna("requisicoes"))),
            "vazao": media(vazoes),
            "vazao_min": min(vazoes),
            "vazao_max": max(vazoes),
            "p50": media(coluna("p50_ms")),
            "p95": media(coluna("p95_ms")),
            "p99": media(coluna("p99_ms")),
            "erros": media(coluna("taxa_erro_pct")),
            "little": media(coluna("little_trabalhadores")),
            "cpu_gerador": media(coluna("cpu_gerador_pct")),
            "cpu_api": media(recurso("air-quality-api")),
            "cpu_postgres": media(recurso("postgres")),
            "cpu_rabbitmq": media(recurso("rabbitmq")),
            "cpu_redis": media(recurso("redis")),
            "fila": media(coluna("fila")),
            "por_erro": sorted({e for g in grupo for e in g["por_erro"]}),
        })
    return {"rota": ROTAS[rota], "execucoes": len(execucoes), "linhas": linhas}


def n(valor, casas=1):
    return "-" if valor is None else f"{valor:.{casas}f}"


def grava_tabela(chave, dados):
    with open(f"{PASTA}/tabela-{chave}.md", "w", encoding="utf-8") as f:
        f.write(f"# Linha de base: {dados['rota']}\n\n")
        f.write(f"Média de {dados['execucoes']} execuções; 1 réplica, sem HPA; 30 s por degrau, 5 s de aquecimento.\n\n")
        f.write("| Trab. | Requisições | Vazão (req/s) | Faixa da vazão | p50 (ms) | p95 (ms) | p99 (ms) | Erros (%) "
                "| CPU API (m) | CPU banco (m) | CPU fila (m) | Fila ao fim | CPU gerador (%) |\n")
        f.write("|" + "---:|" * 13 + "\n")
        for l in dados["linhas"]:
            f.write(f"| {l['trabalhadores']} | {l['requisicoes']} | {n(l['vazao'])} | {n(l['vazao_min'], 0)} a {n(l['vazao_max'], 0)} "
                    f"| {n(l['p50'])} | {n(l['p95'])} | {n(l['p99'])} | {n(l['erros'], 2)} | {n(l['cpu_api'], 0)} "
                    f"| {n(l['cpu_postgres'], 0)} | {n(l['cpu_rabbitmq'], 0)} | {n(l['fila'], 0)} | {n(l['cpu_gerador'], 0)} |\n")


def grava_grafico(chave, dados):
    linhas = dados["linhas"]
    x = [l["trabalhadores"] for l in linhas]
    fig, (cima, baixo) = plt.subplots(2, 1, figsize=(9, 7.5), sharex=True)

    cima.plot(x, [l["vazao"] for l in linhas], marker="o", color="#1f6fb5", label="Vazão média")
    cima.fill_between(x, [l["vazao_min"] for l in linhas], [l["vazao_max"] for l in linhas],
                      color="#1f6fb5", alpha=0.15, label="Faixa entre as execuções")
    cima.set_ylabel("Vazão (respostas OK por segundo)")
    cima.set_ylim(bottom=0)
    cima.legend(loc="upper left")
    cima.grid(alpha=0.3)
    cima.set_title(dados["rota"], fontsize=11)

    for campo, cor, rotulo in (("p50", "#0f7b6c", "p50"), ("p95", "#b4581a", "p95"), ("p99", "#b3323a", "p99")):
        baixo.plot(x, [l[campo] for l in linhas], marker="o", color=cor, label=rotulo)
    baixo.set_yscale("log")
    baixo.set_ylabel("Latência (ms, escala log)")
    baixo.set_xlabel("Trabalhadores")
    baixo.set_xscale("log", base=2)
    baixo.set_xticks(x, [str(v) for v in x])
    baixo.legend(loc="upper left")
    baixo.grid(alpha=0.3, which="both")

    erros = [l["trabalhadores"] for l in linhas if l["erros"] > 1]
    if erros:  # região em que mais de 1% das requisições falhou
        for eixo in (cima, baixo):
            eixo.axvspan(erros[0] / 2 ** 0.5, x[-1] * 1.1, color="#b3323a", alpha=0.08)
        cima.text(erros[0], cima.get_ylim()[1] * 0.92, "região com erros", color="#b3323a", fontsize=9)

    fig.tight_layout()
    fig.savefig(f"{PASTA}/grafico-{chave}.png", dpi=150)
    plt.close(fig)


def main():
    resultado = {}
    for chave in ROTAS:
        dados = analisa(chave)
        resultado[chave] = dados
        grava_tabela(chave, dados)
        grava_grafico(chave, dados)
        print(open(f"{PASTA}/tabela-{chave}.md", encoding="utf-8").read())
    json.dump(resultado, open(f"{PASTA}/linha-base.json", "w", encoding="utf-8"), ensure_ascii=False, indent=2)


if __name__ == "__main__":
    main()
