#!/usr/bin/env python3
"""
Gráficos AO VIVO do teste de carga: abre uma janela e redesenha a cada segundo, um gráfico por medida.

Lê o arquivo <prefixo>-ao-vivo.csv que o loadgen (ou o carga/experimento.py) grava segundo a segundo.
Aponte para uma pasta e ele acompanha sempre o teste mais recente dela: quando um teste termina e outro
começa, a janela troca sozinha e salva a imagem do teste que terminou.

Nos experimentos da Etapa 5 aparecem também as réplicas prontas, as réplicas pedidas pelo HPA e a
fatia de respostas da versão nova (rolling update), e os eventos do eventos.csv (pod apagado, drain,
decisões do HPA...) viram linhas verticais em todos os gráficos.

Uso (num segundo terminal, enquanto o teste roda):
  python carga/ao_vivo.py resultados/base              acompanha o teste mais recente da pasta
  python carga/ao_vivo.py resultados/etapa5
  python carga/ao_vivo.py <arquivo>-ao-vivo.csv        um arquivo específico
Requer: pip install matplotlib
"""
from __future__ import annotations

import csv
import glob
import math
import os
import re
import sys

import matplotlib.pyplot as plt
from matplotlib.animation import FuncAnimation

# Cada painel mostra UMA medida (o título a nomeia, sem legenda). Cor única para as medidas;
# tinta secundária para o contexto (trabalhadores, limites, divisões de degrau, eventos).
COR = "#2a78d6"
CONTEXTO = "#52514e"
TINTA = "#0b0b0b"
GRADE = "#e4e3df"
FUNDO = "#fcfcfb"
DIVISAO = "#d6d5d0"

# (coluna do CSV, título do painel, tipo, limite em millicores ou None, opcional)
PAINEIS = [
    ("p50_ms", "Latência p50 (ms)", "linha", None, False),
    ("p95_ms", "Latência p95 (ms)", "linha", None, False),
    ("p99_ms", "Latência p99 (ms)", "linha", None, False),
    ("ok_s", "Vazão (respostas OK por segundo)", "linha", None, False),
    ("erros_s", "Erros por segundo", "barra", None, False),
    ("trabalhadores", "Trabalhadores ativos", "degrau", None, False),
    ("cpu_api_m", "CPU do pod da API (millicores, kubectl top)", "degrau", 500, False),
    ("cpu_banco_m", "CPU do banco (millicores, kubectl top)", "degrau", 2000, False),
    ("replicas_prontas", "Réplicas prontas da API", "degrau", None, True),
    ("hpa_desejadas", "Réplicas pedidas pelo HPA", "degrau", None, True),
    ("pct_versao_nova", "Respostas da versão nova (%)", "linha", None, True),
]

ROTULOS_EVENTO = {
    "acao_pod_apagado": "pod apagado", "acao_no_drenado": "drain", "drain_concluido": "drain ok",
    "acao_rollout_inicio": "set image", "rollout_fim": "rollout ok", "acao_undo_inicio": "undo",
    "undo_fim": "undo ok", "no_liberado": "uncordon",
}
POR_GERADOR = re.compile(r"-g\d+-ao-vivo\.csv$")


def mais_recente(alvo: str) -> str | None:
    if os.path.isfile(alvo):
        return alvo
    arquivos = [a for a in glob.glob(os.path.join(alvo, "**", "*-ao-vivo.csv"), recursive=True)
                if not POR_GERADOR.search(a)]
    return max(arquivos, key=os.path.getmtime) if arquivos else None


def ler(arquivo: str) -> list[dict]:
    try:
        with open(arquivo, newline="", encoding="utf-8") as f:
            return list(csv.DictReader(f))
    except OSError:
        return []


def numero(texto):
    try:
        return float(texto)
    except (TypeError, ValueError):
        return None


def eventos_da_pasta(arquivo: str, linhas: list[dict]) -> list[tuple[float, str]]:
    """Eventos do experimento (eventos.csv na mesma pasta), convertidos para o eixo x do gráfico."""
    if not linhas or not linhas[0].get("epoch"):
        return []
    deslocamento = float(linhas[0]["epoch"]) - float(linhas[0]["segundo"])
    marcas = []
    for e in ler(os.path.join(os.path.dirname(arquivo), "eventos.csv")):
        rotulo = ROTULOS_EVENTO.get(e["tipo"])
        if e["tipo"] == "hpa_decisao":
            rotulo = "HPA " + e["detalhe"].split(" réplicas")[0].replace(" -> ", "→")
        if rotulo:
            x = float(e["epoch"]) - deslocamento
            if -2 <= x <= float(linhas[-1]["segundo"]) + 2:
                marcas.append((x, rotulo))
    return marcas


