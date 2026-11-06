#!/usr/bin/env python3
"""
Experimentos da Etapa 5: escalabilidade e resiliência, com o gerador de carga rodando.

Cada experimento prepara o cluster, liga os geradores (carga/loadgen.py), executa a ação no segundo
certo e registra, com horário, tudo o que o Kubernetes fez: pods criados, prontos, removidos, decisões
do HPA. No fim devolve o cluster ao normal (manifestos de k8s/) e gera tabelas e gráficos
(carga/analise_etapa5.py). Uma janela com os gráficos ao vivo abre sozinha.

Uso (PowerShell, Git Bash ou terminal):
  python carga/experimento.py escala               1, 2, 4 e 8 réplicas com a mesma carga (HPA removido)
  python carga/experimento.py hpa                  HPA por CPU (mín. 2, máx. 10) com carga em rampa
  python carga/experimento.py pod-apagado          kubectl delete pod com carga constante
  python carga/experimento.py no-drenado           kubectl drain / uncordon com carga constante
  python carga/experimento.py rolling              rolling update 1.1.0 -> 1.2.0 e rollout undo (com preStop)
  python carga/experimento.py rolling-sem-prestop  o mesmo, sem o preStop (para comparar)
  python carga/experimento.py cache                consulta agregada com cache x sem cache
  python carga/experimento.py fila                 ingestão com fila (assíncrono) x sem fila (síncrono)
  python carga/experimento.py todos                todos acima, em sequência (~50 min)

Opções: --rapido (versão curta, para conferir o fluxo), --sem-janela, --gateway URL.
Resultados em resultados/etapa5/<data-hora>-<experimento>/.
O serviço medido é a air-quality-api (o de ingestão, o mais exigido na linha de base).
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import glob
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
from collections import Counter, defaultdict

AQUI = os.path.dirname(os.path.abspath(__file__))
RAIZ = os.path.dirname(AQUI)
NS = "aps"
APP = "air-quality-api"
APIS = ["air-quality-api", "flooding-api", "thermal-inversion-api"]
ROTA_POST = "/api/v1/air-quality/particulate"
ROTA_AGREGADA = "/api/v1/air-quality/areas/CENTRO/average?hours=24"
ROTA_LIVE = "/api/v1/air-quality/health/live"
EXPERIMENTOS = ["escala", "hpa", "pod-apagado", "no-drenado", "rolling", "rolling-sem-prestop", "cache", "fila"]


# ================================ kubectl ================================

def kubectl(*args: str, check: bool = True, timeout: float = 420) -> str:
    try:
        r = subprocess.run(["kubectl", *args], capture_output=True, text=True, timeout=timeout,
                           encoding="utf-8", errors="replace")
    except subprocess.TimeoutExpired:
        if check:
            raise RuntimeError(f"kubectl {' '.join(args)}: sem resposta em {timeout:.0f} s")
        return ""
    if check and r.returncode != 0:
        raise RuntimeError(f"kubectl {' '.join(args)}: {r.stderr.strip() or r.stdout.strip()}")
    return r.stdout


def kjson(*args: str):
    return json.loads(kubectl(*args, "-o", "json"))


def achar_k3d() -> str:
    """O k3d instalado pelo winget nem sempre está no PATH de um terminal aberto antes da instalação."""
    caminho = shutil.which("k3d")
    if caminho:
        return caminho
    base = os.environ.get("LOCALAPPDATA", "")
    for padrao in (r"Microsoft\WinGet\Links\k3d.exe", r"Microsoft\WinGet\Packages\k3d.k3d*\k3d.exe"):
        achados = glob.glob(os.path.join(base, padrao))
        if achados:
            return achados[0]
    raise RuntimeError("k3d não encontrado. Instale com: winget install k3d.k3d")


# ================================ Registro do experimento ================================

class Registro:
    """A pasta do experimento e o diário de eventos (eventos.csv), com horário de cada coisa que aconteceu."""

    def __init__(self, nome: str, base: str):
        self.nome = nome
        self.t0 = time.time()
        self.pasta = os.path.join(base, time.strftime("%Y%m%d-%H%M%S") + "-" + nome)
        os.makedirs(self.pasta, exist_ok=True)
        self._trava = threading.Lock()
        self._eventos = open(os.path.join(self.pasta, "eventos.csv"), "w", newline="", encoding="utf-8")
        self._w = csv.writer(self._eventos)
        self._w.writerow(["epoch", "hora", "segundo", "tipo", "objeto", "no", "versao", "detalhe"])
        self.execucoes: list[dict] = []
        self.meta: dict = {"experimento": nome, "inicio": dt.datetime.now().isoformat(timespec="seconds"),
                           "t0": self.t0, "comando": " ".join(sys.argv)}

    def evento(self, tipo: str, objeto: str = "", no: str = "", versao: str = "", detalhe: str = "", quieto=False):
        agora = time.time()
        with self._trava:
            self._w.writerow([round(agora, 3), time.strftime("%H:%M:%S"), round(agora - self.t0, 1),
                              tipo, objeto, no, versao, detalhe])
            self._eventos.flush()
        if not quieto:
            print(f"   [{time.strftime('%H:%M:%S')}] {tipo} {objeto} {detalhe}".rstrip(), flush=True)

    def salvar(self):
        self.meta["execucoes"] = self.execucoes
        self.meta["fim"] = dt.datetime.now().isoformat(timespec="seconds")
        with open(os.path.join(self.pasta, "experimento.json"), "w", encoding="utf-8") as f:
            json.dump(self.meta, f, ensure_ascii=False, indent=2)

    def fechar(self):
        self._eventos.close()


# ================================ Observador do cluster ================================

class Observador(threading.Thread):
    """
    A cada segundo lê os pods do namespace (e o HPA a cada 2 s) e anota as TRANSIÇÕES no diário:
    pod_criado, pod_agendado, pod_pronto, pod_nao_pronto, pod_terminando, pod_removido, hpa_decisao.
    Também grava replicas.csv (réplicas prontas da API por segundo) e hpa.csv.
    """

    def __init__(self, reg: Registro):
        super().__init__(daemon=True)
        self.reg = reg
        self.parar = threading.Event()
        self.prontas_por_segundo: dict[int, int] = {}
        self.hpa_por_segundo: dict[int, int] = {}
        self._rep = open(os.path.join(reg.pasta, "replicas.csv"), "w", newline="", encoding="utf-8")
        self._wrep = csv.writer(self._rep)
        self._wrep.writerow(["epoch", "hora", "segundo", "prontas", "existentes", "terminando", "prontas_por_versao", "por_no"])
        self._hpa = open(os.path.join(reg.pasta, "hpa.csv"), "w", newline="", encoding="utf-8")
        self._whpa = csv.writer(self._hpa)
        self._whpa.writerow(["epoch", "hora", "segundo", "atuais", "desejadas", "cpu_pct", "minimo", "maximo"])
        self._desejadas = None

    def run(self):
        anteriores: dict[str, dict] = {}
        primeira = True
        tique = 0
        while not self.parar.is_set():
            inicio = time.time()
            try:
                itens = kjson("get", "pods", "-n", NS)["items"]
            except Exception:  # noqa: BLE001 - observador nunca derruba o experimento
                itens = None
            if itens is not None:
                atuais = {}
                for p in itens:
                    nome = p["metadata"]["name"]
                    app = p["metadata"].get("labels", {}).get("app", "")
                    terminando = p["metadata"].get("deletionTimestamp") is not None
                    estados = p.get("status", {}).get("containerStatuses") or []
                    pronto = bool(estados) and all(c.get("ready") for c in estados) and not terminando
                    versao = p["spec"]["containers"][0]["image"].rsplit(":", 1)[-1]
                    no = p["spec"].get("nodeName") or ""
                    atuais[nome] = {"app": app, "pronto": pronto, "terminando": terminando, "versao": versao, "no": no}
                    if primeira:
                        continue
                    ant = anteriores.get(nome)
                    if ant is None:
                        self.reg.evento("pod_criado", nome, no, versao, f"app={app}", quieto=app != APP)
                        ant = {"pronto": False, "terminando": False, "no": ""}
                    if no and not ant["no"]:
                        self.reg.evento("pod_agendado", nome, no, versao, f"app={app}", quieto=True)
                    if pronto and not ant["pronto"]:
                        self.reg.evento("pod_pronto", nome, no, versao, f"app={app}", quieto=app != APP)
                    if not pronto and ant["pronto"] and not terminando:
                        self.reg.evento("pod_nao_pronto", nome, no, versao, f"app={app}", quieto=app != APP)
                    if terminando and not ant["terminando"]:
                        self.reg.evento("pod_terminando", nome, no, versao, f"app={app}", quieto=app != APP)
                if not primeira:
                    for nome, ant in anteriores.items():
                        if nome not in atuais:
                            self.reg.evento("pod_removido", nome, ant["no"], ant["versao"], f"app={ant['app']}",
                                            quieto=ant["app"] != APP)
                primeira = False
                anteriores = atuais

                alvo = [v for v in atuais.values() if v["app"] == APP]
                prontas = [v for v in alvo if v["pronto"]]
                s = int(inicio - self.reg.t0)
                self.prontas_por_segundo[int(inicio)] = len(prontas)
                self._wrep.writerow([round(inicio, 3), time.strftime("%H:%M:%S"), s, len(prontas),
                                     sum(1 for v in alvo if not v["terminando"]), sum(1 for v in alvo if v["terminando"]),
                                     ";".join(f"{k}:{n}" for k, n in sorted(Counter(v["versao"] for v in prontas).items())),
                                     ";".join(f"{k}:{n}" for k, n in sorted(Counter(v["no"] for v in prontas).items()))])
                self._rep.flush()

            if tique % 2 == 0:
                self._ler_hpa(inicio)
            tique += 1
            self.parar.wait(max(0.05, 1 - (time.time() - inicio)))
        self._rep.close()
        self._hpa.close()

    def _ler_hpa(self, agora: float):
        saida = kubectl("get", "hpa", APP, "-n", NS, "-o", "json", check=False, timeout=15)
        if not saida.strip():
            return
        try:
            h = json.loads(saida)
        except json.JSONDecodeError:
            return
        st = h.get("status", {})
        atuais, desejadas = st.get("currentReplicas"), st.get("desiredReplicas")
        cpu = ""
        for m in st.get("currentMetrics") or []:
            cpu = m.get("resource", {}).get("current", {}).get("averageUtilization", cpu)
        self._whpa.writerow([round(agora, 3), time.strftime("%H:%M:%S"), int(agora - self.reg.t0), atuais, desejadas,
                             cpu, h["spec"].get("minReplicas"), h["spec"].get("maxReplicas")])
        self._hpa.flush()
        if desejadas is not None:
            self.hpa_por_segundo[int(agora)] = desejadas
            if self._desejadas is not None and desejadas != self._desejadas:
                self.reg.evento("hpa_decisao", APP, detalhe=f"{self._desejadas} -> {desejadas} réplicas (CPU {cpu}%)")
            self._desejadas = desejadas


# ================================ Janela ao vivo: junta os geradores ================================

class Mesclador(threading.Thread):
    """
    Com vários geradores em paralelo, cada um grava o próprio -ao-vivo.csv. Este junta todos, segundo a
    segundo, num <execução>-ao-vivo.csv (o que a janela do carga/ao_vivo.py desenha), já com as
    réplicas prontas, as decisões do HPA e as versões que responderam.
    """
    COLUNAS = ["hora", "segundo", "fase", "fases", "trabalhadores", "ok_s", "erros_s", "p50_ms", "p95_ms", "p99_ms",
               "pods", "cpu_api_m", "cpu_banco_m", "servico", "rota", "epoch", "versoes",
               "replicas_prontas", "hpa_desejadas", "pct_versao_nova"]

    def __init__(self, destino: str, prefixos: list[str], inicio: float, obs: Observador, com_hpa: bool):
        super().__init__(daemon=True)
        self.destino, self.prefixos, self.inicio, self.obs, self.com_hpa = destino, prefixos, inicio, obs, com_hpa
        self.parar = threading.Event()

    def run(self):
        while not self.parar.wait(1):
            self.juntar()
        self.juntar()

    def juntar(self):
        por_segundo: dict[int, list[dict]] = defaultdict(list)
        for i, prefixo in enumerate(self.prefixos):
            try:
                with open(f"{prefixo}-ao-vivo.csv", newline="", encoding="utf-8") as f:
                    for linha in csv.DictReader(f):
                        if linha.get("epoch"):
                            linha["_gerador"] = i
                            por_segundo[int(float(linha["epoch"]))].append(linha)
            except OSError:
                continue
        if not por_segundo:
            return
        versoes_vistas = set()
        linhas = []
        for epoch in sorted(por_segundo):
            ls = por_segundo[epoch]
            ok = sum(int(l["ok_s"] or 0) for l in ls)
            num = lambda col, l: float(l[col]) if l.get(col) not in ("", None) else None  # noqa: E731
            p50s = [(num("p50_ms", l), int(l["ok_s"] or 0)) for l in ls if num("p50_ms", l) is not None]
            versoes = Counter()
            for l in ls:
                for par in filter(None, (l.get("versoes") or "").split(";")):
                    v, n = par.rsplit(":", 1)
                    versoes[v] += int(n)
            versoes_vistas.update(versoes)
            nova = max(versoes_vistas, key=chave_versao) if versoes_vistas else None
            g1 = next((l for l in ls if l["_gerador"] == 0), ls[0])
            linhas.append({
                "hora": dt.datetime.fromtimestamp(epoch).strftime("%H:%M:%S"),
                "segundo": epoch - int(self.inicio),
                "fase": g1["fase"], "fases": g1["fases"],
                "trabalhadores": sum(int(l["trabalhadores"] or 0) for l in ls),
                "ok_s": ok,
                "erros_s": sum(int(l["erros_s"] or 0) for l in ls),
                "p50_ms": round(sum(v * n for v, n in p50s) / max(1, sum(n for _, n in p50s)), 2) if p50s else "",
                "p95_ms": max((num("p95_ms", l) for l in ls if num("p95_ms", l) is not None), default=""),
                "p99_ms": max((num("p99_ms", l) for l in ls if num("p99_ms", l) is not None), default=""),
                "pods": max(int(l["pods"] or 0) for l in ls),
                "cpu_api_m": g1.get("cpu_api_m", ""), "cpu_banco_m": g1.get("cpu_banco_m", ""),
                "servico": g1.get("servico", ""), "rota": g1.get("rota", ""), "epoch": epoch,
                "versoes": ";".join(f"{v}:{n}" for v, n in sorted(versoes.items())),
                "replicas_prontas": self.obs.prontas_por_segundo.get(epoch, self.obs.prontas_por_segundo.get(epoch - 1, "")),
                "hpa_desejadas": (self.obs.hpa_por_segundo.get(epoch) or self.obs.hpa_por_segundo.get(epoch - 1, ""))
                if self.com_hpa else "",
                "pct_versao_nova": round(100 * versoes[nova] / sum(versoes.values()), 1)
                if len(versoes_vistas) > 1 and sum(versoes.values()) else "",
            })
        temporario = self.destino + ".tmp"
        with open(temporario, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=self.COLUNAS)
            w.writeheader()
            w.writerows(linhas)
        os.replace(temporario, self.destino)


def chave_versao(v: str):
    return tuple(int(x) if x.isdigit() else 0 for x in re.split(r"[.\-]", v))


# ================================ Peças comuns ================================

class Experimento:
    def __init__(self, args, reg: Registro, obs: Observador):
        self.args, self.reg, self.obs = args, reg, obs
        self.gw = args.gateway.rstrip("/")
        self.mudou_configmap = False

    # ---------- duração (o modo --rapido divide tudo, para conferir o fluxo) ----------
    def d(self, segundos: float) -> float:
        return max(6, round(segundos / 3)) if self.args.rapido else segundos

    # ---------- preparação ----------
    def preparar(self, replicas: int, com_hpa: bool = False):
        print(f">> preparando: {replicas} réplica(s) da {APP}, HPA {'ligado' if com_hpa else 'removido'}")
        if com_hpa:
            kubectl("apply", "-f", os.path.join(RAIZ, "k8s", "40-hpa.yaml"))
        else:
            kubectl("delete", "hpa", "--all", "-n", NS, "--ignore-not-found")
        kubectl("scale", "deployment", APP, "-n", NS, f"--replicas={replicas}")
        kubectl("rollout", "status", "deployment", APP, "-n", NS, "--timeout=240s")
        self.esperar_sem_terminando()
        time.sleep(10)   # o gateway leva alguns segundos para atualizar a lista de destinos
        self.reg.evento("preparado", APP, detalhe=f"{replicas} réplica(s), HPA {'ligado' if com_hpa else 'removido'}")

    def esperar_sem_terminando(self, limite: float = 120):
        fim = time.time() + limite
        while time.time() < fim:
            pods = kjson("get", "pods", "-n", NS, "-l", f"app={APP}")["items"]
            if not any(p["metadata"].get("deletionTimestamp") for p in pods):
                return
            time.sleep(2)

    def mudar_configmap(self, chave: str, valor: str):
        kubectl("patch", "configmap", "aps-config", "-n", NS, "--type", "merge", "-p", json.dumps({"data": {chave: valor}}))
        kubectl("rollout", "restart", "deployment", APP, "-n", NS)
        kubectl("rollout", "status", "deployment", APP, "-n", NS, "--timeout=240s")
        self.esperar_sem_terminando()
        time.sleep(10)
        self.mudou_configmap = True
        self.reg.evento("configmap", "aps-config", detalhe=f"{chave}={valor} (pods reiniciados)")

    def pods_prontos(self) -> list[dict]:
        pods = kjson("get", "pods", "-n", NS, "-l", f"app={APP}")["items"]
        return [{"nome": p["metadata"]["name"], "no": p["spec"].get("nodeName", "")} for p in pods
                if not p["metadata"].get("deletionTimestamp")
                and all(c.get("ready") for c in p.get("status", {}).get("containerStatuses") or [{}])]

    # ---------- carga ----------
    def gerar(self, rotulo: str, url_rota: str, trabalhadores: int, geradores: int, duracao: float,
              aquecimento: float, metodo: str = "GET", corpo: str | None = None, rampa: float = 0,
              acoes: list | None = None, com_hpa: bool = False) -> dict:
        slug = f"r{len(self.reg.execucoes) + 1}-" + re.sub(r"[^a-z0-9]+", "-", rotulo.lower()).strip("-")
        prefixos = [os.path.join(self.reg.pasta, f"{slug}-g{k + 1}") for k in range(geradores)]
        divisao = [trabalhadores // geradores + (1 if k < trabalhadores % geradores else 0) for k in range(geradores)]
        print(f">> carga '{rotulo}': {metodo} {url_rota} | {trabalhadores} trabalhadores em {geradores} gerador(es) "
              f"| {duracao:g} s{f' (rampa {rampa:g} s)' if rampa else ''}")
        ambiente = dict(os.environ, PYTHONIOENCODING="utf-8")
        processos, logs = [], []
        inicio = time.time()
        for k, (prefixo, n) in enumerate(zip(prefixos, divisao)):
            cmd = [sys.executable, os.path.join(AQUI, "loadgen.py"), self.gw + url_rota, "-X", metodo,
                   "-c", str(n), "-d", str(duracao), "--aquecimento", str(aquecimento), "--timeout", "5",
                   "--saida", prefixo]
            if corpo:
                cmd += ["--corpo", corpo]
            if rampa:
                cmd += ["--rampa", str(rampa)]
            if k == 0:
                cmd += ["--top", "--top-intervalo", "3", "--top-atraso", "0"]
            log = open(prefixo + ".log", "w", encoding="utf-8")
            logs.append(log)
            processos.append(subprocess.Popen(cmd, stdout=log, stderr=subprocess.STDOUT, env=ambiente, cwd=RAIZ))
        self.reg.evento("carga_inicio", detalhe=f"{rotulo}: {trabalhadores} trabalhadores")
        mesclador = Mesclador(os.path.join(self.reg.pasta, f"{slug}-ao-vivo.csv"), prefixos, inicio, self.obs, com_hpa)
        mesclador.start()

        # Ações no segundo combinado (cada uma pode bloquear: ex.: esperar o rollout terminar)
        for segundo, acao in sorted(acoes or [], key=lambda a: a[0]):
            espera = inicio + segundo - time.time()
            if espera > 0:
                time.sleep(espera)
            if all(p.poll() is not None for p in processos):
                break
            acao()

        for p in processos:
            p.wait()
        for log in logs:
            log.close()
        self.reg.evento("carga_fim", detalhe=rotulo)
        mesclador.parar.set()
        mesclador.join()
        execucao = {"rotulo": rotulo, "slug": slug, "inicio": inicio, "fim": time.time(), "prefixos": prefixos,
                    "rota": f"{metodo} {url_rota}", "trabalhadores": trabalhadores, "geradores": geradores,
                    "duracao_s": duracao, "aquecimento_s": aquecimento, "rampa_s": rampa,
                    "codigos_saida": [p.returncode for p in processos]}
        self.reg.execucoes.append(execucao)
        self.reg.salvar()
        if any(execucao["codigos_saida"]):
            print(f"   ATENÇÃO: gerador terminou com erro, veja {prefixos[0]}.log")
        return execucao

    def aquecer(self, url_rota: str, metodo: str = "GET", corpo: str | None = None, segundos: float = 15):
        """Carga curta DESCARTADA: o .NET compila os caminhos quentes e os pools de conexão abrem."""
        pasta = os.path.join(self.reg.pasta, "descartado")
        os.makedirs(pasta, exist_ok=True)
        cmd = [sys.executable, os.path.join(AQUI, "loadgen.py"), self.gw + url_rota, "-X", metodo, "-c", "8",
               "-d", str(self.d(segundos)), "--aquecimento", "0", "--saida", os.path.join(pasta, f"aquecimento-{int(time.time())}")]
        if corpo:
            cmd += ["--corpo", corpo]
        subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, cwd=RAIZ,
                       env=dict(os.environ, PYTHONIOENCODING="utf-8"))

    def esperar_fila(self, limite: float = 600):
        """O POST responde antes do alerta ser avaliado: espera os consumidores zerarem a fila."""
        inicio, primeiro = time.time(), None
        while True:
            saida = kubectl("exec", "-n", NS, "rabbitmq-0", "--", "rabbitmqctl", "-q", "list_queues", "messages",
                            check=False, timeout=30)
            total = sum(int(x) for x in saida.split() if x.isdigit())
            primeiro = total if primeiro is None else primeiro
            if total == 0 or time.time() - inicio > limite:
                break
            time.sleep(3)
        self.reg.evento("fila_vazia", "rabbitmq", detalhe=f"{primeiro} mensagens pendentes ao fim da carga, "
                                                          f"{time.time() - inicio:.0f} s para esvaziar")
        time.sleep(10)

    def restaurar(self):
        print(">> devolvendo o cluster ao normal (kubectl apply -f k8s/)")
        try:
            for no in kjson("get", "nodes")["items"]:
                if no["spec"].get("unschedulable"):
                    kubectl("uncordon", no["metadata"]["name"], check=False)
                    self.reg.evento("no_liberado", no["metadata"]["name"], detalhe="uncordon (restauração)")
        except Exception as ex:  # noqa: BLE001 - a restauração continua mesmo se uma etapa falhar
            print(f"   aviso: não deu para conferir os nós ({ex})")
        kubectl("apply", "-f", os.path.join(RAIZ, "k8s"), check=False)
        if self.mudou_configmap:
            for api in APIS:
                kubectl("rollout", "restart", "deployment", api, "-n", NS)
        for api in APIS:
            kubectl("rollout", "status", "deployment", api, "-n", NS, "--timeout=300s", check=False)
        self.reg.evento("restaurado", detalhe="manifestos de k8s/ reaplicados")

    # ================================ Os experimentos ================================

    def escala(self):
        """1, 2, 4 e 8 réplicas, HPA removido, MESMA carga: 128 trabalhadores, o bastante para saturar 8 réplicas."""
        lista = [1, 2, 4] if self.args.rapido else [1, 2, 4, 8]
        self.reg.meta["tipo"] = "comparacao"
        self.reg.meta["parametro"] = "replicas"
        for n in lista:
            self.preparar(n)
            self.aquecer(ROTA_POST, "POST", "ar")
            self.esperar_fila()
            ex = self.gerar(f"{n} réplica" + ("s" if n > 1 else ""), ROTA_POST, 128, 4, self.d(60), 10, "POST", "ar")
            ex["replicas"] = n
            self.esperar_fila()

    def hpa(self):
        """HPA ligado (mín. 2, máx. 10). Rampa de 4 a 128 trabalhadores em 120 s, segura até 300 s, depois observa a redução."""
        self.reg.meta["tipo"] = "linha_do_tempo"
        kubectl("apply", "-f", os.path.join(RAIZ, "k8s", "40-hpa.yaml"))
        kubectl("scale", "deployment", APP, "-n", NS, "--replicas=2")
        print(">> esperando o HPA estabilizar em 2 réplicas (pode levar até 5 min se algo o deixou alto)")
        fim = time.time() + 420
        while time.time() < fim:
            h = kjson("get", "hpa", APP, "-n", NS)
            if h.get("status", {}).get("currentReplicas") == 2 and h.get("status", {}).get("desiredReplicas") == 2:
                break
            time.sleep(5)
        kubectl("rollout", "status", "deployment", APP, "-n", NS, "--timeout=240s")
        self.esperar_sem_terminando()
        time.sleep(10)
        self.reg.evento("preparado", APP, detalhe="HPA ligado, 2 réplicas")
        self.gerar("rampa com HPA", ROTA_POST, 128, 4, self.d(300), 0, "POST", "ar", rampa=self.d(120), com_hpa=True)
        self.esperar_fila()
        limite = self.d(420)
        print(f">> observando a redução do HPA (até {limite:.0f} s; ele espera 5 min de calma antes de reduzir)")
        fim = time.time() + limite
        while time.time() < fim:
            st = kjson("get", "hpa", APP, "-n", NS).get("status", {})
            if st.get("currentReplicas") == 2 and st.get("desiredReplicas") == 2:
                self.reg.evento("hpa_reducao_concluida", APP, detalhe="de volta ao mínimo de 2 réplicas")
                break
            time.sleep(5)
        self.reg.meta["observacao_fim"] = time.time()

    def pod_apagado(self):
        """2 réplicas, carga constante de 32 trabalhadores; no segundo 30, kubectl delete pod."""
        self.reg.meta["tipo"] = "linha_do_tempo"
        self.preparar(2)
        self.aquecer(ROTA_POST, "POST", "ar")
        self.esperar_fila()

        def apagar():
            alvo = sorted(self.pods_prontos(), key=lambda p: p["nome"])[0]
            self.reg.meta["acao"] = {"epoch": time.time(), "descricao": f"pod apagado: {alvo['nome']}", "pod": alvo["nome"]}
            self.reg.evento("acao_pod_apagado", alvo["nome"], alvo["no"], detalhe="kubectl delete pod")
            kubectl("delete", "pod", alvo["nome"], "-n", NS, "--wait=false")

        self.gerar("pod apagado", ROTA_POST, 32, 2, self.d(90), 5, "POST", "ar", acoes=[(self.d(30), apagar)])
        self.esperar_fila()

    def no_drenado(self):
        """2 réplicas, carga constante; no segundo 30, kubectl drain do nó (agente) que tem uma réplica da API."""
        self.reg.meta["tipo"] = "linha_do_tempo"
        self.preparar(2)
        no = self.escolher_no()
        self.aquecer(ROTA_POST, "POST", "ar")
        self.esperar_fila()

        def drenar():
            self.reg.meta["acao"] = {"epoch": time.time(), "descricao": f"nó drenado: {no}", "no": no}
            self.reg.evento("acao_no_drenado", no, no, detalhe="kubectl drain --ignore-daemonsets --delete-emptydir-data")
            kubectl("drain", no, "--ignore-daemonsets", "--delete-emptydir-data", "--timeout=180s")
            self.reg.evento("drain_concluido", no, no)

        ex = self.gerar("nó drenado", ROTA_POST, 32, 2, self.d(120), 5, "POST", "ar", acoes=[(self.d(30), drenar)])
        kubectl("uncordon", no)
        self.reg.evento("no_liberado", no, no, detalhe="kubectl uncordon (os pods NÃO voltam sozinhos)")
        ex["no_drenado"] = no
        self.esperar_fila()

    def escolher_no(self) -> str:
        """Um agente (não o plano de controle) com réplica da API e SEM o Postgres/RabbitMQ (volumes presos ao nó)."""
        nos = kjson("get", "nodes")["items"]
        controle = {n["metadata"]["name"] for n in nos if "node-role.kubernetes.io/control-plane" in n["metadata"].get("labels", {})}
        pods = kjson("get", "pods", "-n", NS)["items"]
        com_estado = {p["spec"].get("nodeName") for p in pods if p["metadata"]["name"] in ("postgres-0", "rabbitmq-0")}
        for tentativa in range(3):
            com_api = {p["no"] for p in self.pods_prontos()}
            candidatos = sorted(com_api - controle - com_estado) or sorted(com_api - controle)
            if candidatos:
                escolhido = candidatos[0]
                if escolhido in com_estado:
                    print(f"   aviso: {escolhido} também tem um serviço com volume local; ele ficará Pending até o uncordon")
                self.reg.evento("no_escolhido", escolhido, escolhido, detalhe=f"réplicas da API em: {sorted(com_api)}")
                return escolhido
            # As duas réplicas caíram no plano de controle: recria uma para o scheduler espalhar
            pod = next(p for p in self.pods_prontos() if p["no"] in controle)
            kubectl("delete", "pod", pod["nome"], "-n", NS)
            kubectl("rollout", "status", "deployment", APP, "-n", NS, "--timeout=120s")
            time.sleep(5)
        raise RuntimeError("nenhum nó agente com réplica da API para drenar")

    def rolling(self, com_prestop: bool = True):
        """3 réplicas, carga constante; set image 1.1.0 -> 1.2.0, espera concluir, 30 s depois rollout undo."""
        self.reg.meta["tipo"] = "linha_do_tempo"
        self.reg.meta["prestop"] = com_prestop
        self.garantir_imagem("1.2.0")
        if not com_prestop:
            kubectl("patch", "deployment", APP, "-n", NS, "--type=json",
                    "-p", '[{"op":"remove","path":"/spec/template/spec/containers/0/lifecycle"}]')
            kubectl("rollout", "status", "deployment", APP, "-n", NS, "--timeout=240s")
            self.reg.evento("prestop_removido", APP, detalhe="kubectl patch (lifecycle.preStop removido)")
        self.preparar(3)
        self.aquecer(ROTA_POST, "POST", "ar")
        self.esperar_fila()

        def atualizar():
            self.reg.evento("acao_rollout_inicio", APP, versao="1.2.0", detalhe="kubectl set image ... :1.2.0")
            kubectl("set", "image", f"deployment/{APP}", "-n", NS, f"api=aps-sd/{APP}:1.2.0")
            kubectl("rollout", "status", "deployment", APP, "-n", NS, "--timeout=300s")
            self.reg.evento("rollout_fim", APP, versao="1.2.0", detalhe="kubectl rollout status: concluído")
            time.sleep(self.d(30))
            self.reg.evento("acao_undo_inicio", APP, versao="1.1.0", detalhe="kubectl rollout undo")
            kubectl("rollout", "undo", f"deployment/{APP}", "-n", NS)
            kubectl("rollout", "status", "deployment", APP, "-n", NS, "--timeout=300s")
            self.reg.evento("undo_fim", APP, versao="1.1.0", detalhe="kubectl rollout status: concluído")

        rotulo = "rolling update" + ("" if com_prestop else " sem preStop")
        self.gerar(rotulo, ROTA_POST, 32, 2, self.d(180), 5, "POST", "ar", acoes=[(self.d(20), atualizar)])
        historico = kubectl("rollout", "history", f"deployment/{APP}", "-n", NS, check=False)
        with open(os.path.join(self.reg.pasta, "rollout-history.txt"), "w", encoding="utf-8") as f:
            f.write(historico)
        self.esperar_fila()

    def garantir_imagem(self, versao: str):
        print(f">> construindo e importando aps-sd/{APP}:{versao}")
        r = subprocess.run(["docker", "build", "--quiet", "--build-arg", f"APP_VERSION={versao}",
                            "-t", f"aps-sd/{APP}:{versao}", os.path.join(RAIZ, "src", "AirQuality.Api")],
                           capture_output=True, text=True)
        if r.returncode != 0:
            raise RuntimeError(f"docker build falhou: {r.stderr}")
        r = subprocess.run([achar_k3d(), "image", "import", "-c", "aps", f"aps-sd/{APP}:{versao}"], capture_output=True, text=True)
        if r.returncode != 0:
            raise RuntimeError(f"k3d image import falhou: {r.stderr}")

    def cache(self):
        """Consulta agregada (média do bairro em 24 h): com cache x sem cache, mesma carga, 2 réplicas."""
        self.reg.meta["tipo"] = "comparacao"
        self.reg.meta["parametro"] = "cache"
        self.preparar(2)
        print(">> semeando leituras recentes (a média de 24 h precisa de dados no período)")
        self.aquecer(ROTA_POST, "POST", "ar", segundos=30)
        self.esperar_fila()
        for ligado in (True, False):
            self.mudar_configmap("Cache__Enabled", "true" if ligado else "false")
            self.aquecer(ROTA_AGREGADA)
            self.gerar("com cache" if ligado else "sem cache", ROTA_AGREGADA, 32, 2, self.d(60), 10)

    def fila(self):
        """Ingestão: alerta pela fila (assíncrono) x dentro do POST (síncrono), mesma carga, 2 réplicas."""
        self.reg.meta["tipo"] = "comparacao"
        self.reg.meta["parametro"] = "fila"
        self.preparar(2)
        for ligada in (True, False):
            self.mudar_configmap("Queue__Enabled", "true" if ligada else "false")
            self.aquecer(ROTA_POST, "POST", "ar")
            self.esperar_fila()
            self.gerar("fila (assíncrono)" if ligada else "sem fila (síncrono)", ROTA_POST, 32, 2, self.d(60), 10, "POST", "ar")
            self.esperar_fila()


# ================================ Execução ================================

def rodar(nome: str, args) -> str:
    reg = Registro(nome, os.path.join(RAIZ, "resultados", "etapa5"))
    reg.meta["rapido"] = args.rapido
    print(f"\n================ experimento: {nome} ================\n>> pasta: {os.path.relpath(reg.pasta, RAIZ)}")
    kubectl("config", "use-context", "k3d-aps", check=False)
    obs = Observador(reg)
    obs.start()
    exp = Experimento(args, reg, obs)
    try:
        {"escala": exp.escala, "hpa": exp.hpa, "pod-apagado": exp.pod_apagado, "no-drenado": exp.no_drenado,
         "rolling": lambda: exp.rolling(True), "rolling-sem-prestop": lambda: exp.rolling(False),
         "cache": exp.cache, "fila": exp.fila}[nome]()
    finally:
        try:
            exp.restaurar()
        finally:
            obs.parar.set()
            obs.join(timeout=10)
            reg.salvar()
            reg.fechar()
    try:
        subprocess.run([sys.executable, os.path.join(AQUI, "analise_etapa5.py"), reg.pasta], cwd=RAIZ,
                       env=dict(os.environ, PYTHONIOENCODING="utf-8"))
    except Exception as ex:  # noqa: BLE001
        print(f"   análise falhou ({ex}); rode depois: python carga/analise_etapa5.py {reg.pasta}")
    return reg.pasta


def main():
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[1], formatter_class=argparse.RawDescriptionHelpFormatter,
                                epilog=__doc__.split("Uso")[1] if "Uso" in __doc__ else None)
    p.add_argument("experimento", choices=EXPERIMENTOS + ["todos"])
    p.add_argument("--rapido", action="store_true", help="versão curta (durações / 3), para conferir o fluxo")
    p.add_argument("--sem-janela", action="store_true", help="não abre a janela com os gráficos ao vivo")
    p.add_argument("--gateway", default="http://127.0.0.1:8081")
    args = p.parse_args()

    if not args.sem_janela:
        os.makedirs(os.path.join(RAIZ, "resultados", "etapa5"), exist_ok=True)
        subprocess.Popen([sys.executable, os.path.join(AQUI, "ao_vivo.py"), os.path.join(RAIZ, "resultados", "etapa5")],
                         cwd=RAIZ, env=dict(os.environ, PYTHONIOENCODING="utf-8"))

    nomes = EXPERIMENTOS if args.experimento == "todos" else [args.experimento]
    pastas = [rodar(n, args) for n in nomes]
    print("\n>> pronto. Resultados:")
    for pasta in pastas:
        print(f"   {os.path.relpath(pasta, RAIZ)}  (tabela.md, graficos/)")


if __name__ == "__main__":
    main()
