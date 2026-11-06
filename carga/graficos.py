#!/usr/bin/env python3
"""
Gráficos e tabela da linha de base (Etapa 4), a partir dos *-resumo.json do loadgen.

Agrupa as repetições pelo nome do arquivo antes de "-rep" (ingestao-rep1, ingestao-rep2... -> "ingestao"),
calcula média e desvio-padrão de cada degrau e gera, para cada grupo:
  grafico-<grupo>.png   latência (p50, p95, p99), vazão e erros por número de trabalhadores,
                        com a região de saturação marcada
  graficos-<grupo>/     um PNG por medida (p50, p95, p99, vazão, erros, CPU da API, CPU do banco)
  tabela-<grupo>.md     a tabela da seção 5 da ficha, já preenchida
e um linha-de-base.json com tudo agregado.

Uso:  python carga/graficos.py resultados/base/20261105-2230
Requer: pip install matplotlib
"""
from __future__ import annotations

import glob
import json
import os
import re
import statistics
import sys
from collections import defaultdict

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.ticker import FixedLocator, NullLocator  # noqa: E402

# Paleta de referência (validada): percentis numa rampa azul ordinal (p50 claro -> p99 escuro),
# vazão em laranja, erros em tinta secundária. Texto sempre em tinta neutra, nunca na cor da série.
P50, P95, P99 = "#6da7ec", "#2a78d6", "#104281"
VAZAO = "#eb6834"
ERROS = "#52514e"
TINTA = "#0b0b0b"
TINTA_2 = "#52514e"
GRADE = "#e4e3df"
FUNDO = "#fcfcfb"
SATURACAO = "#efeeea"

# Critério do joelho: dobrar os trabalhadores deu menos de 15% de vazão a mais, ou os erros passaram de 1%.
GANHO_MINIMO = 1.15
ERRO_MAXIMO_PCT = 1.0


def media_dp(valores):
    valores = [v for v in valores if v is not None]
    if not valores:
        return None, None
    return statistics.fmean(valores), (statistics.stdev(valores) if len(valores) > 1 else 0.0)


def nome_do_servico(pod: str) -> str:
    partes = pod.split("-")
    if len(partes) >= 3 and re.fullmatch(r"[a-z0-9]{5}", partes[-1]) and re.fullmatch(r"[a-z0-9]{8,10}", partes[-2]):
        return "-".join(partes[:-2])
    if re.fullmatch(r"\d+", partes[-1]):
        return "-".join(partes[:-1])
    return pod


def servico_alvo(url: str) -> str | None:
    m = re.search(r"/api/v1/([a-z-]+)", url)
    return f"{m.group(1)}-api" if m else None


def agregar(arquivos: list[str]) -> dict:
    resumos = [json.load(open(a, encoding="utf-8")) for a in sorted(arquivos)]
    alvo = servico_alvo(resumos[0]["alvo"]["url"])
    por_trab = defaultdict(lambda: defaultdict(list))
    for r in resumos:
        for f in r["por_fase"]:
            d = por_trab[f["trabalhadores"]]
            d["requisicoes"].append(f["requisicoes"])
            d["vazao"].append(f["vazao_req_s"])
            d["erro"].append(f["taxa_erro_pct"] or 0)
            for p in ("p50", "p95", "p99"):
                d[p].append(f["latencia_ms"][p])
            cpu = defaultdict(int)
            for pod, v in f.get("cpu_top_m", {}).items():
                cpu[nome_do_servico(pod)] += v["media"]
            d["cpu_alvo"].append(cpu.get(alvo))
            d["cpu_banco"].append(cpu.get("postgres"))
            d["pods"].append(len(f["por_pod"]))

    linhas = []
    for n in sorted(por_trab):
        d = por_trab[n]
        linha = {"trabalhadores": n, "repeticoes": len(d["vazao"])}
        for chave in ("requisicoes", "vazao", "erro", "p50", "p95", "p99", "cpu_alvo", "cpu_banco"):
            linha[chave], linha[chave + "_dp"] = media_dp(d[chave])
        linhas.append(linha)

    # Joelho: o primeiro degrau em que dobrar a concorrência quase não aumentou a vazão (ou surgiram erros)
    joelho = None
    for anterior, atual in zip(linhas, linhas[1:]):
        if (atual["vazao"] or 0) < GANHO_MINIMO * (anterior["vazao"] or 0) or (atual["erro"] or 0) > ERRO_MAXIMO_PCT:
            joelho = atual["trabalhadores"]
            break
    pico = max(linhas, key=lambda l: l["vazao"] or 0)
    return {
        "alvo": resumos[0]["alvo"],
        "servico": alvo,
        "comando_exemplo": resumos[0]["comando"],
        "ambiente": resumos[0]["ambiente"],
        "duracao_degrau_s": resumos[0]["parametros"]["duracao_degrau_s"],
        "aquecimento_s": resumos[0]["parametros"]["aquecimento_s"],
        "repeticoes": len(resumos),
        "cpu_gerador_pct_max": max(r["cpu_gerador_pct_de_um_nucleo"] for r in resumos),
        "linhas": linhas,
        "saturacao_a_partir_de": joelho,
        "vazao_maxima": {"trabalhadores": pico["trabalhadores"], "vazao_req_s": pico["vazao"], "p95_ms": pico["p95"]},
    }


