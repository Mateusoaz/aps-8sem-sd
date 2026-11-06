#!/usr/bin/env python3
"""
Análise de um experimento da Etapa 5 (a pasta criada pelo carga/experimento.py).

Gera, dentro da pasta:
  tabela.md         a tabela da seção 5 da ficha já preenchida, mais procedimento e evidências
  analise.json      os números calculados
  graficos/         um PNG por medida: linha do tempo segundo a segundo com os eventos marcados
                    (experimentos de falha, HPA e rolling update) ou comparação entre cenários
                    (escala, cache, fila)

Uso:  python carga/analise_etapa5.py resultados/etapa5/<pasta>   [--p95-aceitavel 100]
Requer: pip install matplotlib
"""
from __future__ import annotations

import argparse
import csv
import gzip
import json
import os
import statistics
import sys
from collections import Counter, defaultdict

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import loadgen  # noqa: E402  (reaproveita percentil, resumir e nome_do_servico)

APP = "air-quality-api"

# Paleta de referência: uma medida por gráfico, em azul; contexto (eventos, limites, ideal) em tinta secundária
COR = "#2a78d6"
COR_2 = "#eb6834"
TINTA = "#0b0b0b"
TINTA_2 = "#52514e"
GRADE = "#e4e3df"
FUNDO = "#fcfcfb"
FAIXA = "#efeeea"

ROTULOS_EVENTO = {
    "acao_pod_apagado": "pod apagado",
    "acao_no_drenado": "drain",
    "drain_concluido": "drain concluído",
    "no_liberado": "uncordon",
    "acao_rollout_inicio": "set image 1.2.0",
    "rollout_fim": "rollout concluído",
    "acao_undo_inicio": "rollout undo",
    "undo_fim": "undo concluído",
    "carga_fim": "fim da carga",
    "hpa_reducao_concluida": "redução concluída",
}


# ================================ Leitura ================================

