#!/usr/bin/env python3
"""
Gerador de carga da APS (Etapas 4 e 5): simula N clientes enviando requisições ao mesmo tempo,
cronometra cada resposta e anota qual pod a atendeu.

Cada trabalhador é um cliente em LAÇO FECHADO: envia, espera a resposta inteira e só então envia a
próxima. N trabalhadores = N requisições em andamento ao mesmo tempo. Nenhuma requisição é descartada:
as que falham (HTTP >= 400, timeout, conexão recusada) entram nos arquivos e na taxa de erro.

Modos de intensidade:
  constante  N trabalhadores do início ao fim                 (-c N -d S)
  rampa      começa com 1 e chega a N em R segundos           (-c N -d S --rampa R)   -> HPA (Etapa 5)
  degraus    1, 2, 4, 8... trabalhadores, T segundos cada     (--degraus 1,2,4 --duracao-degrau T) -> linha de base

Saída (prefixo --saida):
  <prefixo>-requisicoes.csv  uma linha por requisição (a matéria-prima)
  <prefixo>-segundos.csv     uma linha por segundo, com a hora do relógio (linhas do tempo da Etapa 5)
  <prefixo>-top.csv          amostras do "kubectl top pod" durante a carga (com --top)
  <prefixo>-resumo.json      resumo geral e por degrau (tabelas do relatório)
  <prefixo>-ao-vivo.csv      uma linha por segundo gravada NA HORA (python carga/ao_vivo.py desenha ao vivo)

Só biblioteca padrão: não precisa de pip install.
Use 127.0.0.1 e não "localhost": no Windows, "localhost" tenta IPv6 primeiro e soma atraso a cada conexão.

Exemplos:
  python carga/loadgen.py http://127.0.0.1:8081/api/v1/air-quality/health/live -c 8 -d 20
  python carga/loadgen.py http://127.0.0.1:8081/api/v1/air-quality/particulate -X POST --corpo ar \\
         --degraus 1,2,4,8,16,32,64 --duracao-degrau 25 --aquecimento 5 --top --saida resultados/base/ingestao
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import http.client
import itertools
import json
import os
import platform
import random
import re
import shlex
import socket
import subprocess
import sys
import threading
import time
import urllib.parse
from collections import Counter, defaultdict
from dataclasses import dataclass, field

# ================================ Corpos das requisições ================================
# Modelos com marcadores, trocados a cada requisição para que os dados variem
# ("dados repetidos podem ser otimizados ou rejeitados", ficha da Etapa 4):
#   {{num:5:60}}        número com 1 casa decimal entre 5 e 60
#   {{int:1:10}}        inteiro entre 1 e 10
#   {{escolha:A|B|C}}   um dos valores
#   {{seq}}             contador global (1, 2, 3...)
#   {{agora}}           data e hora UTC em ISO 8601
# Os marcadores também funcionam na URL (ex.: /stations/{{escolha:EST-01|EST-02}}/latest).

ESTACOES = "|".join(f"EST-{i:02d}" for i in range(1, 11))
PONTOS = "|".join(f"PT-{i:02d}" for i in range(1, 11))
AREAS = "CENTRO|NORTE|SUL|LESTE|OESTE"

CORPOS_PRONTOS = {
    "ar": '{"stationId":"{{escolha:%s}}","sensorId":"SEN-PM-{{int:1:3}}","areaId":"{{escolha:%s}}",'
          '"pm25":{{num:5:60}},"pm10":{{num:10:90}}}' % (ESTACOES, AREAS),
    "alagamento": '{"monitoringPointId":"{{escolha:%s}}","sensorId":"SEN-N-{{int:1:3}}","waterLevelCm":{{num:100:380}}}'
                  % PONTOS,
    "termica": '{"stationId":"{{escolha:%s}}","areaId":"{{escolha:%s}}","surfaceSensorId":"S-SUP","upperSensorId":"S-ALT",'
               '"surfaceTemperatureC":{{num:8:25}},"upperTemperatureC":{{num:5:28}}}' % (ESTACOES, AREAS),
}

_MARCADOR = re.compile(r"\{\{(\w+)(?::([^}]*))?\}\}")
_sequencia = itertools.count(1)


def preencher(modelo: str, rnd: random.Random) -> str:
    def trocar(m: re.Match) -> str:
        tipo, arg = m.group(1), m.group(2) or ""
        if tipo == "num":
            a, b = (float(x) for x in arg.split(":"))
            return f"{rnd.uniform(a, b):.1f}"
        if tipo == "int":
            a, b = (int(x) for x in arg.split(":"))
            return str(rnd.randint(a, b))
        if tipo == "escolha":
            return rnd.choice(arg.split("|"))
        if tipo == "seq":
            return str(next(_sequencia))
        if tipo == "agora":
            return dt.datetime.now(dt.timezone.utc).isoformat()
        raise ValueError(f"marcador desconhecido: {{{{{tipo}}}}}")
    return _MARCADOR.sub(trocar, modelo)


# ================================ Registro de cada requisição ================================

CAMPOS = ["inicio_epoch", "hora", "segundo", "fase", "trabalhador", "ativos", "aquecimento",
          "latencia_ms", "status", "erro", "x_pod", "x_versao", "x_cache", "bytes"]


@dataclass
class Fase:
    """Um trecho com número fixo (ou crescente, na rampa) de trabalhadores."""
    indice: int
    trabalhadores: int
    duracao: float
    aquecimento: float
    rampa: float = 0.0                  # >0: os trabalhadores entram espalhados ao longo destes segundos
    inicio: float = 0.0                 # time.time() de quando a fase começou
    fim: float = 0.0


@dataclass
class Estado:
    registros: list = field(default_factory=list)
    ativos: int = 0
    trava: threading.Lock = field(default_factory=threading.Lock)
    parar: threading.Event = field(default_factory=threading.Event)
    fase_atual: Fase | None = None
    top: list = field(default_factory=list)
    ultimo_top: dict = field(default_factory=dict)   # serviço -> CPU (millicores) da amostra mais recente


def classificar_erro(ex: BaseException) -> str:
    if isinstance(ex, (socket.timeout, TimeoutError)):
        return "timeout"
    if isinstance(ex, ConnectionRefusedError):
        return "conexao_recusada"
    if isinstance(ex, (ConnectionResetError, BrokenPipeError, http.client.RemoteDisconnected)):
        return "conexao_encerrada"
    if isinstance(ex, http.client.HTTPException):
        return "http_invalido"
    return "erro_rede"


def trabalhador(wid: int, fase: Fase, alvo, args, estado: Estado, partida: float):
    rnd = random.Random((args.semente or 0) * 1_000_003 + fase.indice * 1009 + wid if args.semente is not None else None)
    conexao = None
    corpo_modelo = alvo["corpo"]
    cabecalhos = {"Content-Type": "application/json"} if corpo_modelo else {}

    # Rampa: o trabalhador "wid" só entra depois do seu atraso
    if fase.rampa > 0 and fase.trabalhadores > 1:
        espera = fase.inicio + wid * fase.rampa / (fase.trabalhadores - 1) - time.time()
        if espera > 0 and estado.parar.wait(espera):
            return

    with estado.trava:
        estado.ativos += 1
    try:
        while not estado.parar.is_set() and time.time() < fase.fim:
            if conexao is None:
                classe = http.client.HTTPSConnection if alvo["https"] else http.client.HTTPConnection
                conexao = classe(alvo["host"], alvo["porta"], timeout=args.timeout)
            caminho = preencher(alvo["caminho"], rnd) if "{{" in alvo["caminho"] else alvo["caminho"]
            corpo = preencher(corpo_modelo, rnd).encode() if corpo_modelo else None

            inicio_epoch = time.time()
            t0 = time.perf_counter()
            status, erro, pod, versao, cache, tamanho = 0, "", "", "", "", 0
            try:
                # Corpo em bytes: cabeçalho e corpo vão num pacote só (com str, o Nagle soma ~40 ms)
                conexao.request(args.metodo, caminho, body=corpo, headers=cabecalhos)
                resposta = conexao.getresponse()
                dados = resposta.read()          # latência = até o último byte
                status = resposta.status
                tamanho = len(dados)
                pod = resposta.getheader("X-Pod", "")
                versao = resposta.getheader("X-Versao", "")
                cache = resposta.getheader("X-Cache", "")
                if status >= 400:
                    erro = f"http_{status}"
                if resposta.will_close:
                    conexao.close()
                    conexao = None
            except Exception as ex:  # noqa: BLE001 - toda falha vira registro, nada é descartado
                erro = classificar_erro(ex)
                conexao.close()
                conexao = None
            latencia = (time.perf_counter() - t0) * 1000

            with estado.trava:
                ativos = estado.ativos
            estado.registros.append((
                round(inicio_epoch, 6),
                dt.datetime.fromtimestamp(inicio_epoch).strftime("%H:%M:%S.%f")[:-3],
                int(inicio_epoch - partida),
                fase.indice,
                wid,
                ativos,
                1 if inicio_epoch < fase.inicio + fase.aquecimento else 0,
                round(latencia, 3),
                status,
                erro,
                pod,
                versao,
                cache,
                tamanho,
            ))
    finally:
        with estado.trava:
            estado.ativos -= 1
        if conexao is not None:
            conexao.close()


# ================================ kubectl top em paralelo ================================

def amostrar_top(args, estado: Estado, partida: float):
    """Lê "kubectl top pod" a cada N segundos. O metrics-server atualiza a cada ~15 s."""
    comando = ["kubectl", "top", "pod", "-n", args.namespace, "--no-headers"]
    while not estado.parar.is_set():
        agora = time.time()
        try:
            saida = subprocess.run(comando, capture_output=True, text=True, timeout=15).stdout
        except (OSError, subprocess.TimeoutExpired):
            saida = ""
        fase = estado.fase_atual.indice if estado.fase_atual else -1
        por_servico = defaultdict(int)
        for linha in saida.splitlines():
            partes = linha.split()
            if len(partes) >= 3 and partes[1].endswith("m"):
                cpu = int(partes[1][:-1])
                mem = int(re.sub(r"\D", "", partes[2]) or 0)
                estado.top.append((round(agora, 3), dt.datetime.fromtimestamp(agora).strftime("%H:%M:%S"),
                                   int(agora - partida), fase, partes[0], cpu, mem))
                por_servico[nome_do_servico(partes[0])] += cpu
        if por_servico:
            estado.ultimo_top = dict(por_servico)
        estado.parar.wait(args.top_intervalo)


# ================================ Estatística ================================

def percentil(ordenados: list[float], p: float) -> float | None:
    """Método do posto mais próximo: o menor valor com pelo menos p% das amostras abaixo ou iguais."""
    if not ordenados:
        return None
    k = max(0, min(len(ordenados) - 1, int(-(-p * len(ordenados) // 100)) - 1))
    return round(ordenados[k], 2)


def resumir(registros: list, janela_s: float, trabalhadores: int | None, top: list) -> dict:
    lat = sorted(r[7] for r in registros)
    ok = [r for r in registros if not r[9]]
    lat_ok = sorted(r[7] for r in ok)
    total = len(registros)
    vazao_ok = len(ok) / janela_s if janela_s > 0 else 0
    vazao_total = total / janela_s if janela_s > 0 else 0
    media = sum(lat) / total if total else None
    resumo = {
        "trabalhadores": trabalhadores,
        "janela_medida_s": round(janela_s, 2),
        "requisicoes": total,
        "ok": len(ok),
        "erros": total - len(ok),
        "taxa_erro_pct": round(100 * (total - len(ok)) / total, 3) if total else None,
        "vazao_req_s": round(vazao_ok, 2),
        "latencia_ms": {
            "p50": percentil(lat, 50), "p95": percentil(lat, 95), "p99": percentil(lat, 99),
            "media": round(media, 2) if media is not None else None,
            "max": round(lat[-1], 2) if lat else None,
        },
        "latencia_ok_ms": {"p50": percentil(lat_ok, 50), "p95": percentil(lat_ok, 95), "p99": percentil(lat_ok, 99)},
        "por_pod": dict(Counter(r[10] or "(sem X-Pod)" for r in registros).most_common()),
        "por_status": {str(k): v for k, v in sorted(Counter(r[8] for r in registros).items())},
        "por_erro": dict(Counter(r[9] for r in registros if r[9]).most_common()),
        "por_versao": dict(Counter(r[11] for r in registros if r[11]).most_common()),
        "por_cache": dict(Counter(r[12] for r in registros if r[12]).most_common()),
    }
    # Lei de Little (laço fechado): trabalhadores = vazão x latência média. Se a conta não fecha, a medição tem erro.
    if trabalhadores and vazao_total > 0:
        resumo["lei_de_little"] = {
            "latencia_media_medida_ms": resumo["latencia_ms"]["media"],
            "latencia_media_prevista_ms": round(1000 * trabalhadores / vazao_total, 2),
        }
    if top:
        cpu = defaultdict(list)
        for amostra in top:
            cpu[amostra[4]].append(amostra[5])
        resumo["cpu_top_m"] = {pod: {"media": round(sum(v) / len(v)), "max": max(v)} for pod, v in sorted(cpu.items())}
    return resumo


def serie_por_segundo(registros: list, ativos_por_segundo: dict, partida: float) -> list[dict]:
    """Uma linha por segundo de relógio, agrupando pela hora de INÍCIO de cada requisição."""
    grupos = defaultdict(list)
    for r in registros:
        grupos[r[2]].append(r)
    linhas = []
    for s in range(0, max(grupos, default=-1) + 1):
        rs = grupos.get(s, [])
        lat = sorted(r[7] for r in rs)
        oks = sum(1 for r in rs if not r[9])
        epoch = partida + s
        linhas.append({
            "segundo": s,
            "epoch": int(epoch),
            "hora": dt.datetime.fromtimestamp(epoch).strftime("%H:%M:%S"),
            "ativos": ativos_por_segundo.get(s, ""),
            "requisicoes": len(rs),
            "ok": oks,
            "erros": len(rs) - oks,
            "p50_ms": percentil(lat, 50) if lat else "",
            "p95_ms": percentil(lat, 95) if lat else "",
            "p99_ms": percentil(lat, 99) if lat else "",
            "pods_distintos": len({r[10] for r in rs if r[10]}),
            "por_pod": ";".join(f"{p}:{n}" for p, n in sorted(Counter(r[10] for r in rs if r[10]).items())),
            "por_versao": ";".join(f"{v}:{n}" for v, n in sorted(Counter(r[11] for r in rs if r[11]).items())),
            "erros_tipos": ";".join(f"{e}:{n}" for e, n in sorted(Counter(r[9] for r in rs if r[9]).items())),
        })
    return linhas


# ================================ Ambiente (para a ficha) ================================

def descrever_ambiente() -> dict:
    cpu, ram_gb = platform.processor(), None
    try:
        if sys.platform == "win32":
            import ctypes
            import winreg
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"HARDWARE\DESCRIPTION\System\CentralProcessor\0") as k:
                cpu = winreg.QueryValueEx(k, "ProcessorNameString")[0].strip()

            class MemoryStatus(ctypes.Structure):
                _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                            ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                            ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                            ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                            ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]
            m = MemoryStatus()
            m.dwLength = ctypes.sizeof(MemoryStatus)
            ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m))
            ram_gb = round(m.ullTotalPhys / 2**30, 1)
        else:
            with open("/proc/cpuinfo") as f:
                cpu = next((l.split(":", 1)[1].strip() for l in f if l.startswith("model name")), cpu)
            with open("/proc/meminfo") as f:
                ram_gb = round(int(f.readline().split()[1]) / 2**20, 1)
    except Exception:  # noqa: BLE001 - descrição do ambiente é informativa, não pode derrubar o teste
        pass
    return {"sistema": f"{platform.system()} {platform.release()}", "cpu": cpu, "nucleos_logicos": os.cpu_count(),
            "ram_gb": ram_gb, "python": platform.python_version(), "maquina": platform.node()}


# ================================ Execução ================================

def montar_fases(args) -> list[Fase]:
    if args.degraus:
        lista = [int(x) for x in args.degraus.split(",") if x.strip()]
        return [Fase(i, n, args.duracao_degrau, args.aquecimento) for i, n in enumerate(lista)]
    if args.rampa:
        return [Fase(0, args.trabalhadores, args.duracao, args.aquecimento, rampa=args.rampa)]
    return [Fase(0, args.trabalhadores, args.duracao, args.aquecimento)]


def executar(args, alvo) -> None:
    fases = montar_fases(args)
    estado = Estado()
    partida = time.time()
    ativos_por_segundo: dict[int, int] = {}
    cpu_inicio = time.process_time()
    args.saida = args.saida or os.path.join("resultados", time.strftime("%Y%m%d-%H%M%S"))
    os.makedirs(os.path.dirname(args.saida) or ".", exist_ok=True)
    servico = servico_alvo(args.url)

    # Arquivo AO VIVO: uma linha por segundo, gravada na hora, para o carga/ao_vivo.py desenhar durante o teste
    ao_vivo = open(f"{args.saida}-ao-vivo.csv", "w", newline="", encoding="utf-8")
    escritor = csv.writer(ao_vivo)
    escritor.writerow(["hora", "segundo", "fase", "fases", "trabalhadores", "ok_s", "erros_s",
                       "p50_ms", "p95_ms", "p99_ms", "pods", "cpu_api_m", "cpu_banco_m", "servico", "rota"])
    ao_vivo.flush()
    rota = f"{args.metodo} {re.sub(r'^https?://[^/]+', '', args.url)}"

    if args.top:
        threading.Thread(target=amostrar_top, args=(args, estado, partida), daemon=True).start()

    total_s = sum(f.duracao for f in fases)
    print(f"Alvo: {args.metodo} {args.url}")
    print(f"Modo: {modo_texto(args)} | duração total ~{total_s:.0f} s | timeout {args.timeout:g} s | aquecimento {args.aquecimento:g} s")
    print(f"{'hora':8}  {'fase':>5}  {'trab':>4}  {'req/s':>6}  {'erros':>5}  {'p50 ms':>7}  {'p95 ms':>7}  pods")

    def monitor():
        visto = 0
        while not estado.parar.is_set():
            if estado.parar.wait(1):
                break
            s = int(time.time() - partida)
            with estado.trava:
                ativos = estado.ativos
            ativos_por_segundo[s] = ativos
            novos = estado.registros[visto:]
            visto += len(novos)
            lat = sorted(r[7] for r in novos)
            erros = sum(1 for r in novos if r[9])
            pods = len({r[10] for r in novos if r[10]})
            fase = estado.fase_atual
            print(f"{time.strftime('%H:%M:%S')}  {fase.indice + 1 if fase else '-':>2}/{len(fases):<2}  {ativos:>4}  "
                  f"{len(novos) - erros:>6}  {erros:>5}  {percentil(lat, 50) or 0:>7.1f}  {percentil(lat, 95) or 0:>7.1f}  {pods}",
                  flush=True)
            escritor.writerow([time.strftime("%H:%M:%S"), s, fase.indice + 1 if fase else 0, len(fases), ativos,
                               len(novos) - erros, erros, percentil(lat, 50) or "", percentil(lat, 95) or "",
                               percentil(lat, 99) or "", pods, estado.ultimo_top.get(servico, ""),
                               estado.ultimo_top.get("postgres", ""), servico or "", rota])
            ao_vivo.flush()

    threading.Thread(target=monitor, daemon=True).start()

    try:
        for fase in fases:
            fase.inicio = time.time()
            fase.fim = fase.inicio + fase.duracao
            estado.fase_atual = fase
            threads = [threading.Thread(target=trabalhador, args=(w, fase, alvo, args, estado, partida), daemon=True)
                       for w in range(fase.trabalhadores)]
            for t in threads:
                t.start()
            for t in threads:
                while t.is_alive():
                    t.join(0.2)
            if estado.parar.is_set():
                break
    except KeyboardInterrupt:
        print("\nInterrompido (Ctrl+C): gravando o que foi medido.")
        estado.parar.set()
        for fase in fases:
            if fase.inicio and not fase.fim:
                fase.fim = time.time()
    estado.parar.set()
    fim = time.time()
    cpu_gerador_pct = 100 * (time.process_time() - cpu_inicio) / max(0.001, fim - partida)
    time.sleep(1.1)   # deixa o monitor gravar o último segundo
    ao_vivo.close()

    gravar(args, alvo, fases, estado, partida, fim, ativos_por_segundo, cpu_gerador_pct)


def modo_texto(args) -> str:
    if args.degraus:
        return f"degraus {args.degraus} trabalhadores, {args.duracao_degrau:g} s cada"
    if args.rampa:
        return f"rampa de 1 a {args.trabalhadores} trabalhadores em {args.rampa:g} s"
    return f"constante, {args.trabalhadores} trabalhadores"


def gravar(args, alvo, fases, estado, partida, fim, ativos_por_segundo, cpu_gerador_pct):
    prefixo = args.saida
    registros = estado.registros

    with open(f"{prefixo}-requisicoes.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(CAMPOS)
        w.writerows(registros)

    serie = serie_por_segundo(registros, ativos_por_segundo, partida)
    with open(f"{prefixo}-segundos.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(serie[0].keys()) if serie else ["segundo"])
        w.writeheader()
        w.writerows(serie)

    if estado.top:
        with open(f"{prefixo}-top.csv", "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["epoch", "hora", "segundo", "fase", "pod", "cpu_m", "memoria_mi"])
            w.writerows(estado.top)

    # Resumo por fase (degrau), sem o aquecimento. Janela = do fim do aquecimento ao fim da fase.
    por_fase = []
    for fase in fases:
        if not fase.inicio:
            continue
        rs = [r for r in registros if r[3] == fase.indice and not r[6]]
        janela = max(0.0, (fase.fim or fim) - (fase.inicio + fase.aquecimento))
        # O metrics-server mede a cada 15 s: uma amostra pode refletir até ~30 s atrás. Só valem as amostras
        # tiradas --top-atraso segundos depois do início do degrau, para não herdar a CPU do degrau anterior.
        corte = fase.inicio + max(fase.aquecimento, args.top_atraso)
        top = [a for a in estado.top if a[3] == fase.indice and a[0] >= corte]
        r = resumir(rs, janela, fase.trabalhadores, top)
        r["fase"] = fase.indice
        r["inicio"] = dt.datetime.fromtimestamp(fase.inicio).isoformat(timespec="seconds")
        por_fase.append(r)

    medidos = [r for r in registros if not r[6]]
    janela_total = sum(f["janela_medida_s"] for f in por_fase)
    geral = resumir(medidos, janela_total, fases[0].trabalhadores if len(fases) == 1 else None,
                    [a for a in estado.top if not args.degraus])

    resumo = {
        "comando": " ".join(shlex.quote(a) for a in sys.argv),
        "alvo": {"metodo": args.metodo, "url": args.url, "corpo": args.corpo},
        "modo": "degraus" if args.degraus else ("rampa" if args.rampa else "constante"),
        "parametros": {"trabalhadores": args.trabalhadores, "duracao_s": args.duracao, "degraus": args.degraus,
                       "duracao_degrau_s": args.duracao_degrau, "rampa_s": args.rampa, "aquecimento_s": args.aquecimento,
                       "timeout_s": args.timeout, "semente": args.semente},
        "inicio": dt.datetime.fromtimestamp(partida).isoformat(timespec="seconds"),
        "fim": dt.datetime.fromtimestamp(fim).isoformat(timespec="seconds"),
        "ambiente": descrever_ambiente(),
        "cpu_gerador_pct_de_um_nucleo": round(cpu_gerador_pct, 1),
        "geral": geral,
        "por_fase": por_fase,
        "arquivos": {"requisicoes": f"{prefixo}-requisicoes.csv", "segundos": f"{prefixo}-segundos.csv",
                     "top": f"{prefixo}-top.csv" if estado.top else None, "resumo": f"{prefixo}-resumo.json"},
    }
    with open(f"{prefixo}-resumo.json", "w", encoding="utf-8") as f:
        json.dump(resumo, f, ensure_ascii=False, indent=2)

    imprimir_resumo(resumo)


def servico_alvo(url: str) -> str | None:
    """http://.../api/v1/air-quality/particulate -> air-quality-api (o nome do Deployment)"""
    m = re.search(r"/api/v1/([a-z-]+)", url)
    return f"{m.group(1)}-api" if m else None


