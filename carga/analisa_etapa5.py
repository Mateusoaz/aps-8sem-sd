#!/usr/bin/env python3
"""Consolida resultados/etapa5/ nas tabelas da ficha e em um gráfico por experimento.
Uso (na raiz do repositório): python carga/analisa_etapa5.py
Grava em resultados/etapa5/: tabelas.json e grafico-*.png
"""
import csv
import datetime
import json
import re
import statistics

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

PASTA = "resultados/etapa5"
AZUL, CINZA, VERMELHO, LARANJA = "#1f6fb5", "#8a8f98", "#b3323a", "#b4581a"


def resumo(nome):
    return json.load(open(f"{PASTA}/{nome}-resumo.json", encoding="utf-8"))


def serie(nome):
    return [{k: (float(v) if k not in ("hora",) and v != "" else v) for k, v in l.items()}
            for l in csv.DictReader(open(f"{PASTA}/{nome}-serie.csv", encoding="utf-8"))]


def recursos(nome):
    amostras = [json.loads(l) for l in open(f"{PASTA}/{nome}-recursos.jsonl", encoding="utf-8")]

    def cpu(prefixo):
        por_amostra = [sum(int(m) for m in re.findall(rf"^{prefixo}\S*\s+(\d+)m", a["top_pods"], re.M)) for a in amostras]
        return max(por_amostra) if por_amostra else None

    return {"cpu_api": cpu("air-quality-api"), "cpu_banco": cpu("postgres"),
            "cpu_maquina": max(a["cpu_maquina_pct"] for a in amostras),
            "memoria_maquina": max(a["memoria_maquina_pct"] for a in amostras)}


def media(valores):
    valores = [v for v in valores if v is not None]
    return round(statistics.mean(valores), 2) if valores else None


def tabela_escala(prefixo):
    linhas, base = [], None
    for n in (1, 2, 4, 8):
        grupo = [resumo(f"{prefixo}-r{n}-exec{i}") for i in (1, 2, 3)]
        rec = [recursos(f"{prefixo}-r{n}-exec{i}") for i in (1, 2, 3)]
        vazao = media([g["vazao_req_s"] for g in grupo])
        base = base or vazao
        ganho = vazao / base
        linhas.append({"replicas": n, "vazao": vazao, "vazao_min": min(g["vazao_req_s"] for g in grupo),
                       "vazao_max": max(g["vazao_req_s"] for g in grupo),
                       "p50": media([g["p50_ms"] for g in grupo]), "p95": media([g["p95_ms"] for g in grupo]),
                       "erros": media([g["taxa_erro_pct"] for g in grupo]), "ganho": round(ganho, 2), "ideal": n,
                       # Amdahl: s = (N/ganho - 1) / (N - 1)
                       "s_amdahl": round((n / ganho - 1) / (n - 1), 3) if n > 1 else None,
                       "cpu_api": media([r["cpu_api"] for r in rec]), "cpu_banco": media([r["cpu_banco"] for r in rec]),
                       "cpu_maquina": media([r["cpu_maquina"] for r in rec])})
    return linhas


def epoca_iso(texto):
    return datetime.datetime.fromisoformat(texto.replace("Z", "+00:00")).timestamp()


def recuperacao(nome):
    """Falhas, tempo até o substituto ficar pronto e tempo até voltar ao patamar normal."""
    r = resumo(nome)
    evento = r["eventos"][0]["epoch"]
    pods = json.load(open(f"{PASTA}/{nome}-pods.json", encoding="utf-8"))
    antes = {p["nome"] for a in pods if a["epoch"] < evento for p in a["pods"]}
    pronto = None
    for a in pods:
        if a["epoch"] > evento and any(p["pronto"] and p["nome"] not in antes for p in a["pods"]):
            pronto = round(a["epoch"] - evento, 1)
            break
    s = serie(nome)
    anterior = [x["p95_ms"] for x in s if x["epoch"] < evento and x["epoch"] > r["inicio_epoch"] + 12 and x["p95_ms"] != ""]
    teto = statistics.median(anterior) * 1.5
    normal = None
    depois = [x for x in s if x["epoch"] >= evento]
    for i in range(len(depois) - 5):
        if all(x["erros"] == 0 and x["vazao_req_s"] > 0 and x["p95_ms"] <= teto for x in depois[i:i + 5]):
            normal = round(depois[i]["epoch"] - evento, 0)
            break
    falhas = sum(x["erros"] for x in s)
    return {"nome": nome, "requisicoes": int(sum(x["respostas"] for x in s)), "falhas": int(falhas),
            "substituto_s": pronto, "patamar_s": normal, "p95_antes": round(statistics.median(anterior), 1),
            "por_erro": r["por_erro"], "evento_decorrido": r["eventos"][0]["decorrido_s"]}


