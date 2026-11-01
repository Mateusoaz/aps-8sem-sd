#!/usr/bin/env python3
"""Executa os experimentos da Etapa 5 e grava tudo em resultados/etapa5/.

Uso (na raiz do repositório):
  python carga/experimentos.py                roda todos, pulando o que já terminou
  python carga/experimentos.py 5.3 5.4        roda só alguns

Cada execução usa PROCESSOS cópias do loadgen.py ao mesmo tempo. Um processo Python usa
pouco mais de um núcleo, e a Etapa 4 mostrou que isso limitaria a medição com 4 ou 8 réplicas.
As cópias são juntadas em um único -requisicoes.csv, -serie.csv e -resumo.json.
Junto com a carga, a cada 5 s são anotados pods, nós, fila e CPU da máquina (-recursos.jsonl).
"""
import base64
import collections
import csv
import datetime
import json
import os
import subprocess
import sys
import threading
import time
import urllib.request

import psutil

PASTA = "resultados/etapa5"
API = "air-quality-api"
POST_URL = "http://localhost:8081/air-quality/api/v1/air-quality/particulate"
GET_URL = "http://localhost:8081/air-quality/api/v1/air-quality/areas/CENTRO/average?hours=24"
FILA = "air-quality.particulate-readings"
PROCESSOS = 4
OUTROS = ["flooding-api", "thermal-inversion-api", "web-client"]


# ---------------------------------------------------------------- comandos do cluster

def k(*args, check=True, timeout=240):
    r = subprocess.run(["kubectl", *args], capture_output=True, text=True, encoding="utf-8",
                       errors="replace", timeout=timeout)
    if check and r.returncode:
        raise RuntimeError(f"kubectl {' '.join(args)}: {r.stderr.strip()}")
    return r.stdout


def log(texto):
    print(f"{datetime.datetime.now():%H:%M:%S} {texto}", flush=True)


def pods_api():
    dados = json.loads(k("get", "pods", "-n", "aps", "-l", f"app={API}", "-o", "json"))
    saida = []
    for p in dados["items"]:
        estados = p["status"].get("containerStatuses") or [{}]
        saida.append({"nome": p["metadata"]["name"], "fase": p["status"].get("phase"),
                      "pronto": bool(estados[0].get("ready")), "encerrando": "deletionTimestamp" in p["metadata"],
                      "no": p["spec"].get("nodeName"), "reinicios": estados[0].get("restartCount", 0),
                      "imagem": p["spec"]["containers"][0]["image"].split(":")[-1]})
    return saida