def nome_do_servico(pod: str) -> str:
    """air-quality-api-85ffb8cb47-zrg8n -> air-quality-api ; postgres-0 -> postgres"""
    partes = pod.split("-")
    if len(partes) >= 3 and re.fullmatch(r"[a-z0-9]{5}", partes[-1]) and re.fullmatch(r"[a-z0-9]{8,10}", partes[-2]):
        return "-".join(partes[:-2])
    if re.fullmatch(r"\d+", partes[-1]):
        return "-".join(partes[:-1])
    return pod


def cpu_por_servico(cpu_top: dict) -> dict:
    """Soma a CPU média (millicores) das réplicas de cada serviço."""
    soma = defaultdict(int)
    for pod, v in cpu_top.items():
        soma[nome_do_servico(pod)] += v["media"]
    return dict(sorted(soma.items(), key=lambda kv: -kv[1]))


def imprimir_resumo(resumo: dict):
    print()
    print(f"{'trab':>4}  {'req':>7}  {'req/s':>8}  {'p50':>7}  {'p95':>7}  {'p99':>7}  {'erros %':>7}  CPU média por serviço (kubectl top)")
    for f in resumo["por_fase"]:
        lat = f["latencia_ms"]
        cpu = ", ".join(f"{nome} {m}m" for nome, m in cpu_por_servico(f.get("cpu_top_m", {})).items() if m >= 10) or "-"
        print(f"{f['trabalhadores']:>4}  {f['requisicoes']:>7}  {f['vazao_req_s']:>8.1f}  {lat['p50'] or 0:>7.1f}  "
              f"{lat['p95'] or 0:>7.1f}  {lat['p99'] or 0:>7.1f}  {f['taxa_erro_pct'] or 0:>7.2f}  {cpu}")
    g = resumo["geral"]
    print(f"\nPor pod: {g['por_pod']}")
    if g["por_erro"]:
        print(f"Erros: {g['por_erro']}")
    print(f"CPU do próprio gerador: {resumo['cpu_gerador_pct_de_um_nucleo']}% de um núcleo "
          f"(perto de 100%, o gargalo pode ser o gerador)")
    print(f"Arquivos: {resumo['arquivos']['resumo']} (+ -requisicoes.csv, -segundos.csv"
          f"{', -top.csv' if resumo['arquivos']['top'] else ''})")