def atualizacao(nome):
    r = resumo(nome)
    s = serie(nome)
    com_as_duas = [x for x in s if x["v110"] > 0 and x["v120"] > 0]
    falhas = int(sum(x["erros"] for x in s))
    return {"nome": nome, "requisicoes": int(sum(x["respostas"] for x in s)), "falhas": falhas, "por_erro": r["por_erro"],
            "rollout_s": round(r["eventos"][1]["decorrido_s"] - r["eventos"][0]["decorrido_s"], 1),
            "coexistencia_s": len(com_as_duas), "versoes": sorted(k for k in r["por_versao"] if k != "(sem)")}


def eixo(ax, xlabel, ylabel):
    ax.set_xlabel(xlabel)
    ax.set_ylabel(ylabel)
    ax.grid(alpha=0.3)


def grafico_escala(post, get):
    fig, (a, b) = plt.subplots(1, 2, figsize=(11, 4.6))
    xs = [l["replicas"] for l in post]
    a.plot(xs, xs, "--", color=CINZA, label="Ideal")
    a.plot(xs, [l["ganho"] for l in post], "o-", color=AZUL, label="POST (ingestão)")
    a.plot(xs, [l["ganho"] for l in get], "o-", color=LARANJA, label="GET (consulta agregada)")
    for l in post:
        a.annotate(f"{l['ganho']:.2f}×", (l["replicas"], l["ganho"]), textcoords="offset points", xytext=(0, 8), ha="center", color=AZUL)
    a.set_xticks(xs)
    eixo(a, "Réplicas", "Ganho em relação a 1 réplica")
    a.legend()
    a.set_title("Ganho de vazão com 64 trabalhadores")
    b.plot(xs, [l["cpu_banco"] for l in post], "o-", color=VERMELHO, label="CPU do banco (POST)")
    b.plot(xs, [l["cpu_banco"] for l in get], "o-", color=LARANJA, label="CPU do banco (GET)")
    b.axhline(1000, ls="--", color=CINZA, label="Limite do banco (1000m)")
    b.set_xticks(xs)
    eixo(b, "Réplicas", "CPU (milicores)")
    b.set_ylim(0, 1150)
    b.legend(loc="lower right")
    b.set_title("CPU do banco por número de réplicas")
    fig.tight_layout()
    fig.savefig(f"{PASTA}/grafico-51-escala.png", dpi=150)
    plt.close(fig)


def grafico_hpa(nome, eventos):
    s = serie(nome)
    pods = json.load(open(f"{PASTA}/{nome}-pods.json", encoding="utf-8"))
    r = resumo(nome)
    t0 = r["inicio_epoch"]
    fig, (a, b) = plt.subplots(2, 1, figsize=(10, 6.4), sharex=True)
    a.plot([x["decorrido_s"] for x in s], [x["p95_ms"] for x in s], color=CINZA, lw=1, label="p95 (ms)")
    eixo(a, "", "p95 (ms)")
    p95 = sorted(x["p95_ms"] for x in s if x["p95_ms"] != "")
    a.set_ylim(0, p95[int(len(p95) * 0.98)] * 1.2)  # corta só os picos isolados
    a2 = a.twinx()
    a2.plot([x["decorrido_s"] for x in s], [x["vazao_req_s"] for x in s], color=AZUL, lw=1.2, label="Vazão (req/s)")
    a2.set_ylabel("Vazão (req/s)")
    a2.set_ylim(bottom=0)
    a.set_title("HPA sob carga em rampa")
    a.legend(loc="upper left")
    a2.legend(loc="upper right")
    b.step([p["epoch"] - t0 for p in pods], [len(p["pods"]) for p in pods], where="post", color=CINZA, label="Réplicas pedidas")
    b.step([p["epoch"] - t0 for p in pods], [sum(x["pronto"] for x in p["pods"]) for p in pods], where="post", color=AZUL, label="Réplicas prontas")
    for e in eventos:
        if 0 <= e["t"] <= 310:
            b.axvline(e["t"], color=LARANJA, ls=":", lw=1)
    eixo(b, "Segundos desde o início da carga (linhas pontilhadas: decisões do HPA)", "Réplicas")
    b.legend(loc="lower right")
    fig.tight_layout()
    fig.savefig(f"{PASTA}/grafico-52-hpa.png", dpi=150)
    plt.close(fig)


