#!/usr/bin/env python3
"""
Gráficos AO VIVO do teste de carga: abre uma janela e redesenha a cada segundo, um gráfico por medida.

Lê o arquivo <prefixo>-ao-vivo.csv que o loadgen grava segundo a segundo. Aponte para uma pasta e ele
acompanha sempre o teste mais recente dela: quando a linha de base passa da ingestão para a consulta
(ou para a próxima repetição), a janela troca sozinha e salva a imagem do teste que terminou.

Uso (num segundo terminal, enquanto o teste roda):
  python carga/ao_vivo.py resultados/base              acompanha o teste mais recente da pasta
  python carga/ao_vivo.py resultados/base/x/ingestao-rep1-ao-vivo.csv   um arquivo específico
Requer: pip install matplotlib
"""
from __future__ import annotations

import csv
import glob
import os
import sys

import matplotlib.pyplot as plt
from matplotlib.animation import FuncAnimation

# Cada painel mostra UMA medida (o título a nomeia, sem legenda). Cor única para as medidas;
# tinta secundária para o contexto (trabalhadores, limites, divisões de degrau).
COR = "#2a78d6"
CONTEXTO = "#52514e"
TINTA = "#0b0b0b"
GRADE = "#e4e3df"
FUNDO = "#fcfcfb"
DIVISAO = "#d6d5d0"

# (coluna do CSV, título do painel, tipo, limite do contêiner em millicores ou None)
PAINEIS = [
    ("p50_ms", "Latência p50 (ms)", "linha", None),
    ("p95_ms", "Latência p95 (ms)", "linha", None),
    ("p99_ms", "Latência p99 (ms)", "linha", None),
    ("ok_s", "Vazão (respostas OK por segundo)", "linha", None),
    ("erros_s", "Erros por segundo", "barra", None),
    ("trabalhadores", "Trabalhadores ativos", "degrau", None),
    ("cpu_api_m", "CPU do pod da API (millicores, kubectl top)", "degrau", 500),
    ("cpu_banco_m", "CPU do banco (millicores, kubectl top)", "degrau", 2000),
]


def mais_recente(alvo: str) -> str | None:
    if os.path.isfile(alvo):
        return alvo
    arquivos = glob.glob(os.path.join(alvo, "**", "*-ao-vivo.csv"), recursive=True)
    return max(arquivos, key=os.path.getmtime) if arquivos else None


def ler(arquivo: str) -> list[dict]:
    try:
        with open(arquivo, newline="", encoding="utf-8") as f:
            return list(csv.DictReader(f))
    except OSError:
        return []


def numero(texto: str):
    try:
        return float(texto)
    except (TypeError, ValueError):
        return None


def main():
    if len(sys.argv) != 2:
        raise SystemExit(__doc__)
    alvo = sys.argv[1]

    plt.rcParams.update({"font.size": 9, "axes.titlesize": 10, "axes.titlelocation": "left"})
    fig, eixos = plt.subplots(4, 2, figsize=(14, 9.5), sharex=True)
    fig.patch.set_facecolor(FUNDO)
    eixos = eixos.flatten()
    estado = {"arquivo": None}

    def salvar_imagem(arquivo: str):
        if arquivo:
            fig.savefig(arquivo.replace("-ao-vivo.csv", "-ao-vivo.png"), dpi=130, facecolor=FUNDO, bbox_inches="tight")

    def desenhar(_quadro):
        arquivo = mais_recente(alvo)
        if arquivo != estado["arquivo"]:
            salvar_imagem(estado["arquivo"])       # guarda a imagem do teste que acabou de terminar
            estado["arquivo"] = arquivo
        if not arquivo:
            fig.suptitle(f"Aguardando um teste em {alvo} ...", x=0.02, ha="left", color=TINTA)
            return
        linhas = ler(arquivo)
        if not linhas:
            return

        x = [int(l["segundo"]) for l in linhas]
        # Onde cada degrau começa: linhas verticais em todos os painéis
        inicios = [(x[i], linhas[i]["trabalhadores"]) for i in range(1, len(linhas))
                   if linhas[i]["fase"] != linhas[i - 1]["fase"]]

        for ax, (coluna, titulo, tipo, limite) in zip(eixos, PAINEIS):
            ax.clear()
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

            y = [numero(l[coluna]) for l in linhas]
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
            if limite:
                ax.axhline(limite, color=CONTEXTO, linewidth=1, linestyle="--")
                ax.annotate(f"limite {limite}m", (0, limite), xycoords=("axes fraction", "data"), xytext=(4, 3),
                            textcoords="offset points", fontsize=8, color=CONTEXTO)
                ax.set_ylim(0, max(limite * 1.15, max((p[1] for p in pontos), default=0) * 1.15))
            else:
                ax.set_ylim(bottom=0)
            agora = "" if ultimo is None else f"   agora: {ultimo:,.1f}".replace(",", "X").replace(".", ",").replace("X", ".")
            ax.set_title(titulo + agora, color=TINTA)
            if coluna == "trabalhadores":
                for inicio, n in [(x[0], linhas[0]["trabalhadores"])] + inicios:
                    ax.annotate(n, (inicio, 1), xycoords=("data", "axes fraction"), xytext=(3, -12),
                                textcoords="offset points", fontsize=8, color=CONTEXTO)

        for ax in eixos[-2:]:
            ax.set_xlabel("segundos desde o início do teste", color=CONTEXTO)

        u = linhas[-1]
        nome = os.path.basename(arquivo).replace("-ao-vivo.csv", "")
        fig.suptitle(f"{nome} · {u['rota']} · degrau {u['fase']}/{u['fases']} · {u['trabalhadores']} trabalhadores · "
                     f"{u['pods']} pod(s) respondendo · {u['hora']}", x=0.02, ha="left", fontsize=11, color=TINTA)

    fig.tight_layout(rect=(0, 0, 1, 0.96))
    animacao = FuncAnimation(fig, desenhar, interval=1000, cache_frame_data=False)  # noqa: F841 - precisa viver
    try:
        plt.show()
    finally:
        salvar_imagem(estado["arquivo"])


if __name__ == "__main__":
    main()