def main():
    if len(sys.argv) != 2:
        raise SystemExit(__doc__)
    alvo = sys.argv[1]

    plt.rcParams.update({"font.size": 9, "axes.titlesize": 10, "axes.titlelocation": "left"})
    fig = plt.figure(figsize=(14, 9.5))
    fig.patch.set_facecolor(FUNDO)
    estado = {"arquivo": None}

    def salvar_imagem(arquivo):
        if arquivo:
            try:
                fig.savefig(arquivo.replace("-ao-vivo.csv", "-ao-vivo.png"), dpi=130, facecolor=FUNDO, bbox_inches="tight")
            except OSError:
                pass

    def desenhar(_quadro):
        arquivo = mais_recente(alvo)
        if arquivo != estado["arquivo"]:
            salvar_imagem(estado["arquivo"])       # guarda a imagem do teste que acabou de terminar
            estado["arquivo"] = arquivo
        fig.clear()
        if not arquivo:
            fig.suptitle(f"Aguardando um teste em {alvo} ...", x=0.02, ha="left", color=TINTA)
            return
        linhas = ler(arquivo)
        if not linhas:
            return

        paineis = [p for p in PAINEIS if not p[4] or any(numero(l.get(p[0])) is not None for l in linhas)]
        colunas = 2
        fileiras = math.ceil(len(paineis) / colunas)
        eixos = fig.subplots(fileiras, colunas, sharex=True, squeeze=False).flatten()
        x = [int(float(l["segundo"])) for l in linhas]
        inicios = [(x[i], linhas[i]["trabalhadores"]) for i in range(1, len(linhas))
                   if linhas[i]["fase"] != linhas[i - 1]["fase"]]
        marcas = eventos_da_pasta(arquivo, linhas)

        for ax, (coluna, titulo, tipo, limite, _) in zip(eixos, paineis):
            ax.set_facecolor(FUNDO)
            for lado in ("top", "right"):
                ax.spines[lado].set_visible(False)
            for lado in ("left", "bottom"):
                ax.spines[lado].set_color(GRADE)
            ax.tick_params(colors=CONTEXTO, length=0)
            ax.grid(axis="y", color=GRADE, linewidth=0.8)
            ax.set_axisbelow(True)
            for inicio, _ in inicios:
                ax.axvline(inicio, color=DIVISAO, linewidth=1, zorder=0)
            for i, (mx, rotulo) in enumerate(marcas):
                ax.axvline(mx, color=CONTEXTO, linewidth=1, linestyle=":", zorder=1)
                if coluna in ("ok_s", "replicas_prontas", "p95_ms"):
                    ax.annotate(rotulo, (mx, 1), xycoords=("data", "axes fraction"), xytext=(2, -9 - 9 * (i % 3)),
                                textcoords="offset points", fontsize=7, color=TINTA)

            y = [numero(l.get(coluna)) for l in linhas]
            pontos = [(a, b) for a, b in zip(x, y) if b is not None]
            ultimo = pontos[-1][1] if pontos else None
            if pontos:
                px, py = zip(*pontos)
                if tipo == "barra":
                    ax.bar(px, py, width=0.9, color=CONTEXTO)
                elif tipo == "degrau":
                    ax.step(px, py, where="post", color=CONTEXTO if coluna == "trabalhadores" else COR, linewidth=2)
                else:
                    ax.plot(px, py, color=COR, linewidth=2)
            maximo = max((p[1] for p in pontos), default=0)
            if limite:
                ax.axhline(limite, color=CONTEXTO, linewidth=1, linestyle="--")
                ax.annotate(f"limite {limite}m", (0, limite), xycoords=("axes fraction", "data"), xytext=(4, 3),
                            textcoords="offset points", fontsize=8, color=CONTEXTO)
                ax.set_ylim(0, max(limite, maximo) * 1.15)
            else:
                ax.set_ylim(0, maximo * 1.3 if maximo else 1)
            agora = "" if ultimo is None else f"   agora: {ultimo:,.1f}".replace(",", "X").replace(".", ",").replace("X", ".")
            ax.set_title(titulo + agora, color=TINTA)
            if coluna == "trabalhadores" and inicios:
                for inicio, n in [(x[0], linhas[0]["trabalhadores"])] + inicios:
                    ax.annotate(n, (inicio, 1), xycoords=("data", "axes fraction"), xytext=(3, -12),
                                textcoords="offset points", fontsize=8, color=CONTEXTO)
        for ax in eixos[len(paineis):]:
            ax.set_visible(False)
        for ax in eixos[max(0, len(paineis) - colunas):len(paineis)]:
            ax.set_xlabel("segundos desde o início do teste", color=CONTEXTO)

        u = linhas[-1]
        nome = os.path.basename(arquivo).replace("-ao-vivo.csv", "")
        pasta = os.path.basename(os.path.dirname(arquivo))
        fases = f" · degrau {u['fase']}/{u['fases']}" if u.get("fases") not in ("1", "", None) else ""
        fig.suptitle(f"{pasta} / {nome} · {u['rota']}{fases} · {u['trabalhadores']} trabalhadores · "
                     f"{u['pods']} pod(s) respondendo · {u['hora']}", x=0.02, ha="left", fontsize=11, color=TINTA)
        fig.tight_layout(rect=(0, 0, 1, 0.96))

    animacao = FuncAnimation(fig, desenhar, interval=1000, cache_frame_data=False)  # noqa: F841 - precisa viver
    try:
        plt.show()
    finally:
        salvar_imagem(estado["arquivo"])


if __name__ == "__main__":
    main()