def grafico_resiliencia():
    casos = [("53-pod-exec2", "Pod apagado"), ("53-no-sem-banco", "Nó drenado sem banco"), ("53-no-com-banco", "Nó drenado com banco")]
    fig, eixos = plt.subplots(3, 1, figsize=(10, 7.5))
    for a, (nome, titulo) in zip(eixos, casos):
        s, r = serie(nome), resumo(nome)
        a.plot([x["decorrido_s"] for x in s], [x["vazao_req_s"] for x in s], color=AZUL, lw=1.2, label="Sucessos/s")
        a.fill_between([x["decorrido_s"] for x in s], [min(x["erros"], 800) for x in s], color=VERMELHO, alpha=0.3, label="Falhas/s (corte em 800)")
        for e in r["eventos"]:
            a.axvline(e["decorrido_s"], color=LARANJA, ls="--", lw=1)
        a.set_title(titulo, fontsize=10)
        eixo(a, "", "Respostas/s")
        a.legend(loc="upper right", fontsize=8)
    eixos[-1].set_xlabel("Segundos desde o início (linha tracejada: drain, delete ou uncordon)")
    fig.tight_layout()
    fig.savefig(f"{PASTA}/grafico-53-resiliencia.png", dpi=150)
    plt.close(fig)


def grafico_rolling():
    fig, (a, b) = plt.subplots(1, 2, figsize=(11, 4.2))
    s = serie("54-com-prestop-update-exec2")
    a.stackplot([x["decorrido_s"] for x in s], [x["v110"] for x in s], [x["v120"] for x in s],
               labels=["Versão 1.1.0", "Versão 1.2.0"], colors=[CINZA, AZUL])
    eixo(a, "Segundos desde o início", "Respostas/s")
    a.legend(loc="lower left")
    a.set_title("As duas versões coexistem durante a troca")
    grupos = ["update", "undo"]
    maior = 0
    for i, (rotulo, cor, nome) in enumerate((("Sem preStop", VERMELHO, "sem-prestop"), ("Com preStop", AZUL, "com-prestop"))):
        valores = [media([atualizacao(f"54-{nome}-{g}-exec{k}")["falhas"] for k in (1, 2, 3)]) for g in grupos]
        maior = max(maior, *valores)
        barras = b.bar([j + i * 0.38 for j in range(2)], valores, 0.36, color=cor, label=rotulo)
        b.bar_label(barras, fmt="%.1f")
    b.set_xticks([0.19, 1.19], ["Rolling update", "Rollout undo"])
    eixo(b, "", "Falhas por execução (média de 3)")
    b.set_ylim(0, max(5, maior * 1.3))
    b.legend(loc="upper center", ncol=2)
    b.set_title("Falhas com e sem preStop")
    fig.tight_layout()
    fig.savefig(f"{PASTA}/grafico-54-rolling.png", dpi=150)
    plt.close(fig)


def distribuicao(nome):
    """Quantas réplicas da API havia em cada nó no início da execução."""
    pods = json.load(open(f"{PASTA}/{nome}-pods.json", encoding="utf-8"))
    primeiros = pods[0]["pods"] if pods else []
    contagem = {}
    for p in primeiros:
        contagem[p["no"]] = contagem.get(p["no"], 0) + 1
    return dict(sorted(contagem.items()))


def main():
    saida = {"escala_post": tabela_escala("51"), "escala_get": tabela_escala("51g")}
    saida["distribuicao_escala"] = {n: distribuicao(f"51-r{n}-exec1") for n in (1, 2, 4, 8)}
    grafico_escala(saida["escala_post"], saida["escala_get"])

    t0 = resumo("52-hpa")["inicio_epoch"]
    brutos = json.load(open(f"{PASTA}/52-hpa-eventos-k8s.json", encoding="utf-8"))["items"]
    decisoes = sorted(({"t": round(epoca_iso(e["lastTimestamp"]) - t0), "hora": datetime.datetime.fromtimestamp(epoca_iso(e["lastTimestamp"])).strftime("%H:%M:%S"),
                        "mensagem": e["message"][:60]} for e in brutos if e["reason"] == "SuccessfulRescale" and e["lastTimestamp"] and epoca_iso(e["lastTimestamp"]) >= t0 - 5), key=lambda e: e["t"])
    saida["hpa"] = {"decisoes": decisoes, "resumo": {k: resumo("52-hpa")[k] for k in ("requisicoes", "falhas", "vazao_req_s", "p95_ms")}}
    grafico_hpa("52-hpa", decisoes)

    saida["resiliencia"] = [recuperacao(n) for n in ("53-pod-exec1", "53-pod-exec2", "53-pod-exec3", "53-no-sem-banco", "53-no-com-banco")]
    grafico_resiliencia()

    saida["rolling"] = [atualizacao(f"54-{p}-{g}-exec{i}") for p in ("sem-prestop", "com-prestop") for g in ("update", "undo") for i in (1, 2, 3)]
    grafico_rolling()

    json.dump(saida, open(f"{PASTA}/tabelas.json", "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print(json.dumps(saida, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