def fmt(v, dp=None, casas=1):
    if v is None:
        return "—"
    texto = f"{v:,.{casas}f}".replace(",", "X").replace(".", ",").replace("X", ".")
    if dp:
        texto += f" ± {dp:,.{casas}f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return texto


def tabela_md(nome: str, a: dict) -> str:
    alvo = a["alvo"]
    linhas = [
        f"# Linha de base: {nome}",
        "",
        f"Rota: `{alvo['metodo']} {alvo['url']}` · 1 réplica de cada serviço, HPA removido · "
        f"{a['duracao_degrau_s']:g} s por degrau, {a['aquecimento_s']:g} s de aquecimento descartados · "
        f"{a['repeticoes']} repetições (média ± desvio-padrão)",
        "",
        f"| Trabalhadores | Requisições | Vazão (req/s) | p50 (ms) | p95 (ms) | p99 (ms) | Erros (%) | CPU do pod ({a['servico']}, top) | CPU do banco (top) |",
        "|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for l in a["linhas"]:
        linhas.append(
            f"| {l['trabalhadores']} | {fmt(l['requisicoes'], casas=0)} | {fmt(l['vazao'], l['vazao_dp'])} | "
            f"{fmt(l['p50'], l['p50_dp'])} | {fmt(l['p95'], l['p95_dp'])} | {fmt(l['p99'], l['p99_dp'])} | "
            f"{fmt(l['erro'], casas=2)} | {fmt(l['cpu_alvo'], casas=0)}m | {fmt(l['cpu_banco'], casas=0)}m |")
    v = a["vazao_maxima"]
    linhas += [
        "",
        f"**Ponto de saturação:** a partir de {a['saturacao_a_partir_de'] or '— (não saturou nos degraus medidos)'} trabalhadores"
        f" · vazão máxima {fmt(v['vazao_req_s'])} req/s (com {v['trabalhadores']} trabalhadores) · p95 nesse ponto {fmt(v['p95_ms'])} ms",
        "",
        f"Critério do joelho: dobrar os trabalhadores aumentou a vazão em menos de {round((GANHO_MINIMO - 1) * 100)}%, "
        f"ou os erros passaram de {ERRO_MAXIMO_PCT:g}%.",
        "",
        f"CPU do gerador: até {fmt(a['cpu_gerador_pct_max'])}% de um núcleo "
        "(perto de 100%, o limite medido pode ser o do próprio gerador).",
        "",
        f"Ambiente: {a['ambiente'].get('cpu')} · {a['ambiente'].get('nucleos_logicos')} núcleos lógicos · "
        f"{a['ambiente'].get('ram_gb')} GB de RAM · {a['ambiente'].get('sistema')} · gerador na mesma máquina do cluster.",
        "",
        f"Comando (exemplo de uma repetição): `{a['comando_exemplo']}`",
        "",
    ]
    return "\n".join(linhas)


def estilo(ax):
    ax.set_facecolor(FUNDO)
    for lado in ("top", "right"):
        ax.spines[lado].set_visible(False)
    for lado in ("left", "bottom"):
        ax.spines[lado].set_color(GRADE)
    ax.tick_params(colors=TINTA_2, labelsize=9, length=0)
    ax.grid(axis="y", color=GRADE, linewidth=0.8)
    ax.set_axisbelow(True)


def grafico(nome: str, a: dict, caminho: str):
    x = [l["trabalhadores"] for l in a["linhas"]]
    fig, (ax_lat, ax_vaz, ax_err) = plt.subplots(
        3, 1, figsize=(9, 9), sharex=True, gridspec_kw={"height_ratios": [3, 2, 1.2], "hspace": 0.28})
    fig.patch.set_facecolor(FUNDO)
    for ax in (ax_lat, ax_vaz, ax_err):
        estilo(ax)
        ax.set_xscale("log", base=2)
        ax.xaxis.set_major_locator(FixedLocator(x))
        ax.xaxis.set_minor_locator(NullLocator())
        ax.set_xticklabels([str(v) for v in x])
        if a["saturacao_a_partir_de"]:
            ax.axvspan(a["saturacao_a_partir_de"] / 1.25, x[-1] * 1.25, color=SATURACAO, zorder=0)
        ax.set_xlim(x[0] / 1.25, x[-1] * 1.25)

    # Latência: três percentis, linhas de 2 px, marcadores de 8 px, barra de erro = desvio-padrão entre repetições
    for chave, cor, rotulo in (("p50", P50, "p50"), ("p95", P95, "p95"), ("p99", P99, "p99")):
        y = [l[chave] for l in a["linhas"]]
        dp = [l[chave + "_dp"] or 0 for l in a["linhas"]]
        ax_lat.errorbar(x, y, yerr=dp, color=cor, linewidth=2, marker="o", markersize=7, markeredgecolor=FUNDO,
                        markeredgewidth=1.5, elinewidth=1, capsize=3, label=rotulo, zorder=3)
        ax_lat.annotate(rotulo, (x[-1], y[-1]), xytext=(8, 0), textcoords="offset points",
                        va="center", fontsize=9, color=TINTA)
    ax_lat.set_ylabel("Latência (ms)", color=TINTA_2, fontsize=10)
    ax_lat.set_ylim(bottom=0)
    ax_lat.legend(loc="upper left", frameon=False, fontsize=9, labelcolor=TINTA)

    # Vazão: uma série só (o título do painel a nomeia, sem legenda)
    y = [l["vazao"] for l in a["linhas"]]
    dp = [l["vazao_dp"] or 0 for l in a["linhas"]]
    ax_vaz.errorbar(x, y, yerr=dp, color=VAZAO, linewidth=2, marker="o", markersize=7, markeredgecolor=FUNDO,
                    markeredgewidth=1.5, elinewidth=1, capsize=3, zorder=3)
    v = a["vazao_maxima"]
    ax_vaz.annotate(f"máx. {fmt(v['vazao_req_s'], casas=0)} req/s", (v["trabalhadores"], v["vazao_req_s"]),
                    xytext=(0, 10), textcoords="offset points", ha="center", fontsize=9, color=TINTA)
    ax_vaz.set_ylabel("Vazão (req/s)", color=TINTA_2, fontsize=10)
    ax_vaz.set_ylim(0, max(y) * 1.25 if max(y) else 1)

    # Erros
    erros = [l["erro"] or 0 for l in a["linhas"]]
    ax_err.bar(x, erros, width=[v * 0.35 for v in x], color=ERROS, zorder=3)
    ax_err.set_ylabel("Erros (%)", color=TINTA_2, fontsize=10)
    ax_err.set_ylim(0, max(1.0, max(erros) * 1.3))
    ax_err.set_xlabel("Trabalhadores simultâneos (escala log₂)", color=TINTA_2, fontsize=10)

    alvo = a["alvo"]
    rota = re.sub(r"^https?://[^/]+", "", alvo["url"])
    fig.suptitle(f"Linha de base — {alvo['metodo']} {rota}", x=0.06, ha="left", fontsize=13, color=TINTA, y=0.97)
    sub = f"1 réplica, HPA removido · {a['repeticoes']} repetições, média ± desvio-padrão"
    if a["saturacao_a_partir_de"]:
        sub += f" · área cinza: saturação a partir de {a['saturacao_a_partir_de']} trabalhadores"
    fig.text(0.06, 0.935, sub, fontsize=9, color=TINTA_2)
    fig.savefig(caminho, dpi=150, bbox_inches="tight", facecolor=FUNDO)
    plt.close(fig)


# Uma medida por gráfico: (chave na linha agregada, título, unidade, cor, tipo)
MEDIDAS = [
    ("p50", "Latência p50", "ms", P50, "linha"),
    ("p95", "Latência p95", "ms", P95, "linha"),
    ("p99", "Latência p99", "ms", P99, "linha"),
    ("vazao", "Vazão", "req/s", VAZAO, "linha"),
    ("erro", "Taxa de erro", "%", ERROS, "barra"),
    ("cpu_alvo", "CPU do pod da API (kubectl top)", "millicores", P95, "linha"),
    ("cpu_banco", "CPU do banco (kubectl top)", "millicores", P95, "linha"),
]
LIMITES = {"cpu_alvo": 500, "cpu_banco": 2000}


def graficos_separados(nome: str, a: dict, pasta: str) -> list[str]:
    """Um PNG por medida, em <pasta>/graficos-<nome>/<medida>.png"""
    destino = os.path.join(pasta, f"graficos-{nome}")
    os.makedirs(destino, exist_ok=True)
    x = [l["trabalhadores"] for l in a["linhas"]]
    rota = re.sub(r"^https?://[^/]+", "", a["alvo"]["url"])
    gerados = []
    for chave, titulo, unidade, cor, tipo in MEDIDAS:
        y = [l[chave] for l in a["linhas"]]
        if all(v is None for v in y):
            continue
        y = [v or 0 for v in y]
        dp = [l.get(chave + "_dp") or 0 for l in a["linhas"]]
        fig, ax = plt.subplots(figsize=(8, 4.2))
        fig.patch.set_facecolor(FUNDO)
        estilo(ax)
        ax.set_xscale("log", base=2)
        ax.xaxis.set_major_locator(FixedLocator(x))
        ax.xaxis.set_minor_locator(NullLocator())
        ax.set_xticklabels([str(v) for v in x])
        ax.set_xlim(x[0] / 1.25, x[-1] * 1.25)
        if a["saturacao_a_partir_de"]:
            ax.axvspan(a["saturacao_a_partir_de"] / 1.25, x[-1] * 1.25, color=SATURACAO, zorder=0)
        if tipo == "barra":
            ax.bar(x, y, width=[v * 0.35 for v in x], color=cor, zorder=3)
            ax.set_ylim(0, max(1.0, max(y) * 1.3))
        else:
            ax.errorbar(x, y, yerr=dp, color=cor, linewidth=2, marker="o", markersize=7, markeredgecolor=FUNDO,
                        markeredgewidth=1.5, elinewidth=1, capsize=3, zorder=3)
            topo = max(v + d for v, d in zip(y, dp))
            if chave in LIMITES:
                ax.axhline(LIMITES[chave], color=TINTA_2, linewidth=1, linestyle="--")
                ax.annotate(f"limite {LIMITES[chave]}m", (x[0] / 1.2, LIMITES[chave]), xytext=(0, 4),
                            textcoords="offset points", fontsize=8, color=TINTA_2)
                topo = max(topo, LIMITES[chave])
            ax.set_ylim(0, topo * 1.2 if topo else 1)
            # Rótulo direto só no último ponto (nunca um número em cada ponto)
            ax.annotate(fmt(y[-1], casas=0 if unidade != "ms" else 1), (x[-1], y[-1]), xytext=(8, 0),
                        textcoords="offset points", va="center", fontsize=9, color=TINTA)
        ax.set_ylabel(unidade, color=TINTA_2, fontsize=10)
        ax.set_xlabel("Trabalhadores simultâneos (escala log₂)", color=TINTA_2, fontsize=10)
        fig.suptitle(f"{titulo} — {a['alvo']['metodo']} {rota}", x=0.08, ha="left", fontsize=12, color=TINTA, y=0.99)
        sub = f"Linha de base, 1 réplica · {a['repeticoes']} repetições, média ± desvio-padrão"
        if a["saturacao_a_partir_de"]:
            sub += f" · cinza: saturação a partir de {a['saturacao_a_partir_de']}"
        fig.text(0.08, 0.905, sub, fontsize=8.5, color=TINTA_2)
        fig.tight_layout(rect=(0, 0, 1, 0.9))
        caminho = os.path.join(destino, f"{chave.replace('_', '-')}.png")
        fig.savefig(caminho, dpi=150, facecolor=FUNDO)
        plt.close(fig)
        gerados.append(caminho)
    return gerados


def main():
    if len(sys.argv) != 2:
        raise SystemExit(__doc__)
    pasta = sys.argv[1]
    grupos = defaultdict(list)
    for arquivo in glob.glob(os.path.join(pasta, "*-resumo.json")):
        nome = re.sub(r"-rep\d+$", "", os.path.basename(arquivo)[: -len("-resumo.json")])
        grupos[nome].append(arquivo)
    if not grupos:
        raise SystemExit(f"Nenhum *-resumo.json em {pasta}")

    tudo = {}
    for nome, arquivos in sorted(grupos.items()):
        a = agregar(arquivos)
        tudo[nome] = a
        with open(os.path.join(pasta, f"tabela-{nome}.md"), "w", encoding="utf-8") as f:
            f.write(tabela_md(nome, a))
        grafico(nome, a, os.path.join(pasta, f"grafico-{nome}.png"))
        graficos_separados(nome, a, pasta)
        v = a["vazao_maxima"]
        print(f"{nome}: saturação a partir de {a['saturacao_a_partir_de']} trabalhadores, "
              f"vazão máx. {v['vazao_req_s']:.0f} req/s (p95 {v['p95_ms']:.1f} ms) -> grafico-{nome}.png, tabela-{nome}.md")
    with open(os.path.join(pasta, "linha-de-base.json"), "w", encoding="utf-8") as f:
        json.dump(tudo, f, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    main()