def ler_argumentos():
    p = argparse.ArgumentParser(
        description="Gerador de carga da APS: laço fechado, latência p50/p95/p99, vazão, erros e X-Pod por requisição.",
        formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__.split("Exemplos:")[1] and
        "Exemplos:" + __doc__.split("Exemplos:")[1])
    p.add_argument("url", help="URL alvo, sempre pelo gateway (ex.: http://127.0.0.1:8081/api/v1/air-quality/particulate)")
    p.add_argument("-X", "--metodo", default="GET", help="verbo HTTP (padrão: GET)")
    p.add_argument("--corpo", help=f"corpo JSON: um modelo pronto ({', '.join(CORPOS_PRONTOS)}), JSON literal ou @arquivo")
    p.add_argument("-c", "--trabalhadores", type=int, default=8, help="trabalhadores simultâneos (padrão: 8)")
    p.add_argument("-d", "--duracao", type=float, default=20, help="duração em segundos nos modos constante e rampa (padrão: 20)")
    p.add_argument("--rampa", type=float, default=0, metavar="S", help="modo rampa: de 1 a -c trabalhadores em S segundos")
    p.add_argument("--degraus", metavar="LISTA", help="modo degraus: ex. 1,2,4,8,16,32,64")
    p.add_argument("--duracao-degrau", type=float, default=25, metavar="S", help="segundos por degrau (padrão: 25)")
    p.add_argument("--aquecimento", type=float, default=5, metavar="S",
                   help="segundos iniciais de cada fase fora do resumo (padrão: 5)")
    p.add_argument("--timeout", type=float, default=5, help="tempo limite por requisição em segundos (padrão: 5)")
    p.add_argument("--saida", metavar="PREFIXO", help="prefixo dos arquivos (padrão: resultados/<data-hora>)")
    p.add_argument("--top", action="store_true", help="amostra o kubectl top pod durante a carga")
    p.add_argument("--top-intervalo", type=float, default=5, metavar="S", help="intervalo do kubectl top (padrão: 5)")
    p.add_argument("--top-atraso", type=float, default=20, metavar="S",
                   help="no resumo, só usa amostras do top tiradas S segundos após o início do degrau (padrão: 20)")
    p.add_argument("--namespace", default="aps", help="namespace do kubectl top (padrão: aps)")
    p.add_argument("--semente", type=int, help="semente do random: repete a mesma sequência de dados")
    args = p.parse_args()

    args.metodo = args.metodo.upper()
    if args.corpo:
        if args.corpo in CORPOS_PRONTOS:
            args.corpo_modelo = CORPOS_PRONTOS[args.corpo]
        elif args.corpo.startswith("@"):
            with open(args.corpo[1:], encoding="utf-8") as f:
                args.corpo_modelo = f.read()
        else:
            args.corpo_modelo = args.corpo
    else:
        args.corpo_modelo = None
    if args.trabalhadores < 1:
        p.error("-c precisa ser pelo menos 1")
    if args.rampa and args.rampa > args.duracao:
        p.error("--rampa não pode ser maior que -d")

    partes = urllib.parse.urlsplit(args.url)
    if partes.scheme not in ("http", "https") or not partes.hostname:
        p.error("URL inválida: use http://host:porta/caminho")
    caminho = partes.path or "/"
    if partes.query:
        caminho += "?" + partes.query
    alvo = {"https": partes.scheme == "https", "host": partes.hostname,
            "porta": partes.port or (443 if partes.scheme == "https" else 80),
            "caminho": urllib.parse.unquote(caminho) if "%7B%7B" in caminho else caminho,
            "corpo": args.corpo_modelo}
    return args, alvo


if __name__ == "__main__":
    argumentos, destino = ler_argumentos()
    executar(argumentos, destino)