def ler_csv(caminho: str) -> list[dict]:
    if not os.path.exists(caminho):
        return []
    with open(caminho, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def carregar_registros(prefixos: list[str], inicio: float) -> list[tuple]:
    """Junta as requisições de todos os geradores, no formato do loadgen, com o segundo relativo à execução."""
    registros = []
    for prefixo in prefixos:
        caminho = prefixo + "-requisicoes.csv.gz"
        if not os.path.exists(caminho):
            continue
        with gzip.open(caminho, "rt", encoding="utf-8", newline="") as f:
            for r in csv.DictReader(f):
                ep = float(r["inicio_epoch"])
                registros.append((ep, r["hora"], int(ep - inicio), int(r["fase"]), int(r["trabalhador"]),
                                  int(r["ativos"]), int(r["aquecimento"]), float(r["latencia_ms"]), int(r["status"]),
                                  r["erro"], r["x_pod"], r["x_versao"], r["x_cache"], int(r["bytes"] or 0)))
    registros.sort(key=lambda r: r[0])
    return registros


def serie_por_segundo(registros: list[tuple], duracao: int) -> list[dict]:
    grupos = defaultdict(list)
    for r in registros:
        grupos[r[2]].append(r)
    linhas = []
    for s in range(0, duracao + 1):
        rs = grupos.get(s, [])
        lat = sorted(r[7] for r in rs)
        linhas.append({
            "s": s,
            "ok": sum(1 for r in rs if not r[9]),
            "erros": sum(1 for r in rs if r[9]),
            "p50": loadgen.percentil(lat, 50), "p95": loadgen.percentil(lat, 95), "p99": loadgen.percentil(lat, 99),
            "versoes": Counter(r[11] for r in rs if r[11]),
        })
    return linhas


def cpu_por_segundo(prefixo: str, inicio: float) -> dict[str, dict[int, int]]:
    """kubectl top do gerador 1: CPU somada por serviço em cada amostra -> {serviço: {segundo: millicores}}"""
    por_amostra = defaultdict(lambda: defaultdict(int))
    for r in ler_csv(prefixo + "-top.csv"):
        por_amostra[float(r["epoch"])][loadgen.nome_do_servico(r["pod"])] += int(r["cpu_m"])
    saida = defaultdict(dict)
    for epoch, servicos in por_amostra.items():
        for servico, m in servicos.items():
            saida[servico][int(epoch - inicio)] = m
    return saida


def fmt(v, casas=1, sufixo=""):
    if v is None or v == "":
        return "—"
    texto = f"{v:,.{casas}f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return texto + sufixo


def mediana(valores):
    valores = [v for v in valores if v is not None]
    return statistics.median(valores) if valores else None


# ================================ Gráficos ================================

def estilo(ax):
    ax.set_facecolor(FUNDO)
    for lado in ("top", "right"):
        ax.spines[lado].set_visible(False)
    for lado in ("left", "bottom"):
        ax.spines[lado].set_color(GRADE)
    ax.tick_params(colors=TINTA_2, labelsize=9, length=0)
    ax.grid(axis="y", color=GRADE, linewidth=0.8)
    ax.set_axisbelow(True)


def grafico_tempo(caminho, titulo, subtitulo, x, y, unidade, marcas, tipo="linha", limite=None, faixas=()):
    """Uma medida ao longo do tempo. marcas = [(segundo, rótulo)]; faixas = [(início, fim, rótulo)]."""
    pontos = [(a, b) for a, b in zip(x, y) if b is not None and b != ""]
    if not pontos:
        return
    fig, ax = plt.subplots(figsize=(10, 4.2))
    fig.patch.set_facecolor(FUNDO)
    estilo(ax)
    for ini, fim, rot in faixas:
        ax.axvspan(ini, fim, color=FAIXA, zorder=0)
    px, py = zip(*pontos)
    if tipo == "barra":
        ax.bar(px, py, width=0.9, color=TINTA_2, zorder=3)
    elif tipo == "degrau":
        ax.step(px, py, where="post", color=COR, linewidth=2, zorder=3)
    else:
        ax.plot(px, py, color=COR, linewidth=2, zorder=3)
    topo = max(py) if py else 1
    if limite:
        ax.axhline(limite[0], color=TINTA_2, linewidth=1, linestyle="--")
        ax.annotate(limite[1], (px[0], limite[0]), xytext=(2, 4), textcoords="offset points", fontsize=8, color=TINTA_2)
        topo = max(topo, limite[0])
    ax.set_ylim(0, topo * 1.25 if topo else 1)
    # Eventos: linha vertical fina + rótulo no alto. Eventos a menos de 2 s um do outro viram UM rótulo
    # ("pod criado ×2 · pod pronto"), e rótulos vizinhos alternam em 3 alturas para não encavalar.
    grupos: list[list] = []
    for s, rot in sorted(marcas):
        if grupos and s - grupos[-1][0] < 2:
            grupos[-1][1].append(rot)
        else:
            grupos.append([s, [rot]])
    for i, (s, rotulos) in enumerate(grupos):
        contagem = Counter(rotulos)
        texto = " · ".join(f"{r} ×{n}" if n > 1 else r for r, n in contagem.items())
        ax.axvline(s, color=TINTA_2, linewidth=1, linestyle=":", zorder=2)
        ax.annotate(texto, (s, 1), xycoords=("data", "axes fraction"), xytext=(3, -10 - 11 * (i % 3)),
                    textcoords="offset points", fontsize=7.5, color=TINTA, ha="left")
    ax.set_xlim(min(px[0], *(m[0] for m in marcas)) if marcas else px[0], max(px[-1], *(m[0] for m in marcas)) + 1 if marcas else px[-1] + 1)
    ax.set_ylabel(unidade, color=TINTA_2, fontsize=10)
    ax.set_xlabel("segundos desde o início da carga", color=TINTA_2, fontsize=10)
    fig.suptitle(titulo, x=0.07, ha="left", fontsize=12, color=TINTA, y=0.99)
    fig.text(0.07, 0.905, subtitulo, fontsize=8.5, color=TINTA_2)
    fig.tight_layout(rect=(0, 0, 1, 0.9))
    fig.savefig(caminho, dpi=150, facecolor=FUNDO)
    plt.close(fig)


def grafico_barras(caminho, titulo, subtitulo, rotulos, valores, unidade, referencia=None):
    """Uma medida por cenário. referencia = (valores, rótulo) desenhada como marcador tracejado (ex.: ideal)."""
    fig, ax = plt.subplots(figsize=(8, 4.2))
    fig.patch.set_facecolor(FUNDO)
    estilo(ax)
    xs = range(len(rotulos))
    vals = [v or 0 for v in valores]
    ax.bar(xs, vals, width=0.55, color=COR, zorder=3)
    for x, v in zip(xs, vals):
        ax.annotate(fmt(v, 0 if v >= 100 else 1), (x, v), xytext=(0, 4), textcoords="offset points", ha="center",
                    fontsize=9, color=TINTA)
    topo = max(vals) if vals else 1
    if referencia:
        ref, rot = referencia
        ax.plot(list(xs), ref, color=TINTA_2, linestyle="--", linewidth=1.2, marker="_", markersize=18, zorder=4)
        ax.annotate(rot, (len(rotulos) - 1, ref[-1]), xytext=(8, 0), textcoords="offset points", va="center",
                    fontsize=8, color=TINTA_2)
        topo = max(topo, max(ref))
    ax.set_xticks(list(xs))
    ax.set_xticklabels(rotulos)
    ax.set_ylim(0, topo * 1.2 if topo else 1)
    ax.set_ylabel(unidade, color=TINTA_2, fontsize=10)
    fig.suptitle(titulo, x=0.08, ha="left", fontsize=12, color=TINTA, y=0.99)
    fig.text(0.08, 0.905, subtitulo, fontsize=8.5, color=TINTA_2)
    fig.tight_layout(rect=(0, 0, 1, 0.9))
    fig.savefig(caminho, dpi=150, facecolor=FUNDO)
    plt.close(fig)


# ================================ Análises ================================

def resumo_execucao(ex: dict) -> dict:
    regs = carregar_registros(ex["prefixos"], ex["inicio"])
    medidos = [r for r in regs if not r[6]]
    janela = max(1.0, ex["duracao_s"] - ex["aquecimento_s"])
    r = loadgen.resumir(medidos, janela, ex["trabalhadores"], [])
    cpu = cpu_por_segundo(ex["prefixos"][0], ex["inicio"])
    na_janela = lambda d: [m for s, m in d.items() if s >= ex["aquecimento_s"]]  # noqa: E731
    r["cpu_api_m"] = mediana(na_janela(cpu.get(APP, {})))
    r["cpu_banco_m"] = mediana(na_janela(cpu.get("postgres", {})))
    total_cache = sum(r["por_cache"].values())
    r["pct_cache_hit"] = round(100 * r["por_cache"].get("HIT", 0) / total_cache, 1) if total_cache else None
    return r


def analisar_comparacao(pasta, meta, eventos):
    linhas = []
    for ex in meta["execucoes"]:
        r = resumo_execucao(ex)
        fila = next((e for e in eventos if e["tipo"] == "fila_vazia" and float(e["epoch"]) > ex["fim"] - 1), None)
        linhas.append({"rotulo": ex["rotulo"], "replicas": ex.get("replicas"), "resumo": r, "rota": ex["rota"],
                       "trabalhadores": ex["trabalhadores"], "duracao_s": ex["duracao_s"],
                       "fila": fila["detalhe"] if fila else None})
    resultado = {"linhas": linhas}
    destino = os.path.join(pasta, "graficos")
    os.makedirs(destino, exist_ok=True)
    rotulos = [l["rotulo"] for l in linhas]
    sub = f"{linhas[0]['rota']} · {linhas[0]['trabalhadores']} trabalhadores · {linhas[0]['duracao_s']:g} s por cenário"

    if meta.get("parametro") == "replicas":
        base = linhas[0]["resumo"]["vazao_req_s"] or 1
        for l in linhas:
            n = l["replicas"]
            ganho = (l["resumo"]["vazao_req_s"] or 0) / base
            l["ganho_medido"] = round(ganho, 2)
            l["ganho_ideal"] = n
            # Lei de Amdahl: G(N) = 1 / (s + (1 - s)/N)  ->  s = (N/G - 1) / (N - 1)
            # Só faz sentido com ganho real (1 < G <= N); sem ganho, a fórmula daria s >= 1
            l["s_estimado"] = round((n / ganho - 1) / (n - 1), 3) if n > 1 and 1 < ganho <= n else None
        estimativas = [l["s_estimado"] for l in linhas if l["s_estimado"] is not None]
        resultado["s_amdahl"] = round(statistics.fmean(estimativas), 3) if estimativas else None
        grafico_barras(os.path.join(destino, "vazao.png"), "Vazão por número de réplicas", sub, rotulos,
                       [l["resumo"]["vazao_req_s"] for l in linhas], "req/s",
                       ([base * l["replicas"] for l in linhas], "ideal (N × 1 réplica)"))
        grafico_barras(os.path.join(destino, "ganho.png"), "Ganho em relação a 1 réplica", sub, rotulos,
                       [l["ganho_medido"] for l in linhas], "vezes", ([l["replicas"] for l in linhas], "ideal"))
    else:
        grafico_barras(os.path.join(destino, "vazao.png"), "Vazão", sub, rotulos, [l["resumo"]["vazao_req_s"] for l in linhas], "req/s")
    for chave, titulo in (("p50", "Latência p50"), ("p95", "Latência p95"), ("p99", "Latência p99")):
        grafico_barras(os.path.join(destino, f"{chave}.png"), titulo, sub, rotulos,
                       [l["resumo"]["latencia_ms"][chave] for l in linhas], "ms")
    grafico_barras(os.path.join(destino, "erros.png"), "Taxa de erro", sub, rotulos,
                   [l["resumo"]["taxa_erro_pct"] for l in linhas], "%")
    grafico_barras(os.path.join(destino, "cpu-api.png"), "CPU do pod da API (soma das réplicas, kubectl top)", sub,
                   rotulos, [l["resumo"]["cpu_api_m"] for l in linhas], "millicores")
    grafico_barras(os.path.join(destino, "cpu-banco.png"), "CPU do banco (kubectl top)", sub, rotulos,
                   [l["resumo"]["cpu_banco_m"] for l in linhas], "millicores")
    return resultado


def marcas_de(eventos, inicio, fim, extra=(), com_pods=False):
    marcas = []
    for e in eventos:
        ep = float(e["epoch"])
        if not (inicio - 1 <= ep <= fim + 1):
            continue
        if com_pods and "app=" + APP in e.get("detalhe", ""):
            # Demo: as ações são digitadas à mão, então marcamos o que o Kubernetes fez com os pods
            rot = {"pod_criado": "+pod", "pod_pronto": "pronto", "pod_terminando": "saindo"}.get(e["tipo"])
            if rot:
                marcas.append((ep - inicio, f"{rot} {e['versao']}" if e["tipo"] == "pod_criado" else rot))
                continue
        if e["tipo"] in ROTULOS_EVENTO:
            marcas.append((ep - inicio, ROTULOS_EVENTO[e["tipo"]]))
        elif e["tipo"] == "hpa_decisao":
            marcas.append((ep - inicio, "HPA " + e["detalhe"].split(" réplicas")[0].replace(" -> ", "→")))
    marcas += [(s, rot) for s, rot in extra]
    return marcas


def volta_ao_normal(serie, desde, vaz_normal, p95_normal, sustentar=5):
    """
    Primeiro segundo >= desde a partir do qual, numa janela de 'sustentar' segundos, a vazão MÉDIA voltou a
    >= 85% do normal e a MEDIANA do p95 a <= 1,5x o normal. Média e mediana porque a vazão segundo a segundo
    oscila bastante mesmo sem falha nenhuma.
    """
    if not vaz_normal:
        return None
    por_s = {l["s"]: l for l in serie}
    for s in range(int(desde) + 1, max(por_s) - sustentar + 2):
        janela = [por_s.get(s + k) for k in range(sustentar)]
        if not all(janela):
            continue
        p95s = [j["p95"] for j in janela if j["p95"] is not None]
        if (statistics.fmean(j["ok"] for j in janela) >= 0.85 * vaz_normal
                and p95s and statistics.median(p95s) <= 1.5 * (p95_normal or 0)):
            return s
    return None


def analisar_linha_do_tempo(pasta, meta, eventos, p95_aceitavel):
    ex = meta["execucoes"][0]
    inicio, fim = ex["inicio"], ex["fim"]
    regs = carregar_registros(ex["prefixos"], inicio)
    # Só os segundos inteiros de carga: o último segundo é parcial (os geradores estão terminando)
    duracao = int(ex["duracao_s"]) - 1
    serie = serie_por_segundo(regs, duracao)
    cpu = cpu_por_segundo(ex["prefixos"][0], inicio)
    # Réplicas a partir de 5 s antes da carga (a preparação antes disso só aperta o gráfico)
    replicas = [(float(r["epoch"]) - inicio, int(r["prontas"])) for r in ler_csv(os.path.join(pasta, "replicas.csv"))
                if float(r["epoch"]) - inicio >= -5]
    hpa = [(float(r["epoch"]) - inicio, r) for r in ler_csv(os.path.join(pasta, "hpa.csv"))]
    fim_obs = meta.get("observacao_fim", fim)
    ev = lambda tipo: [e for e in eventos if e["tipo"] == tipo]  # noqa: E731
    rel = lambda e: float(e["epoch"]) - inicio  # noqa: E731
    resultado = {"requisicoes": len(regs), "falhas": sum(1 for r in regs if r[9]),
                 "por_erro": dict(Counter(r[9] for r in regs if r[9]).most_common()),
                 "versoes": dict(Counter(r[11] for r in regs if r[11]).most_common())}
    marcas_extra = []
    faixas = []
    tipo = meta["experimento"]

    acao = meta.get("acao")
    if acao:                                     # pod apagado / nó drenado
        t_acao = acao["epoch"] - inicio
        antes = [l for l in serie if ex["aquecimento_s"] <= l["s"] < t_acao]
        vaz_normal = mediana([l["ok"] for l in antes])
        p95_normal = mediana([l["p95"] for l in antes])
        criados = {e["objeto"] for e in ev("pod_criado") if "app=" + APP in e["detalhe"] and float(e["epoch"]) >= acao["epoch"] - 1}
        prontos = [e for e in ev("pod_pronto") if e["objeto"] in criados]
        substituto = min((rel(e) for e in prontos), default=None)
        todos = max((rel(e) for e in prontos), default=None)
        normal = volta_ao_normal(serie, t_acao, vaz_normal, p95_normal)
        removidos = [e for e in ev("pod_terminando") if float(e["epoch"]) >= acao["epoch"] - 1]
        resultado.update({
            "acao": acao["descricao"], "t_acao_s": round(t_acao, 1),
            "falhas_apos_acao": sum(1 for r in regs if r[9] and r[0] >= acao["epoch"]),
            # Mede a indisponibilidade melhor que a contagem: quantos segundos tiveram pelo menos uma falha
            "segundos_com_erro": sum(1 for l in serie if l["erros"]),
            "segundos_sem_resposta_ok": sum(1 for l in serie if l["s"] >= t_acao and l["ok"] == 0),
            "vazao_normal": vaz_normal, "p95_normal": p95_normal,
            "tempo_ate_substituto_pronto_s": round(substituto - t_acao, 1) if substituto is not None else None,
            "tempo_ate_todos_substitutos_s": round(todos - t_acao, 1) if todos is not None else None,
            "tempo_ate_patamar_normal_s": round(normal - t_acao, 1) if normal is not None else None,
            "pods_retirados": [f"{e['objeto']} ({e['no']}, {e['hora']})" for e in removidos],
            "pods_criados": [f"{e['objeto']} -> {e['no']} pronto às {e['hora']}" for e in prontos],
        })
        if substituto is not None:
            marcas_extra.append((substituto, "substituto pronto"))
        if normal is not None:
            marcas_extra.append((normal, "patamar normal"))

    if tipo.startswith("rolling"):
        segmentos = []
        for ini_t, fim_t, nome in (("acao_rollout_inicio", "rollout_fim", "rolling update"), ("acao_undo_inicio", "undo_fim", "rollout undo")):
            a, b = ev(ini_t), ev(fim_t)
            if not a or not b:
                continue
            s0, s1 = rel(a[0]), rel(b[0])
            dentro = [r for r in regs if a[0] and s0 <= r[0] - inicio <= s1 + 10]
            seg_serie = [l for l in serie if s0 <= l["s"] <= s1 + 10]
            antes = [l for l in serie if max(ex["aquecimento_s"], s0 - 15) <= l["s"] < s0]
            normal = volta_ao_normal(serie, s0, mediana([l["ok"] for l in antes]), mediana([l["p95"] for l in antes]))
            segmentos.append({
                "cenario": nome, "inicio_s": round(s0, 1), "duracao_s": round(s1 - s0, 1),
                "requisicoes": len(dentro), "falhas": sum(1 for r in dentro if r[9]),
                "por_erro": dict(Counter(r[9] for r in dentro if r[9])),
                "versoes_vistas": sorted({r[11] for r in dentro if r[11]}, key=lambda v: [int(x) for x in v.split(".") if x.isdigit()]),
                "segundos_com_duas_versoes": sum(1 for l in seg_serie if len(l["versoes"]) > 1),
                "tempo_ate_patamar_normal_s": round(normal - s0, 1) if normal is not None else None,
            })
            faixas.append((s0, s1, nome))
        resultado["segmentos"] = segmentos
        resultado["prestop"] = meta.get("prestop")

    if tipo == "hpa":
        def replicas_em(t):
            antes = [r for s, r in hpa if s <= t]
            return antes[-1] if antes else (hpa[0][1] if hpa else {})
        decisoes = [e for e in ev("hpa_decisao") if float(e["epoch"]) >= inicio]
        subida = [e for e in decisoes if int(e["detalhe"].split(" -> ")[1].split()[0]) > int(e["detalhe"].split(" -> ")[0])]
        descida = [e for e in decisoes if e not in subida and float(e["epoch"]) >= fim - 1]
        primeira = subida[0] if subida else None
        novo_pronto = min((rel(e) for e in ev("pod_pronto") if "app=" + APP in e["detalhe"]
                           and primeira and float(e["epoch"]) > float(primeira["epoch"])), default=None)
        p95_ok = None
        if primeira:
            por_s = {l["s"]: l for l in serie}
            for s in range(int(rel(primeira)), duracao - 9):
                if all(por_s.get(s + k) and por_s[s + k]["p95"] is not None and por_s[s + k]["p95"] <= p95_aceitavel
                       for k in range(10)):
                    p95_ok = s
                    break
        linha = lambda nome, t, obs="": {"evento": nome, "t_s": round(t, 1) if t is not None else None,  # noqa: E731
                                          "hora": None if t is None else __import__("datetime").datetime.fromtimestamp(inicio + t).strftime("%H:%M:%S"),
                                          "replicas": (replicas_em(t).get("atuais") if t is not None else None), "obs": obs}
        cpu_txt = lambda t: f"CPU {replicas_em(t).get('cpu_pct', '?')}%" if t is not None else ""  # noqa: E731
        p95_txt = lambda t: next((f"p95 {fmt(l['p95'])} ms" for l in serie if t is not None and l["s"] == int(t) and l["p95"]), "")  # noqa: E731
        maximo = max((int(r.get("atuais") or 0) for _, r in hpa), default=None)
        resultado["linha_do_tempo"] = [
            linha("Início da carga (rampa)", 0, cpu_txt(0)),
            linha("Primeira decisão de escala (SuccessfulRescale)", rel(primeira) if primeira else None,
                  primeira["detalhe"] if primeira else "sem decisão de escala"),
            linha("Novos pods prontos (1/1)", novo_pronto, p95_txt(novo_pronto)),
            linha(f"Latência p95 de volta ao patamar aceitável (≤ {p95_aceitavel:g} ms por 10 s)", p95_ok, p95_txt(p95_ok)),
            linha("Fim da carga / início da redução", fim - inicio,
                  f"primeira redução: {descida[0]['hora']} ({descida[0]['detalhe']})" if descida else "redução não observada"),
        ]
        reducao = ev("hpa_reducao_concluida")
        if reducao:
            resultado["linha_do_tempo"].append(linha("Redução concluída (mínimo de 2)", rel(reducao[0]), ""))
        resultado["replicas_maximas"] = maximo
        resultado["decisoes"] = [f"{e['hora']} {e['detalhe']}" for e in decisoes]
        if novo_pronto is not None:
            marcas_extra.append((novo_pronto, "novos pods prontos"))
        if p95_ok is not None:
            marcas_extra.append((p95_ok, "p95 aceitável"))

    # ---------------- gráficos: um por medida ----------------
    destino = os.path.join(pasta, "graficos")
    os.makedirs(destino, exist_ok=True)
    if meta.get("demo"):
        prontas = [n for s, n in replicas if 0 <= s <= duracao]
        resultado.update({
            "segundos_com_erro": sum(1 for l in serie if l["erros"]),
            "segundos_sem_resposta_ok": sum(1 for l in serie if l["ok"] == 0),
            "replicas_prontas_min": min(prontas, default=None), "replicas_prontas_max": max(prontas, default=None),
            "eventos_pods": [f"{e['hora']} {e['tipo'].replace('_', ' ')}: {e['objeto']} ({e['no']}, versão {e['versao']})"
                             for e in eventos if "app=" + APP in e.get("detalhe", "") and inicio - 1 <= float(e["epoch"]) <= fim + 1
                             and e["tipo"] in ("pod_criado", "pod_pronto", "pod_terminando", "pod_removido", "pod_nao_pronto")],
        })
    marcas = marcas_de(eventos, inicio, fim_obs, marcas_extra, com_pods=bool(meta.get("demo")))
    marcas_carga = [m for m in marcas if m[0] <= duracao + 1]
    sub = f"{ex['rota']} · {ex['trabalhadores']} trabalhadores" + (f" (rampa de {ex['rampa_s']:g} s)" if ex.get("rampa_s") else "")
    x = [l["s"] for l in serie]
    nome = meta["experimento"]
    grafico_tempo(os.path.join(destino, "vazao.png"), f"Vazão — {nome}", sub, x, [l["ok"] for l in serie], "respostas OK por segundo", marcas_carga, faixas=faixas)
    grafico_tempo(os.path.join(destino, "erros.png"), f"Erros — {nome}", sub, x, [l["erros"] for l in serie], "erros por segundo", marcas_carga, tipo="barra", faixas=faixas)
    for chave in ("p50", "p95", "p99"):
        lim = (p95_aceitavel, f"aceitável {p95_aceitavel:g} ms") if (chave == "p95" and nome == "hpa") else None
        grafico_tempo(os.path.join(destino, f"{chave}.png"), f"Latência {chave} — {nome}", sub, x, [l[chave] for l in serie], "ms", marcas_carga, limite=lim, faixas=faixas)
    if replicas:
        grafico_tempo(os.path.join(destino, "replicas-prontas.png"), f"Réplicas prontas da {APP} — {nome}", sub,
                      [s for s, _ in replicas if s <= fim_obs - inicio + 1], [n for s, n in replicas if s <= fim_obs - inicio + 1],
                      "pods 1/1", marcas, tipo="degrau", faixas=faixas)
    if nome == "hpa" and hpa:
        grafico_tempo(os.path.join(destino, "hpa-desejadas.png"), f"Réplicas desejadas pelo HPA — {nome}", sub,
                      [s for s, _ in hpa], [int(r["desejadas"]) if r["desejadas"] else None for _, r in hpa], "réplicas", marcas, tipo="degrau")
        grafico_tempo(os.path.join(destino, "hpa-cpu.png"), f"CPU média medida pelo HPA — {nome}", sub,
                      [s for s, _ in hpa], [int(r["cpu_pct"]) if r["cpu_pct"] else None for _, r in hpa], "% do requests",
                      marcas, limite=(50, "meta 50%"))
    if tipo.startswith("rolling") or len(resultado["versoes"]) > 1:
        novas = []
        for l in serie:
            tot = sum(l["versoes"].values())
            novas.append(round(100 * l["versoes"].get("1.2.0", 0) / tot, 1) if tot else None)
        grafico_tempo(os.path.join(destino, "versao-nova.png"), f"Respostas da versão 1.2.0 — {nome}", sub, x, novas,
                      "% das respostas", marcas_carga, faixas=faixas)
    for servico, arquivo, titulo, limite in ((APP, "cpu-api.png", "CPU da API (soma das réplicas)", None),
                                              ("postgres", "cpu-banco.png", "CPU do banco", (2000, "limite 2000m"))):
        d = cpu.get(servico, {})
        if d:
            xs = sorted(d)
            grafico_tempo(os.path.join(destino, arquivo), f"{titulo} — {nome}", sub + " · kubectl top (atraso de ~15 s)",
                          xs, [d[s] for s in xs], "millicores", marcas_carga, limite=limite, faixas=faixas)
    return resultado


# ================================ Tabela (seção 5 da ficha) ================================

HIPOTESES = {
    "escala": "Com N réplicas a vazão cresce quase N vezes enquanto o gargalo é a CPU de cada pod (500m); "
              "a partir de algum N o ganho cai, porque banco, gateway e a CPU da máquina são compartilhados.",
    "hpa": "Com a carga em rampa, o HPA aumenta as réplicas em alguns ciclos de 15 s; o p95 sobe enquanto os pods novos "
           "não estão prontos e volta ao patamar quando eles entram no Service. A redução só começa ~5 min depois.",
    "pod-apagado": "Falham só as requisições que estavam no pod no instante da exclusão; o ReplicaSet cria o substituto "
                   "em segundos e a vazão volta quando ele passa na readiness.",
    "no-drenado": "O drain despeja os pods com aviso (encerramento gracioso + preStop): poucas ou nenhuma falha; "
                  "os pods são recriados nos outros nós. Com a outra réplica atendendo, o serviço não para.",
    "rolling": "Com maxUnavailable 0 e preStop de 5 s, a troca de versão não gera falhas e as duas versões "
               "atendem ao mesmo tempo durante a transição.",
    "rolling-sem-prestop": "Sem o preStop, o pod antigo recebe o SIGTERM enquanto o gateway ainda lhe manda requisições: "
                           "aparecem algumas falhas (502/504) a cada pod trocado.",
    "cache": "Com o cache, quase todas as consultas são respondidas pelo Redis: a vazão sobe, a latência cai e a CPU do "
             "banco fica perto de zero. Sem cache, o banco vira o gargalo.",
    "fila": "Com a fila, o POST só grava e publica: responde mais rápido. Sem a fila, cada POST também avalia a regra "
            "de alerta no banco: latência maior e vazão menor, mas sem atraso nos alertas.",
    "demo": "Demonstração ao vivo: ao escalar, a vazão sobe depois que os pods novos passam na readiness; ao apagar "
            "um pod, o ReplicaSet recria outro e quase nada falha; na troca de versão, as duas versões atendem juntas.",
}


def tabela_md(pasta, meta, analise, p95_aceitavel) -> str:
    nome = meta["experimento"]
    ex0 = meta["execucoes"][0]
    linhas = [f"# Experimento: {nome}", "",
              f"Data: {meta['inicio']} · comando: `{meta['comando']}`" + (" · **modo rápido (durações reduzidas)**" if meta.get("rapido") else ""), "",
              "## Hipótese (sugerida, revise antes de entregar)", "", HIPOTESES.get(nome, ""), "",
              "## Procedimento", ""]
    for ex in meta["execucoes"]:
        linhas.append(f"- **{ex['rotulo']}:** `{ex['rota']}`, {ex['trabalhadores']} trabalhadores em {ex['geradores']} "
                      f"gerador(es), {ex['duracao_s']:g} s" + (f", rampa de {ex['rampa_s']:g} s" if ex.get("rampa_s") else "")
                      + f", {ex['aquecimento_s']:g} s de aquecimento descartados")
    linhas += ["", "## Resultados", ""]

    if meta.get("tipo") == "comparacao":
        if meta.get("parametro") == "replicas":
            linhas += [f"### 5.1 Escalabilidade horizontal manual — rota: `{ex0['rota']}` · trabalhadores: {ex0['trabalhadores']} · duração: {ex0['duracao_s']:g} s", "",
                       "| Réplicas | Vazão (req/s) | p50 (ms) | p95 (ms) | Erros (%) | Ganho medido | Ganho ideal | s estimado (Amdahl) | CPU API (m) | CPU banco (m) |",
                       "|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|"]
            for l in analise["linhas"]:
                r = l["resumo"]
                linhas.append(f"| {l['replicas']} | {fmt(r['vazao_req_s'])} | {fmt(r['latencia_ms']['p50'])} | {fmt(r['latencia_ms']['p95'])} | "
                              f"{fmt(r['taxa_erro_pct'], 2)} | {fmt(l['ganho_medido'], 2)} | {l['ganho_ideal']} | {fmt(l['s_estimado'], 3)} | "
                              f"{fmt(r['cpu_api_m'], 0)} | {fmt(r['cpu_banco_m'], 0)} |")
            s = analise.get("s_amdahl")
            if s is not None:
                linhas += ["", f"**Lei de Amdahl:** Ganho(N) = 1 / (s + (1 − s)/N). Fração serial estimada s ≈ {fmt(s, 3)} "
                               f"(média das estimativas) → ganho máximo teórico ≈ {fmt(1 / s if s > 0 else None, 1)}×. "
                               "s representa o que não se divide entre as réplicas: o banco único, a fila, o gateway e a CPU da máquina."]
        else:
            titulo = "5.5 Cache" if meta.get("parametro") == "cache" else "5.5 Processamento assíncrono (fila)"
            linhas += [f"### {titulo} — rota: `{ex0['rota']}` · trabalhadores: {ex0['trabalhadores']}", "",
                       "| Cenário | Vazão (req/s) | p50 (ms) | p95 (ms) | Erros (%) | CPU do banco (m) | CPU da API (m) | Cache HIT (%) | Fila ao fim |",
                       "|---|---:|---:|---:|---:|---:|---:|---:|---|"]
            for l in analise["linhas"]:
                r = l["resumo"]
                linhas.append(f"| {l['rotulo']} | {fmt(r['vazao_req_s'])} | {fmt(r['latencia_ms']['p50'])} | {fmt(r['latencia_ms']['p95'])} | "
                              f"{fmt(r['taxa_erro_pct'], 2)} | {fmt(r['cpu_banco_m'], 0)} | {fmt(r['cpu_api_m'], 0)} | "
                              f"{fmt(r['pct_cache_hit'])} | {l['fila'] or '—'} |")
    elif meta.get("demo"):
        linhas += ["### Demonstração ao vivo (seção 6 da ficha)", "",
                   "| Requisições | Falhas | Segundos com falha | Segundos sem resposta OK | Réplicas prontas (mín.–máx.) | Versões que responderam |",
                   "|---:|---:|---:|---:|---|---|",
                   f"| {analise['requisicoes']} | {analise['falhas']} | {analise['segundos_com_erro']} | {analise['segundos_sem_resposta_ok']} | "
                   f"{analise['replicas_prontas_min']}–{analise['replicas_prontas_max']} | "
                   f"{', '.join(f'{v} ({n})' for v, n in analise['versoes'].items()) or '—'} |",
                   "", f"Erros por tipo: {analise['por_erro'] or 'nenhum'}", "",
                   "O que o Kubernetes fez com os pods da API, com horário:", ""] + [f"- {e}" for e in analise["eventos_pods"]]
    elif nome == "hpa":
        linhas += ["### 5.2 HPA — linha do tempo", "", "| Evento | Hora | t (s) | Réplicas | Observação |", "|---|---|---:|---:|---|"]
        for l in analise["linha_do_tempo"]:
            linhas.append(f"| {l['evento']} | {l['hora'] or '—'} | {fmt(l['t_s'])} | {l['replicas'] if l['replicas'] is not None else '—'} | {l['obs']} |")
        linhas += ["", f"Réplicas máximas: {analise.get('replicas_maximas')} · requisições: {analise['requisicoes']} · "
                       f"falhas: {analise['falhas']}", "", "Decisões do HPA:", ""] + [f"- {d}" for d in analise["decisoes"]]
    else:
        linhas += ["### 5.3 Resiliência e 5.4 Rolling update", "",
                   "| Cenário | Requisições | Falhas | Tempo até pod substituto pronto | Tempo até patamar normal | Versões vistas |",
                   "|---|---:|---:|---:|---:|---|"]
        if analise.get("acao"):
            linhas.append(f"| {analise['acao']} | {analise['requisicoes']} | {analise['falhas']} | "
                          f"{fmt(analise['tempo_ate_substituto_pronto_s'], 1, ' s')} | {fmt(analise['tempo_ate_patamar_normal_s'], 1, ' s')} | — |")
        for seg in analise.get("segmentos", []):
            linhas.append(f"| {seg['cenario']}{'' if analise.get('prestop', True) else ' (sem preStop)'} | {seg['requisicoes']} | {seg['falhas']} | — | "
                          f"{fmt(seg['tempo_ate_patamar_normal_s'], 1, ' s')} | {', '.join(seg['versoes_vistas'])} "
                          f"({seg['segundos_com_duas_versoes']} s com as duas) |")
        if analise.get("acao"):
            linhas += ["", f"Vazão normal antes da ação: {fmt(analise['vazao_normal'], 0)} req/s · p95 normal: {fmt(analise['p95_normal'])} ms · "
                           f"falhas depois da ação: {analise['falhas_apos_acao']} · erros por tipo: {analise['por_erro'] or 'nenhum'}",
                       f"Segundos com pelo menos uma falha: {analise['segundos_com_erro']} · "
                       f"segundos sem nenhuma resposta OK (serviço fora do ar): {analise['segundos_sem_resposta_ok']}",
                       f"Todos os substitutos prontos em: {fmt(analise['tempo_ate_todos_substitutos_s'], 1, ' s')}", "",
                       "Pods retirados:", ""] + [f"- {p}" for p in analise["pods_retirados"]] + ["", "Pods criados:", ""] + \
                      [f"- {p}" for p in analise["pods_criados"]]
        for seg in analise.get("segmentos", []):
            linhas.append(f"\n{seg['cenario']}: começou em t = {fmt(seg['inicio_s'])} s, levou {fmt(seg['duracao_s'])} s; erros: {seg['por_erro'] or 'nenhum'}")
        linhas += ["", "Critério de \"patamar normal\": numa janela de 5 s, vazão média ≥ 85% e mediana do p95 ≤ 1,5× os valores (medianas) dos segundos anteriores à ação."]

    linhas += ["", "## Evidências (nesta pasta)", "",
               "- `graficos/`: um gráfico por medida" + (", linha do tempo com os eventos marcados" if meta.get("tipo") != "comparacao" else ", comparação entre cenários"),
               "- `eventos.csv`: tudo o que o Kubernetes fez, com horário (pods criados, prontos, removidos; decisões do HPA; ações)",
               "- `replicas.csv`, `hpa.csv`: réplicas prontas e estado do HPA a cada segundo",
               "- `*-requisicoes.csv.gz`, `*-segundos.csv`, `*-resumo.json`: arquivos brutos de cada gerador",
               "", "## Análise crítica (escrever)", "",
               "A hipótese se confirmou? Se não, por quê? Qual recurso limitou? O que mudaria o resultado?", ""]
    return "\n".join(linhas)


def main():
    p = argparse.ArgumentParser(description="Tabelas e gráficos de um experimento da Etapa 5.")
    p.add_argument("pasta")
    p.add_argument("--p95-aceitavel", type=float, default=100, help="patamar aceitável do p95 no HPA, em ms (padrão: 100)")
    args = p.parse_args()
    with open(os.path.join(args.pasta, "experimento.json"), encoding="utf-8") as f:
        meta = json.load(f)
    if not meta.get("execucoes"):
        raise SystemExit("experimento sem execuções registradas")
    eventos = ler_csv(os.path.join(args.pasta, "eventos.csv"))
    if meta.get("tipo") == "comparacao":
        analise = analisar_comparacao(args.pasta, meta, eventos)
    else:
        analise = analisar_linha_do_tempo(args.pasta, meta, eventos, args.p95_aceitavel)
    with open(os.path.join(args.pasta, "analise.json"), "w", encoding="utf-8") as f:
        json.dump(analise, f, ensure_ascii=False, indent=2, default=str)
    with open(os.path.join(args.pasta, "tabela.md"), "w", encoding="utf-8") as f:
        f.write(tabela_md(args.pasta, meta, analise, args.p95_aceitavel))
    print(f">> {os.path.join(args.pasta, 'tabela.md')} e graficos/ gerados")


if __name__ == "__main__":
    main()