class Fila:
    """Lê o tamanho da fila pela API do painel do RabbitMQ, mais leve que rodar rabbitmqctl."""

    def __init__(self):
        segredo = json.loads(k("get", "secret", "banco-credenciais", "-n", "aps", "-o", "json"))["data"]
        decodifica = lambda c: base64.b64decode(segredo[c]).decode()
        self.auth = base64.b64encode(f"{decodifica('RABBITMQ_USER')}:{decodifica('RABBITMQ_PASSWORD')}".encode()).decode()
        self.pf = None

    def tamanho(self):
        for _ in range(2):
            try:
                pedido = urllib.request.Request(f"http://127.0.0.1:15672/api/queues/%2F/{FILA}",
                                                headers={"Authorization": f"Basic {self.auth}"})
                dados = json.load(urllib.request.urlopen(pedido, timeout=3))
                return dados.get("messages", 0)
            except Exception:
                if self.pf is None or self.pf.poll() is not None:
                    self.pf = subprocess.Popen(["kubectl", "port-forward", "-n", "aps", "pod/rabbitmq-0", "15672"],
                                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                time.sleep(2)
        return None

    def fecha(self):
        if self.pf:
            self.pf.terminate()


def espera_sistema(fila, pausa=20):
    """Toda execução começa com a fila vazia e todos os pods prontos."""
    while True:
        pendentes = [l for l in k("get", "pods", "-n", "aps", "--no-headers").splitlines()
                     if " 1/1 " not in l or "Running" not in l]
        tamanho = fila.tamanho()
        if not pendentes and tamanho == 0:
            break
        log(f"aguardando: fila={tamanho} pods fora de 1/1={len(pendentes)}")
        time.sleep(10)
    time.sleep(pausa)


def replicas(n, deploy=API):
    k("scale", "deployment", deploy, "-n", "aps", f"--replicas={n}")
    k("rollout", "status", f"deployment/{deploy}", "-n", "aps", "--timeout=200s")


def sem_hpa():
    k("delete", "hpa", API, "-n", "aps", "--ignore-not-found")


# ---------------------------------------------------------------- medição

class Monitor(threading.Thread):
    """Anota o estado do sistema a cada 5 s e os pods da API a cada segundo."""

    def __init__(self, nome, fila):
        super().__init__(daemon=True)
        self.nome, self.fila = nome, fila
        self.fim = threading.Event()
        self.pods = []
        self.vigia = threading.Thread(target=self.vigia_pods, daemon=True)

    def vigia_pods(self):
        while not self.fim.is_set():
            try:
                self.pods.append({"epoch": time.time(), "pods": pods_api()})
            except Exception:
                pass
            self.fim.wait(1)

    def run(self):
        self.vigia.start()
        psutil.cpu_percent(None)
        with open(f"{PASTA}/{self.nome}-recursos.jsonl", "w", encoding="utf-8") as f:
            while not self.fim.wait(5):
                f.write(json.dumps({
                    "epoch": time.time(), "cpu_maquina_pct": psutil.cpu_percent(None),
                    "memoria_maquina_pct": psutil.virtual_memory().percent, "fila": self.fila.tamanho(),
                    "top_pods": k("top", "pod", "-n", "aps", "--no-headers", check=False, timeout=30),
                    "top_nos": k("top", "node", "--no-headers", check=False, timeout=30),
                    "hpa": k("get", "hpa", "-n", "aps", "--no-headers", check=False, timeout=30),
                }, ensure_ascii=False) + "\n")
                f.flush()

    def termina(self):
        self.fim.set()
        self.join(40)
        self.vigia.join(10)
        with open(f"{PASTA}/{self.nome}-pods.json", "w", encoding="utf-8") as f:
            json.dump(self.pods, f)


def percentil(ordenados, p):
    if not ordenados:
        return None
    return round(ordenados[max(1, -(-len(ordenados) * p // 100)) - 1], 2)


def junta(nome, inicio, duracao, aquecimento, eventos, parametros):
    """Junta as cópias do gerador nos três arquivos da execução e devolve o resumo."""
    linhas = []
    for i in range(PROCESSOS):
        parte = f"{PASTA}/_{nome}-p{i}-requisicoes.csv"
        if os.path.exists(parte):
            linhas += [dict(l, processo=i) for l in csv.DictReader(open(parte, encoding="utf-8"))]
        for sufixo in ("requisicoes.csv", "serie.csv", "resumo.json"):
            if os.path.exists(f"{PASTA}/_{nome}-p{i}-{sufixo}"):
                os.remove(f"{PASTA}/_{nome}-p{i}-{sufixo}")
    linhas.sort(key=lambda l: float(l["inicio_epoch"]))
    colunas = list(linhas[0]) if linhas else []
    with open(f"{PASTA}/{nome}-requisicoes.csv", "w", newline="", encoding="utf-8") as f:
        saida = csv.DictWriter(f, fieldnames=colunas)
        saida.writeheader()
        saida.writerows(linhas)

    # Série por segundo, pelo instante em que cada resposta terminou.
    por_segundo = collections.defaultdict(list)
    for l in linhas:
        por_segundo[int(float(l["inicio_epoch"]) + float(l["latencia_ms"]) / 1000)].append(l)
    serie = []
    for s in sorted(por_segundo):
        grupo = por_segundo[s]
        lat = sorted(float(l["latencia_ms"]) for l in grupo)
        erros = sum(1 for l in grupo if l["erro"])
        serie.append({"hora": f"{datetime.datetime.fromtimestamp(s):%H:%M:%S}", "epoch": s,
                      "decorrido_s": s - int(inicio), "respostas": len(grupo), "vazao_req_s": len(grupo) - erros,
                      "erros": erros, "p50_ms": percentil(lat, 50), "p95_ms": percentil(lat, 95),
                      "p99_ms": percentil(lat, 99), "pods_distintos": len({l["x_pod"] for l in grupo if l["x_pod"]}),
                      "v110": sum(1 for l in grupo if l["x_versao"] == "1.1.0"),
                      "v120": sum(1 for l in grupo if l["x_versao"] == "1.2.0")})
    if serie:
        with open(f"{PASTA}/{nome}-serie.csv", "w", newline="", encoding="utf-8") as f:
            saida = csv.DictWriter(f, fieldnames=list(serie[0]))
            saida.writeheader()
            saida.writerows(serie)

    uteis = [l for l in linhas if l["aquecimento"] == "0"]
    lat = sorted(float(l["latencia_ms"]) for l in uteis)
    erros = [l for l in uteis if l["erro"]]
    janela = duracao - aquecimento
    resumo = {
        "nome": nome, "parametros": parametros, "inicio": f"{datetime.datetime.fromtimestamp(inicio):%Y-%m-%dT%H:%M:%S}",
        "inicio_epoch": inicio, "eventos": eventos, "requisicoes": len(uteis), "falhas": len(erros),
        "taxa_erro_pct": round(100 * len(erros) / len(uteis), 3) if uteis else 0,
        "vazao_req_s": round((len(uteis) - len(erros)) / janela, 1),
        "latencia_media_ms": round(sum(lat) / len(lat), 2) if lat else None,
        "p50_ms": percentil(lat, 50), "p95_ms": percentil(lat, 95), "p99_ms": percentil(lat, 99),
        "little_trabalhadores": round(len(uteis) / janela * sum(lat) / len(lat) / 1000, 1) if lat else None,
        "por_pod": dict(collections.Counter(l["x_pod"] or "(sem X-Pod)" for l in uteis)),
        "por_versao": dict(collections.Counter(l["x_versao"] or "(sem)" for l in uteis)),
        "por_erro": dict(collections.Counter(l["erro"] for l in erros)),
        "requisicoes_no_aquecimento": len(linhas) - len(uteis),
    }
    with open(f"{PASTA}/{nome}-resumo.json", "w", encoding="utf-8") as f:
        json.dump(resumo, f, ensure_ascii=False, indent=2)
    return resumo


def carga(nome, fila, trabalhadores, duracao, aquecimento=10, rampa=None, url=POST_URL, acoes=(), extra=None):
    """Roda uma execução: gerador, monitor e as ações marcadas para cada instante."""
    if os.path.exists(f"{PASTA}/{nome}-resumo.json"):
        log(f"{nome}: já feito, pulando")
        return json.load(open(f"{PASTA}/{nome}-resumo.json", encoding="utf-8"))
    log(f"{nome}: início ({trabalhadores} trabalhadores, {duracao} s)")
    monitor = Monitor(nome, fila)
    monitor.start()
    processos, por_processo = [], [trabalhadores // PROCESSOS + (i < trabalhadores % PROCESSOS) for i in range(PROCESSOS)]
    pasta_relativa = os.path.relpath(PASTA, "resultados")
    inicio = time.time()
    for i, c in enumerate(por_processo):
        comando = [sys.executable, "carga/loadgen.py", url, "-c", str(c), "-d", str(duracao),
                   "--aquecimento", str(aquecimento), "--prefixo", f"{pasta_relativa}/_{nome}-p{i}"]
        if url == POST_URL:
            comando += ["--payload", "ar"]
        if rampa:
            comando += ["--rampa", str(rampa)]
        processos.append(subprocess.Popen(comando, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))
    eventos = []

    def marca(texto):
        eventos.append({"evento": texto, "epoch": time.time(), "hora": f"{datetime.datetime.now():%H:%M:%S}",
                        "decorrido_s": round(time.time() - inicio, 1)})
        log(f"{nome}: t={eventos[-1]['decorrido_s']} s {texto}")

    for instante, acao in acoes:
        time.sleep(max(0, inicio + instante - time.time()))
        acao(marca)
    for p in processos:
        p.wait()
    monitor.termina()
    resumo = junta(nome, inicio, duracao, aquecimento, eventos, {"trabalhadores": trabalhadores, "duracao_s": duracao,
                   "aquecimento_s": aquecimento, "rampa_s": rampa, "processos_gerador": PROCESSOS, "url": url, **(extra or {})})
    log(f"{nome}: {resumo['vazao_req_s']} req/s, p95 {resumo['p95_ms']} ms, falhas {resumo['falhas']} de {resumo['requisicoes']} {resumo['por_erro']}")
    return resumo


# ---------------------------------------------------------------- experimentos

def e51(fila):
    """Escala manual: mesma carga com 1, 2, 4 e 8 réplicas."""
    sem_hpa()
    for d in OUTROS:
        replicas(1, d)
    for n in (1, 2, 4, 8):
        for rep in (1, 2, 3):
            if os.path.exists(f"{PASTA}/51-r{n}-exec{rep}-resumo.json"):
                continue
            replicas(n)
            espera_sistema(fila)
            carga(f"51-r{n}-exec{rep}", fila, 64, 60, extra={"replicas": n})


def aquece(url=POST_URL):
    """Carga curta, descartada: o pod recém-criado ainda está compilando o código."""
    comando = [sys.executable, "carga/loadgen.py", url, "-c", "8", "-d", "20", "--aquecimento", "1", "--prefixo", "aquecimento/descartar"]
    if url == POST_URL:
        comando += ["--payload", "ar"]
    subprocess.run(comando, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def serie_escala(fila, prefixo, url):
    """Repete a escala manual: a mesma carga com 1, 2, 4 e 8 réplicas, 3 vezes cada."""
    sem_hpa()
    for d in OUTROS:
        replicas(1, d)
    for n in (1, 2, 4, 8):
        for rep in (1, 2, 3):
            nome = f"{prefixo}-r{n}-exec{rep}"
            if os.path.exists(f"{PASTA}/{nome}-resumo.json"):
                continue
            replicas(n)
            if rep == 1:
                aquece(url)
            espera_sistema(fila)
            carga(nome, fila, 64, 60, url=url, extra={"replicas": n, "pool_conexoes": 8})


def e51b(fila):
    """POST depois de limitar o pool a 8 conexões por pod."""
    serie_escala(fila, "51b", POST_URL)


def e51g(fila):
    """GET com cache: quase não usa o banco, então mostra o efeito da CPU do pod."""
    serie_escala(fila, "51g", GET_URL)


def e52b(fila):
    """HPA de novo, com o pool limitado."""
    sem_hpa()
    e52(fila, "52b-hpa")


def e52(fila, nome="52-hpa"):
    """HPA: rampa de 1 a 64 trabalhadores e observação da redução."""
    if os.path.exists(f"{PASTA}/{nome}-resumo.json"):
        return
    replicas(2)
    espera_sistema(fila)
    k("apply", "-f", "k8s/40-hpa.yaml")
    time.sleep(90)  # o metrics-server precisa de uma medida limpa
    carga(nome, fila, 64, 300, aquecimento=0, rampa=120, extra={"replicas_inicio": 2})
    # A carga acabou: acompanha a redução por 7 minutos.
    log(f"{nome}: observando a redução")
    with open(f"{PASTA}/{nome}-reducao.jsonl", "w", encoding="utf-8") as f:
        for _ in range(84):
            pods = pods_api()
            f.write(json.dumps({"epoch": time.time(), "hora": f"{datetime.datetime.now():%H:%M:%S}",
                                "replicas": len(pods), "prontos": sum(p["pronto"] for p in pods),
                                "fila": fila.tamanho(),
                                "hpa": k("get", "hpa", "-n", "aps", "--no-headers", check=False)}) + "\n")
            f.flush()
            time.sleep(5)
    with open(f"{PASTA}/{nome}-eventos-k8s.json", "w", encoding="utf-8") as f:
        f.write(k("get", "events", "-n", "aps", "--field-selector", f"involvedObject.kind=HorizontalPodAutoscaler", "-o", "json"))
    with open(f"{PASTA}/{nome}-describe.txt", "w", encoding="utf-8") as f:
        f.write(k("describe", "hpa", API, "-n", "aps"))


def e53(fila):
    """Resiliência: pod apagado e nó drenado, sob carga constante."""
    sem_hpa()
    for rep in (1, 2, 3):
        nome = f"53-pod-exec{rep}"
        if os.path.exists(f"{PASTA}/{nome}-resumo.json"):
            continue
        replicas(2)
        espera_sistema(fila)

        def apaga(marca):
            alvo = pods_api()[0]["nome"]
            marca(f"kubectl delete pod {alvo}")
            k("delete", "pod", alvo, "-n", "aps", "--wait=false")

        carga(nome, fila, 16, 60, acoes=[(25, apaga)], extra={"replicas": 2})

    for nome, no, espera in (("53-no-sem-banco", "k3d-aps-server-0", None), ("53-no-com-banco", "k3d-aps-agent-1", 45)):
        if os.path.exists(f"{PASTA}/{nome}-resumo.json"):
            continue
        replicas(3)
        espera_sistema(fila)
        with open(f"{PASTA}/{nome}-antes.txt", "w", encoding="utf-8") as f:
            f.write(k("get", "pods", "-A", "-o", "wide"))

        def drena(marca):
            marca(f"kubectl drain {no}")
            threading.Thread(target=lambda: k("drain", no, "--ignore-daemonsets", "--delete-emptydir-data",
                                              "--timeout=120s", check=False, timeout=150), daemon=True).start()

        def libera(marca):
            marca(f"kubectl uncordon {no}")
            k("uncordon", no)

        try:
            acoes = [(25, drena)] + ([(25 + espera, libera)] if espera else [])
            carga(nome, fila, 16, 120, acoes=acoes, extra={"replicas": 3, "no": no})
            with open(f"{PASTA}/{nome}-depois.txt", "w", encoding="utf-8") as f:
                f.write(k("get", "pods", "-A", "-o", "wide"))
        finally:
            k("uncordon", no, check=False)  # o nó nunca fica bloqueado, mesmo se algo falhar
        time.sleep(30)


def e54(fila):
    """Rolling update e rollout undo, sem e com preStop."""
    sem_hpa()
    prestop = {"spec": {"template": {"spec": {"terminationGracePeriodSeconds": 30, "containers": [
        {"name": "api", "lifecycle": {"preStop": {"exec": {"command": ["sleep", "5"]}}}}]}}}}
    sem_prestop = {"spec": {"template": {"spec": {"containers": [{"name": "api", "lifecycle": None}]}}}}
    for rotulo, patch in (("sem-prestop", sem_prestop), ("com-prestop", prestop)):
        for rep in (1, 2, 3):
            if os.path.exists(f"{PASTA}/54-{rotulo}-undo-exec{rep}-resumo.json"):
                continue
            k("patch", "deployment", API, "-n", "aps", "--type=strategic", "-p", json.dumps(patch))
            k("set", "image", f"deployment/{API}", "-n", "aps", f"api=aps-sd/{API}:1.1.0")
            k("rollout", "status", f"deployment/{API}", "-n", "aps", "--timeout=200s")
            replicas(3)
            espera_sistema(fila)

            def publica(marca):
                marca("kubectl set image 1.2.0")
                k("set", "image", f"deployment/{API}", "-n", "aps", f"api=aps-sd/{API}:1.2.0")
                k("rollout", "status", f"deployment/{API}", "-n", "aps", "--timeout=200s")
                marca("rollout concluído")

            def desfaz(marca):
                marca("kubectl rollout undo")
                k("rollout", "undo", f"deployment/{API}", "-n", "aps")
                k("rollout", "status", f"deployment/{API}", "-n", "aps", "--timeout=200s")
                marca("rollout concluído")

            carga(f"54-{rotulo}-update-exec{rep}", fila, 16, 70, acoes=[(20, publica)], extra={"replicas": 3, "prestop": rotulo})
            espera_sistema(fila, pausa=5)
            carga(f"54-{rotulo}-undo-exec{rep}", fila, 16, 70, acoes=[(20, desfaz)], extra={"replicas": 3, "prestop": rotulo})
    with open(f"{PASTA}/54-rollout-history.txt", "w", encoding="utf-8") as f:
        f.write(k("rollout", "history", f"deployment/{API}", "-n", "aps"))
    k("patch", "deployment", API, "-n", "aps", "--type=strategic", "-p", json.dumps(sem_prestop))
    k("set", "image", f"deployment/{API}", "-n", "aps", f"api=aps-sd/{API}:1.1.0")
    k("rollout", "status", f"deployment/{API}", "-n", "aps", "--timeout=200s")


def e55(fila):
    """Processamento assíncrono: com fila e sem fila, com a mesma carga."""
    sem_hpa()
    replicas(1)
    for cenario in ("com-fila", "sem-fila"):
        for rep in (1, 2, 3):
            nome = f"55-{cenario}-exec{rep}"
            if os.path.exists(f"{PASTA}/{nome}-resumo.json"):
                continue
            if cenario == "sem-fila":  # sem a conexão, a API avalia o alerta dentro do POST
                espera_sistema(fila, pausa=0)  # a fila precisa zerar antes: sem consumidor, ela nunca esvazia
                k("set", "env", f"deployment/{API}", "-n", "aps", "ConnectionStrings__RabbitMq=")
            k("rollout", "status", f"deployment/{API}", "-n", "aps", "--timeout=200s")
            espera_sistema(fila)
            carga(nome, fila, 32, 60, extra={"cenario": cenario, "replicas": 1})


def restaura(fila):
    k("apply", "-f", "k8s/")
    k("rollout", "restart", f"deployment/{API}", "-n", "aps")
    k("rollout", "status", f"deployment/{API}", "-n", "aps", "--timeout=200s")
    for no in ("k3d-aps-server-0", "k3d-aps-agent-0", "k3d-aps-agent-1"):
        k("uncordon", no, check=False)
    log("cluster restaurado")


def main():
    os.makedirs(PASTA, exist_ok=True)
    pedidos = sys.argv[1:] or ["5.1", "5.2", "5.3", "5.4", "5.5"]
    fila = Fila()
    try:
        for chave, funcao in (("5.1", e51), ("5.2", e52), ("5.3", e53), ("5.4", e54), ("5.5", e55),
                              ("5.1b", e51b), ("5.1g", e51g), ("5.2b", e52b)):
            if chave in pedidos:
                log(f"=== experimento {chave}")
                funcao(fila)
        restaura(fila)
    finally:
        fila.fecha()
    log("fim")


if __name__ == "__main__":
    main()
