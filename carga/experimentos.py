#!/usr/bin/env python3
"""
Experimentos da Etapa 5: escalabilidade e resiliência, com o gerador de carga rodando.

Cada experimento prepara o cluster, liga 4 processos do carga/loadgen.py ao mesmo tempo (um só já gasta
boa parte de um núcleo), executa a ação do teste no segundo combinado e anota, com horário, tudo o que o
Kubernetes fez: pods criados, prontos e removidos, decisões do HPA. No fim devolve o cluster ao normal
(kubectl apply -f k8s/) e chama o carga/analise_etapa5.py, que gera tabelas e gráficos.

Uso:
  python carga/experimentos.py escala        1, 2, 4 e 8 réplicas, 64 trabalhadores, 60 s, 3 execuções, POST e GET
  python carga/experimentos.py hpa           HPA ligado, rampa de 1 a 64 trabalhadores em 120 s, 300 s de carga
  python carga/experimentos.py pod-apagado   2 réplicas, 16 trabalhadores, kubectl delete pod aos 25 s, 3 execuções
  python carga/experimentos.py no-drenado    3 réplicas, 16 trabalhadores, kubectl drain aos 25 s (nó sem banco e nó com banco)
  python carga/experimentos.py rolling       3 réplicas, 16 trabalhadores, set image / rollout undo aos 20 s,
                                             com e sem preStop, 3 execuções de cada
  python carga/experimentos.py todos         todos acima, em sequência (~1 h 30)

Opções: --rapido (durações / 3 e 1 execução, para conferir o fluxo), --gateway URL.
Resultados em resultados/etapa5/<experimento>/ (dados brutos, eventos.csv, experimento.json, tabela.md, graficos/).
O serviço medido é a air-quality-api, a de ingestão.
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

AQUI = os.path.dirname(os.path.abspath(__file__))
RAIZ = os.path.dirname(AQUI)
NS = "aps"
APP = "air-quality-api"
APIS = ["air-quality-api", "flooding-api", "thermal-inversion-api"]
ROTA_POST = "/air-quality/api/v1/air-quality/particulate"
ROTA_GET = "/air-quality/api/v1/air-quality/areas/CENTRO/average?hours=24"
EXPERIMENTOS = ["escala", "hpa", "pod-apagado", "no-drenado", "rolling"]
GERADORES = 4


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


def pronto(p: dict) -> bool:
    estados = p.get("status", {}).get("containerStatuses") or []
    return bool(estados) and all(c.get("ready") for c in estados) and not p["metadata"].get("deletionTimestamp")


# ================================ Registro e observador ================================

class Registro:
    """A pasta do experimento, o diário de eventos (eventos.csv) e o experimento.json com cada execução."""

    def __init__(self, nome: str, rapido: bool):
        self.nome = nome
        self.pasta = os.path.join(RAIZ, "resultados", "etapa5", nome + ("-rapido" if rapido else ""))
        if os.path.isdir(self.pasta):
            shutil.rmtree(self.pasta)
        os.makedirs(self.pasta)
        self._trava = threading.Lock()
        self._arq = open(os.path.join(self.pasta, "eventos.csv"), "w", newline="", encoding="utf-8")
        self._w = csv.writer(self._arq)
        self._w.writerow(["epoch", "hora", "tipo", "objeto", "no", "versao", "detalhe"])
        self.meta = {"experimento": nome, "rapido": rapido, "inicio": dt.datetime.now().isoformat(timespec="seconds"),
                     "comando": " ".join(sys.argv), "execucoes": []}

    def evento(self, tipo: str, objeto: str = "", no: str = "", versao: str = "", detalhe: str = "", quieto=False):
        agora = time.time()
        with self._trava:
            self._w.writerow([round(agora, 3), time.strftime("%H:%M:%S"), tipo, objeto, no, versao, detalhe])
            self._arq.flush()
        if not quieto:
            print(f"   [{time.strftime('%H:%M:%S')}] {tipo} {objeto} {detalhe}".rstrip(), flush=True)
        return agora

    def salvar(self):
        self.meta["fim"] = dt.datetime.now().isoformat(timespec="seconds")
        with open(os.path.join(self.pasta, "experimento.json"), "w", encoding="utf-8") as f:
            json.dump(self.meta, f, ensure_ascii=False, indent=2)

    def fechar(self):
        self._arq.close()


class Observador(threading.Thread):
    """
    A cada segundo lê os pods do namespace e anota as TRANSIÇÕES no diário (pod_criado, pod_pronto,
    pod_nao_pronto, pod_terminando, pod_removido). A cada 2 s lê o HPA (hpa.csv e hpa_decisao).
    Também grava replicas.csv: réplicas prontas da API por segundo, por versão e por nó.
    """

    def __init__(self, reg: Registro):
        super().__init__(daemon=True)
        self.reg = reg
        self.parar = threading.Event()
        self._rep = open(os.path.join(reg.pasta, "replicas.csv"), "w", newline="", encoding="utf-8")
        self._wrep = csv.writer(self._rep)
        self._wrep.writerow(["epoch", "hora", "prontas", "existentes", "por_versao", "por_no", "postgres_pronto"])
        self._hpa = open(os.path.join(reg.pasta, "hpa.csv"), "w", newline="", encoding="utf-8")
        self._whpa = csv.writer(self._hpa)
        self._whpa.writerow(["epoch", "hora", "atuais", "desejadas", "cpu_pct"])
        self._desejadas = None

    def run(self):
        anteriores: dict[str, dict] | None = None
        tique = 0
        while not self.parar.is_set():
            inicio = time.time()
            try:
                itens = kjson("get", "pods", "-n", NS)["items"]
            except Exception:  # noqa: BLE001 - o observador nunca derruba o experimento
                itens = None
            if itens is not None:
                atuais = {}
                for p in itens:
                    nome = p["metadata"]["name"]
                    atuais[nome] = {
                        "app": p["metadata"].get("labels", {}).get("app", ""),
                        "pronto": pronto(p),
                        "terminando": p["metadata"].get("deletionTimestamp") is not None,
                        "versao": p["spec"]["containers"][0]["image"].rsplit(":", 1)[-1],
                        "no": p["spec"].get("nodeName") or "",
                    }
                if anteriores is not None:
                    self._transicoes(anteriores, atuais)
                anteriores = atuais
                alvo = [v for v in atuais.values() if v["app"] == APP]
                prontas = [v for v in alvo if v["pronto"]]
                conta = lambda chave: ";".join(f"{k}:{sum(1 for v in prontas if v[chave] == k)}"  # noqa: E731
                                               for k in sorted({v[chave] for v in prontas}))
                self._wrep.writerow([round(inicio, 3), time.strftime("%H:%M:%S"), len(prontas),
                                     sum(1 for v in alvo if not v["terminando"]), conta("versao"), conta("no"),
                                     int(any(v["pronto"] for v in atuais.values() if v["app"] == "postgres"))])
                self._rep.flush()
            if tique % 2 == 0:
                self._ler_hpa(inicio)
            tique += 1
            self.parar.wait(max(0.05, 1 - (time.time() - inicio)))
        self._rep.close()
        self._hpa.close()

    def _transicoes(self, anteriores: dict, atuais: dict):
        for nome, v in atuais.items():
            q = v["app"] not in (APP, "postgres")
            ant = anteriores.get(nome)
            if ant is None:
                self.reg.evento("pod_criado", nome, v["no"], v["versao"], f"app={v['app']}", quieto=q)
                ant = {"pronto": False, "terminando": False}
            if v["pronto"] and not ant["pronto"]:
                self.reg.evento("pod_pronto", nome, v["no"], v["versao"], f"app={v['app']}", quieto=q)
            if not v["pronto"] and ant["pronto"] and not v["terminando"]:
                self.reg.evento("pod_nao_pronto", nome, v["no"], v["versao"], f"app={v['app']}", quieto=q)
            if v["terminando"] and not ant["terminando"]:
                self.reg.evento("pod_terminando", nome, v["no"], v["versao"], f"app={v['app']}", quieto=q)
        for nome, ant in anteriores.items():
            if nome not in atuais:
                self.reg.evento("pod_removido", nome, ant["no"], ant["versao"], f"app={ant['app']}",
                                quieto=ant["app"] not in (APP, "postgres"))

    def _ler_hpa(self, agora: float):
        saida = kubectl("get", "hpa", APP, "-n", NS, "-o", "json", check=False, timeout=15)
        if not saida.strip():
            return
        try:
            st = json.loads(saida).get("status", {})
        except json.JSONDecodeError:
            return
        cpu = ""
        for m in st.get("currentMetrics") or []:
            cpu = m.get("resource", {}).get("current", {}).get("averageUtilization", cpu)
        desejadas = st.get("desiredReplicas")
        self._whpa.writerow([round(agora, 3), time.strftime("%H:%M:%S"), st.get("currentReplicas"), desejadas, cpu])
        self._hpa.flush()
        if desejadas is not None and self._desejadas is not None and desejadas != self._desejadas:
            self.reg.evento("hpa_decisao", APP, detalhe=f"{self._desejadas} -> {desejadas} réplicas (CPU {cpu}%)")
        if desejadas is not None:
            self._desejadas = desejadas


# ================================ Peças comuns ================================

class Experimento:
    def __init__(self, args, reg: Registro):
        self.args, self.reg = args, reg
        self.gw = args.gateway.rstrip("/")

    def d(self, segundos: float) -> float:
        """Duração; o modo --rapido divide por 3 (para conferir o fluxo, não para medir)."""
        return max(8, round(segundos / 3)) if self.args.rapido else segundos

    def reps(self, n: int) -> int:
        return 1 if self.args.rapido else n

    # ---------- preparação ----------
    def esperar_estavel(self, replicas: int | None = None, limite: float = 240):
        """Espera o Deployment ter as réplicas prontas e nenhum pod terminando."""
        kubectl("rollout", "status", "deployment", APP, "-n", NS, f"--timeout={int(limite)}s")
        fim = time.time() + limite
        while time.time() < fim:
            pods = kjson("get", "pods", "-n", NS, "-l", f"app={APP}")["items"]
            terminando = any(p["metadata"].get("deletionTimestamp") for p in pods)
            prontos = sum(1 for p in pods if pronto(p))
            if not terminando and (replicas is None or prontos == replicas):
                break
            time.sleep(2)
        time.sleep(10)   # o gateway leva alguns segundos para atualizar a lista de destinos

    def preparar(self, replicas: int):
        print(f">> preparando: {replicas} réplica(s) da {APP}, HPA removido")
        kubectl("delete", "hpa", APP, "-n", NS, "--ignore-not-found")
        kubectl("scale", "deployment", APP, "-n", NS, f"--replicas={replicas}")
        self.esperar_estavel(replicas)
        self.reg.evento("preparado", APP, detalhe=f"{replicas} réplica(s), HPA removido")

    def pods_prontos(self) -> list[dict]:
        return [{"nome": p["metadata"]["name"], "no": p["spec"].get("nodeName", "")}
                for p in kjson("get", "pods", "-n", NS, "-l", f"app={APP}")["items"] if pronto(p)]

    def no_do_banco(self) -> str:
        return kjson("get", "pod", "postgres-0", "-n", NS)["spec"]["nodeName"]

    def agentes(self) -> list[str]:
        return sorted(n["metadata"]["name"] for n in kjson("get", "nodes")["items"]
                      if "node-role.kubernetes.io/control-plane" not in n["metadata"].get("labels", {}))

    # ---------- carga ----------
    def carregar(self, rotulo: str, rota: str, trabalhadores: int, duracao: float, aquecimento: float = 0,
                 metodo: str = "POST", rampa: float = 0, acoes: list | None = None, extra: dict | None = None) -> dict:
        """Liga os 4 geradores, roda as ações no segundo combinado (cada uma numa thread) e espera terminar."""
        slug = f"e{len(self.reg.meta['execucoes']) + 1:02d}-" + re.sub(r"[^a-z0-9]+", "-", rotulo.lower()).strip("-")
        prefixos = [os.path.join(self.reg.pasta, f"{slug}-g{k + 1}") for k in range(GERADORES)]
        divisao = [trabalhadores // GERADORES + (1 if k < trabalhadores % GERADORES else 0) for k in range(GERADORES)]
        print(f">> {rotulo}: {metodo} {rota} | {trabalhadores} trabalhadores em {GERADORES} geradores | {duracao:g} s"
              + (f" (rampa {rampa:g} s)" if rampa else ""))
        ambiente = dict(os.environ, PYTHONIOENCODING="utf-8")
        processos, logs = [], []
        inicio = time.time()
        for k, (prefixo, n) in enumerate(zip(prefixos, divisao)):
            cmd = [sys.executable, os.path.join(AQUI, "loadgen.py"), self.gw + rota, "-X", metodo, "-c", str(n),
                   "-d", str(duracao), "--aquecimento", str(aquecimento), "--timeout", "5", "--saida", prefixo]
            if metodo == "POST":
                cmd += ["--corpo", "carga"]
            if rampa:
                cmd += ["--rampa", str(rampa)]
            if k == 0:
                cmd += ["--top", "--top-intervalo", "5", "--top-atraso", "0"]
            log = open(prefixo + ".log", "w", encoding="utf-8")
            logs.append(log)
            processos.append(subprocess.Popen(cmd, stdout=log, stderr=subprocess.STDOUT, env=ambiente, cwd=RAIZ))
        self.reg.evento("carga_inicio", detalhe=rotulo)

        execucao = {"rotulo": rotulo, "slug": slug, "inicio": inicio, "prefixos": [os.path.basename(p) for p in prefixos],
                    "rota": f"{metodo} {rota}", "trabalhadores": trabalhadores, "duracao_s": duracao,
                    "aquecimento_s": aquecimento, "rampa_s": rampa, "acoes": [], **(extra or {})}

        def disparar(segundo, nome, funcao):
            espera = inicio + segundo - time.time()
            if espera > 0:
                time.sleep(espera)
            registro = {"nome": nome, "inicio": time.time()}
            execucao["acoes"].append(registro)
            try:
                detalhe = funcao()
                if detalhe:
                    registro["detalhe"] = detalhe
            except Exception as ex:  # noqa: BLE001
                registro["erro"] = str(ex)
                print(f"   ação {nome} falhou: {ex}")
            registro["fim"] = time.time()

        threads = [threading.Thread(target=disparar, args=a, daemon=True) for a in (acoes or [])]
        for t in threads:
            t.start()
        for p in processos:
            p.wait()
        for t in threads:
            t.join(timeout=600)
        for log in logs:
            log.close()
        execucao["fim"] = time.time()
        execucao["codigos_saida"] = [p.returncode for p in processos]
        self.reg.evento("carga_fim", detalhe=rotulo)
        self.reg.meta["execucoes"].append(execucao)
        self.reg.salvar()
        if any(execucao["codigos_saida"]):
            print(f"   ATENÇÃO: gerador terminou com erro, veja {prefixos[0]}.log")
        return execucao

    def aquecer(self, rota: str, metodo: str = "POST", segundos: float = 20):
        """
        Carga DESCARTADA antes de medir: um pod recém-criado ainda compila o código (JIT) e tem o pool de
        conexões vazio. Como o gateway reparte igualmente, uma réplica fria atrasa todo mundo.
        16 trabalhadores por réplica, por 20 s.
        """
        pasta = os.path.join(self.reg.pasta, "descartado")
        os.makedirs(pasta, exist_ok=True)
        n = 16 * max(1, len(self.pods_prontos()))
        cmd = [sys.executable, os.path.join(AQUI, "loadgen.py"), self.gw + rota, "-X", metodo, "-c", str(n),
               "-d", str(segundos), "--aquecimento", "0", "--saida", os.path.join(pasta, f"aquecimento-{int(time.time())}")]
        if metodo == "POST":
            cmd += ["--corpo", "carga"]
        subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, cwd=RAIZ,
                       env=dict(os.environ, PYTHONIOENCODING="utf-8"))
        time.sleep(5)

    def restaurar(self):
        print(">> devolvendo o cluster ao normal (uncordon + kubectl apply -f k8s/)")
        for no in kjson("get", "nodes")["items"]:
            if no["spec"].get("unschedulable"):
                kubectl("uncordon", no["metadata"]["name"], check=False)
        kubectl("apply", "-f", os.path.join(RAIZ, "k8s"), check=False)
        kubectl("rollout", "status", "statefulset", "postgres", "-n", NS, "--timeout=300s", check=False)
        for api in APIS:
            kubectl("rollout", "status", "deployment", api, "-n", NS, "--timeout=300s", check=False)
        self.reg.evento("restaurado", detalhe="manifestos de k8s/ reaplicados")

    def reequilibrar(self):
        """Depois de um drain os pods ficam todos no nó que sobrou: recria para dividir de novo entre os agentes."""
        for api in APIS:
            kubectl("rollout", "restart", "deployment", api, "-n", NS)
        for api in APIS:
            kubectl("rollout", "status", "deployment", api, "-n", NS, "--timeout=300s")
        self.esperar_estavel()

    # ================================ 13.3 Escala manual ================================

    def escala(self):
        """HPA removido; 1, 2, 4 e 8 réplicas; 64 trabalhadores, 60 s, 10 s de aquecimento; 3 execuções; POST e GET."""
        self.reg.meta["tipo"] = "escala"
        for n in ([1, 2, 4] if self.args.rapido else [1, 2, 4, 8]):
            self.preparar(n)
            for metodo, rota in (("POST", ROTA_POST), ("GET", ROTA_GET)):
                self.aquecer(rota, metodo)
                for rep in range(1, self.reps(3) + 1):
                    self.carregar(f"{metodo} {n} replicas exec {rep}", rota, 64, self.d(60), 10, metodo,
                                  extra={"replicas": n, "metodo": metodo, "repeticao": rep})
                    time.sleep(10)

    # ================================ 13.4 HPA ================================

    def hpa(self):
        """HPA por CPU (mín. 2, máx. 10, meta 50%); rampa de 1 a 64 trabalhadores em 120 s; 300 s; observa mais 7 min."""
        self.reg.meta["tipo"] = "hpa"
        kubectl("apply", "-f", os.path.join(RAIZ, "k8s", "40-hpa.yaml"))
        kubectl("scale", "deployment", APP, "-n", NS, "--replicas=2")
        print(">> esperando o HPA estar em 2 réplicas")
        fim = time.time() + 420
        while time.time() < fim:
            st = kjson("get", "hpa", APP, "-n", NS).get("status", {})
            if st.get("currentReplicas") == 2 and st.get("desiredReplicas") == 2 and st.get("currentMetrics"):
                break
            time.sleep(5)
        self.esperar_estavel(2)
        self.reg.evento("preparado", APP, detalhe="HPA ligado, 2 réplicas")
        ex = self.carregar("rampa com HPA", ROTA_POST, 64, self.d(300), 0, "POST", rampa=self.d(120))
        observar = self.d(420)
        print(f">> observando a redução por {observar:.0f} s (o HPA espera 5 min abaixo da meta para reduzir)")
        fim = time.time() + observar
        while time.time() < fim:
            st = kjson("get", "hpa", APP, "-n", NS).get("status", {})
            if st.get("currentReplicas") == 2 and st.get("desiredReplicas") == 2 and time.time() > ex["fim"] + 60:
                self.reg.evento("hpa_reducao_concluida", APP, detalhe="de volta a 2 réplicas")
                break
            time.sleep(5)
        ex["observacao_fim"] = time.time()
        self.reg.salvar()

    # ================================ 13.5 Resiliência ================================

    def pod_apagado(self):
        """2 réplicas, 16 trabalhadores constantes, 60 s; kubectl delete pod aos 25 s; 3 execuções."""
        self.reg.meta["tipo"] = "pod-apagado"
        self.preparar(2)
        self.aquecer(ROTA_POST)
        for rep in range(1, self.reps(3) + 1):
            alvo = {}

            def apagar():
                p = sorted(self.pods_prontos(), key=lambda x: x["nome"])[0]
                alvo.update(p)
                self.reg.evento("acao_pod_apagado", p["nome"], p["no"], detalhe="kubectl delete pod")
                kubectl("delete", "pod", p["nome"], "-n", NS, "--wait=false")
                return f"{p['nome']} ({p['no']})"

            ex = self.carregar(f"pod apagado exec {rep}", ROTA_POST, 16, self.d(60), 0, "POST",
                               acoes=[(self.d(25), "delete pod", apagar)], extra={"repeticao": rep})
            ex["pod_apagado"] = alvo
            self.esperar_estavel(2)

    def no_drenado(self):
        """3 réplicas, 16 trabalhadores, 120 s; kubectl drain aos 25 s. Um nó sem o banco e o nó do banco (uncordon aos 70 s)."""
        self.reg.meta["tipo"] = "no-drenado"
        self.preparar(3)
        for com_banco in (False, True):
            banco = self.no_do_banco()
            no = banco if com_banco else next(a for a in self.agentes() if a != banco)
            self.aquecer(ROTA_POST)
            distribuicao = {p["nome"]: p["no"] for p in self.pods_prontos()}
            self.reg.evento("no_escolhido", no, no, detalhe=f"banco em {banco}; réplicas: {distribuicao}")

            def drenar(no=no):
                self.reg.evento("acao_no_drenado", no, no, detalhe="kubectl drain --ignore-daemonsets --delete-emptydir-data")
                kubectl("drain", no, "--ignore-daemonsets", "--delete-emptydir-data", "--timeout=90s", check=False)
                self.reg.evento("drain_concluido", no, no)

            def liberar(no=no):
                self.reg.evento("acao_uncordon", no, no, detalhe="kubectl uncordon")
                kubectl("uncordon", no)

            acoes = [(self.d(25), "drain", drenar)]
            if com_banco:
                acoes.append((self.d(70), "uncordon", liberar))
            rotulo = "no com banco" if com_banco else "no sem banco"
            ex = self.carregar(rotulo, ROTA_POST, 16, self.d(120), 0, "POST", acoes=acoes,
                               extra={"no_drenado": no, "com_banco": com_banco, "replicas_antes": distribuicao})
            if not com_banco:
                kubectl("uncordon", no)
                self.reg.evento("acao_uncordon", no, no, detalhe="kubectl uncordon (depois da carga)")
            kubectl("rollout", "status", "statefulset", "postgres", "-n", NS, "--timeout=300s")
            self.reequilibrar()
            ex["fim_reequilibrio"] = time.time()
            self.reg.salvar()

    # ================================ 13.6 Rolling update ================================

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

    def rolling(self):
        """3 réplicas, 16 trabalhadores, 70 s; set image 1.2.0 aos 20 s e, em outra execução, rollout undo aos 20 s.
        3 execuções de cada, com e sem preStop de 5 s. maxSurge 1, maxUnavailable 0."""
        self.reg.meta["tipo"] = "rolling"
        self.garantir_imagem("1.2.0")
        for com_prestop in (False, True):
            kubectl("apply", "-f", os.path.join(RAIZ, "k8s", "20-air-quality-api.yaml"))
            self.esperar_estavel()
            if not com_prestop:
                kubectl("patch", "deployment", APP, "-n", NS, "--type=json",
                        "-p", '[{"op":"remove","path":"/spec/template/spec/containers/0/lifecycle"}]')
                self.reg.evento("prestop_removido", APP, detalhe="kubectl patch (lifecycle.preStop removido)")
            self.preparar(3)
            self.aquecer(ROTA_POST)
            sufixo = "com preStop" if com_prestop else "sem preStop"
            for rep in range(1, self.reps(3) + 1):
                for tipo in ("update", "undo"):
                    def trocar(tipo=tipo):
                        if tipo == "update":
                            self.reg.evento("acao_set_image", APP, versao="1.2.0", detalhe="kubectl set image ... :1.2.0")
                            kubectl("set", "image", f"deployment/{APP}", "-n", NS, f"api=aps-sd/{APP}:1.2.0")
                        else:
                            self.reg.evento("acao_undo", APP, versao="1.1.0", detalhe="kubectl rollout undo")
                            kubectl("rollout", "undo", f"deployment/{APP}", "-n", NS)
                        kubectl("rollout", "status", "deployment", APP, "-n", NS, "--timeout=300s")
                        self.reg.evento("rollout_concluido", APP)

                    self.carregar(f"{tipo} {sufixo} exec {rep}", ROTA_POST, 16, self.d(70), 0, "POST",
                                  acoes=[(self.d(20), tipo, trocar)],
                                  extra={"troca": tipo, "prestop": com_prestop, "repeticao": rep})
                    self.esperar_estavel(3)
            historico = kubectl("rollout", "history", f"deployment/{APP}", "-n", NS, check=False)
            with open(os.path.join(self.reg.pasta, f"rollout-history-{sufixo.replace(' ', '-').lower()}.txt"), "w",
                      encoding="utf-8") as f:
                f.write(historico)


# ================================ Execução ================================

def rodar(nome: str, args) -> str:
    reg = Registro(nome, args.rapido)
    print(f"\n================ experimento: {nome} ================\n>> pasta: {os.path.relpath(reg.pasta, RAIZ)}")
    kubectl("config", "use-context", "k3d-aps", check=False)
    reg.meta["estado_inicial"] = kubectl("get", "pods", "-n", NS, "-o", "wide", check=False)
    obs = Observador(reg)
    obs.start()
    exp = Experimento(args, reg)
    try:
        {"escala": exp.escala, "hpa": exp.hpa, "pod-apagado": exp.pod_apagado,
         "no-drenado": exp.no_drenado, "rolling": exp.rolling}[nome]()
    finally:
        try:
            exp.restaurar()
        finally:
            obs.parar.set()
            obs.join(timeout=10)
            reg.salvar()
            reg.fechar()
    subprocess.run([sys.executable, os.path.join(AQUI, "analise_etapa5.py"), reg.pasta], cwd=RAIZ,
                   env=dict(os.environ, PYTHONIOENCODING="utf-8"))
    return reg.pasta


def main():
    p = argparse.ArgumentParser(description="Experimentos da Etapa 5", epilog=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("experimento", choices=EXPERIMENTOS + ["todos"])
    p.add_argument("--rapido", action="store_true", help="durações / 3 e 1 execução, para conferir o fluxo")
    p.add_argument("--gateway", default="http://127.0.0.1:8081")
    args = p.parse_args()
    nomes = EXPERIMENTOS if args.experimento == "todos" else [args.experimento]
    pastas = [rodar(n, args) for n in nomes]
    print("\n>> pronto. Resultados:")
    for pasta in pastas:
        print(f"   {os.path.relpath(pasta, RAIZ)}  (tabela.md, analise.json, graficos/)")


if __name__ == "__main__":
    main()
