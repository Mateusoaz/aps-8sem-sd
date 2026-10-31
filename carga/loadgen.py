#!/usr/bin/env python3
"""Gerador de carga da APS (Etapa 4). Usa só a biblioteca padrão do Python.

Simula N clientes em laço fechado: cada trabalhador envia uma requisição, espera
a resposta, anota o resultado e só então envia a próxima. Por isso, N trabalhadores
significam N requisições em andamento ao mesmo tempo.

Exemplos (a partir da raiz do repositório):
  python carga/loadgen.py URL -c 8 -d 20
  python carga/loadgen.py URL --payload ar --degraus 1,2,4,8,16,32,64 -d 30 --prefixo base/post-rep1
  python carga/loadgen.py URL --payload ar -c 32 -d 120 --rampa 60

Cada execução grava em resultados/:
  <prefixo>-requisicoes.csv  uma linha por requisição (matéria-prima)
  <prefixo>-serie.csv        uma linha por segundo, com a hora do relógio
  <prefixo>-resumo.json      resumo por degrau e geral, com o comando exato
"""
import argparse
import collections
import csv
import datetime
import http.client
import json
import os
import random
import socket
import sys
import threading
import time
import urllib.parse

# O gerador só pode apontar para o cluster do próprio grupo (limite ético do Anexo A).
HOSTS_PERMITIDOS = {"localhost", "127.0.0.1", "::1"}


# ---------------------------------------------------------------- corpos das requisições
# Cada corpo varia a estação e o valor, para o sistema não receber dados repetidos.
# A área CARGA separa estas leituras das usadas na consulta da área CENTRO: assim a
# ingestão não deixa a rota de consulta mais lenta a cada teste.

def leitura_ar(rnd):
    estacao = f"EST-CARGA-{rnd.randint(1, 20):02d}"
    return {"stationId": estacao, "sensorId": f"{estacao}-PM", "areaId": "CARGA",
            "pm25": round(rnd.uniform(5, 40), 1), "pm10": round(rnd.uniform(10, 80), 1)}


def leitura_alagamento(rnd):
    ponto = f"PT-CARGA-{rnd.randint(1, 20):02d}"
    return {"monitoringPointId": ponto, "sensorId": f"{ponto}-NIVEL",
            "waterLevelCm": round(rnd.uniform(50, 350), 1)}


def leitura_inversao(rnd):
    estacao = f"EST-TI-CARGA-{rnd.randint(1, 20):02d}"
    superficie = rnd.uniform(14, 24)
    return {"stationId": estacao, "areaId": "CARGA",
            "surfaceSensorId": f"{estacao}-SUP", "upperSensorId": f"{estacao}-ALT",
            "surfaceTemperatureC": round(superficie, 1),
            "upperTemperatureC": round(superficie + rnd.uniform(-4, 3), 1)}


PAYLOADS = {"ar": leitura_ar, "alagamento": leitura_alagamento, "inversao": leitura_inversao}


# ---------------------------------------------------------------- estatística

def percentil(ordenados, p):
    """Percentil pelo método do posto mais próximo; a lista já vem ordenada."""
    if not ordenados:
        return None
    posto = max(1, -(-len(ordenados) * p // 100))  # arredonda a divisão para cima
    return ordenados[int(posto) - 1]


def arredonda(valor):
    return None if valor is None else round(valor, 2)


def resume(registros, duracao_s):
    """Calcula as métricas de um conjunto de requisições. Nenhuma é descartada:
    as que falharam entram nos percentis e na taxa de erro."""
    latencias = sorted(r.latencia_ms for r in registros)
    total = len(registros)
    erros = sum(1 for r in registros if r.erro)
    sucessos = total - erros
    media = sum(latencias) / total if total else None
    return {
        "requisicoes": total,
        "sucessos": sucessos,
        "erros": erros,
        "taxa_erro_pct": round(100 * erros / total, 2) if total else 0.0,
        # Vazão = respostas bem-sucedidas por segundo.
        "vazao_req_s": round(sucessos / duracao_s, 2) if duracao_s else 0.0,
        "latencia_media_ms": arredonda(media),
        "p50_ms": arredonda(percentil(latencias, 50)),
        "p95_ms": arredonda(percentil(latencias, 95)),
        "p99_ms": arredonda(percentil(latencias, 99)),
        "latencia_max_ms": arredonda(latencias[-1] if latencias else None),
        # Lei de Little: trabalhadores = (todas as respostas/s) x latência média.
        # Deve dar perto do número real de trabalhadores; se não der, desconfie da medição.
        "little_trabalhadores": round(total / duracao_s * media / 1000, 2) if total and duracao_s else None,
        "por_pod": dict(sorted(collections.Counter(r.pod or "(sem X-Pod)" for r in registros).items())),
        "por_status": dict(sorted(collections.Counter(str(r.status or "sem_resposta") for r in registros).items())),
        "por_erro": dict(sorted(collections.Counter(r.erro for r in registros if r.erro).items())),
    }


# ---------------------------------------------------------------- plano de carga

class Plano:
    """Diz quantos trabalhadores devem estar ativos em cada instante do teste."""

    def __init__(self, args):
        self.modo = "degraus" if args.degraus else "rampa" if args.rampa else "constante"
        self.degraus = args.degraus
        self.passo_s = args.duration
        self.rampa_s = args.rampa
        self.maximo = max(args.degraus) if args.degraus else args.workers
        self.duracao_s = len(args.degraus) * args.duration if args.degraus else args.duration

    def ativos(self, t):
        if self.modo == "degraus":
            return self.degraus[min(int(t // self.passo_s), len(self.degraus) - 1)]
        if self.modo == "rampa":
            # Começa com 1 e chega ao máximo em rampa_s segundos; depois mantém.
            return min(self.maximo, 1 + int((self.maximo - 1) * t / self.rampa_s))
        return self.maximo

    def fase(self, t):
        """Número do degrau naquele instante (constante e rampa têm uma fase só)."""
        return min(int(t // self.passo_s), len(self.degraus) - 1) if self.modo == "degraus" else 0


# ---------------------------------------------------------------- trabalhador

Registro = collections.namedtuple(
    "Registro", "inicio_epoch trabalhador ativos fase aquecimento latencia_ms status pod versao cache erro")


def classifica(excecao):
    """Traduz a exceção no tipo de erro anotado na requisição."""
    if isinstance(excecao, (socket.timeout, TimeoutError)):
        return "timeout"
    if isinstance(excecao, ConnectionRefusedError):
        return "conexao_recusada"
    if isinstance(excecao, (ConnectionError, http.client.RemoteDisconnected)):
        return "conexao_encerrada"
    return f"outro_{type(excecao).__name__}"


class ConexaoUmEnvio(http.client.HTTPConnection):
    """Envia cabeçalho e corpo no mesmo pacote.

    A http.client normal envia os dois separados, e isso somava cerca de 45 ms a todo
    POST neste cluster (3 ms medidos com curl viravam 48 ms). Esse tempo não pertence ao
    sistema: sem esta classe, a linha de base mediria o próprio gerador.
    """

    def _send_output(self, message_body=None, encode_chunked=False):
        self._buffer.extend((b"", b""))
        mensagem = b"\r\n".join(self._buffer)
        del self._buffer[:]
        self.send(mensagem + (message_body or b""))


class Teste:
    def __init__(self, args, alvo):
        self.args = args
        self.alvo = alvo
        self.plano = Plano(args)
        self.registros = []  # list.append é seguro entre threads no CPython
        self.parar = threading.Event()
        self.inicio_perf = 0.0

    def trabalhador(self, numero):
        args, plano = self.args, self.plano
        rnd = random.Random(args.semente + numero if args.semente is not None else None)
        conexao = None
        cabecalhos = {"Content-Type": "application/json"} if args.metodo == "POST" else {}

        while not self.parar.is_set():
            decorrido = time.perf_counter() - self.inicio_perf
            if decorrido >= plano.duracao_s:
                break
            ativos = plano.ativos(decorrido)
            if numero >= ativos:  # ainda não é a vez deste trabalhador
                time.sleep(0.01)
                continue

            corpo = None
            if args.metodo == "POST":
                corpo = args.body if args.body else json.dumps(PAYLOADS[args.payload](rnd))
                corpo = corpo.encode("utf-8")

            status = pod = versao = cache = None
            erro = ""
            inicio_epoch = time.time()  # hora do relógio, para cruzar com kubectl top
            inicio = time.perf_counter()  # relógio preciso, para a latência
            try:
                # Uma conexão por trabalhador, reaproveitada entre requisições (keep-alive).
                if conexao is None:
                    conexao = ConexaoUmEnvio(self.alvo.hostname, self.alvo.port or 80,
                                             timeout=args.timeout)
                conexao.request(args.metodo, self.caminho(), body=corpo, headers=cabecalhos)
                resposta = conexao.getresponse()
                resposta.read()  # a latência vai até o último byte da resposta
                status = resposta.status
                pod = resposta.getheader("X-Pod")
                versao = resposta.getheader("X-Versao")
                cache = resposta.getheader("X-Cache")
                if status >= 400:
                    erro = f"http_{status}"
            except (OSError, http.client.HTTPException) as excecao:
                erro = classifica(excecao)
                if conexao is not None:
                    conexao.close()
                conexao = None  # a próxima requisição abre uma conexão nova
            latencia_ms = (time.perf_counter() - inicio) * 1000

            no_passo = decorrido % plano.passo_s if plano.modo == "degraus" else decorrido
            self.registros.append(Registro(inicio_epoch, numero, ativos, plano.fase(decorrido),
                                           no_passo < args.aquecimento, latencia_ms,
                                           status, pod, versao, cache, erro))
        if conexao is not None:
            conexao.close()

    def caminho(self):
        caminho = self.alvo.path or "/"
        return f"{caminho}?{self.alvo.query}" if self.alvo.query else caminho

    def progresso(self):
        """Uma vez por segundo: imprime uma linha e guarda a mesma linha na série."""
        print(f"{'hora':8}  {'trab':>4}  {'req/s':>7}  {'erros%':>6}  {'p50':>8}  {'p95':>8}  {'p99':>8}  {'pods':>4}")
        serie = []
        lidos = 0
        anterior = self.inicio_perf
        cpu_anterior = time.process_time()
        proximo = anterior + 1
        while True:
            terminou = self.parar.wait(max(0, proximo - time.perf_counter()))
            agora = time.perf_counter()
            intervalo = max(agora - anterior, 1e-6)
            total = len(self.registros)
            novos = self.registros[lidos:total]
            latencias = sorted(r.latencia_ms for r in novos)
            erros = sum(1 for r in novos if r.erro)
            cpu = time.process_time()
            if terminou and not novos:  # o teste acabou logo depois da última linha
                self.serie = serie
                return
            linha = {
                "hora": datetime.datetime.now().strftime("%H:%M:%S"),
                "epoch": round(time.time(), 3),
                "decorrido_s": round(agora - self.inicio_perf, 1),
                "trabalhadores": self.plano.ativos(min(agora - self.inicio_perf, self.plano.duracao_s - 0.001)),
                "fase": self.plano.fase(min(agora - self.inicio_perf, self.plano.duracao_s - 0.001)),
                "respostas": len(novos),
                "vazao_req_s": round((len(novos) - erros) / intervalo, 1),
                "taxa_erro_pct": round(100 * erros / len(novos), 1) if novos else 0.0,
                "p50_ms": arredonda(percentil(latencias, 50)),
                "p95_ms": arredonda(percentil(latencias, 95)),
                "p99_ms": arredonda(percentil(latencias, 99)),
                "pods_distintos": len({r.pod for r in novos if r.pod}),
                # 100% = um núcleo inteiro. Por causa do GIL, um processo Python usa
                # pouco mais que isso: perto de 100% o gargalo pode ser o próprio gerador.
                "cpu_gerador_pct": round(100 * (cpu - cpu_anterior) / intervalo, 1),
            }
            serie.append(linha)
            ms = lambda v: f"{v:8.1f}" if v is not None else f"{'-':>8}"
            print(f"{linha['hora']:8}  {linha['trabalhadores']:>4}  {linha['vazao_req_s']:>7.1f}  "
                  f"{linha['taxa_erro_pct']:>6.1f}  {ms(linha['p50_ms'])}  {ms(linha['p95_ms'])}  "
                  f"{ms(linha['p99_ms'])}  {linha['pods_distintos']:>4}", flush=True)
            lidos, anterior, cpu_anterior = total, agora, cpu
            proximo += 1
            if terminou:
                self.serie = serie
                return

    def executa(self):
        trabalhadores = [threading.Thread(target=self.trabalhador, args=(i,), daemon=True)
                         for i in range(self.plano.maximo)]
        self.inicio_perf = time.perf_counter()
        for t in trabalhadores:
            t.start()
        relogio = threading.Thread(target=self.progresso, daemon=True)
        relogio.start()
        try:
            for t in trabalhadores:
                while t.is_alive():
                    t.join(0.2)
        except KeyboardInterrupt:  # Ctrl+C: encerra e grava o que já foi medido
            print("\nInterrompido: gravando o que foi medido até aqui.")
            self.parar.set()
            for t in trabalhadores:
                t.join(self.args.timeout + 1)
        self.parar.set()
        relogio.join()
        self.duracao_real_s = time.perf_counter() - self.inicio_perf


# ---------------------------------------------------------------- resumo e arquivos

def monta_resumo(teste, args):
    plano = teste.plano
    uteis = [r for r in teste.registros if not r.aquecimento]
    fases = []
    if plano.modo == "degraus":
        for indice, n in enumerate(plano.degraus):
            selecao = [r for r in uteis if r.fase == indice]
            cpu = [s["cpu_gerador_pct"] for s in teste.serie if s["fase"] == indice]
            fases.append({"trabalhadores": n,
                          "cpu_gerador_pct": round(sum(cpu) / len(cpu), 1) if cpu else None,
                          **resume(selecao, plano.passo_s - args.aquecimento)})
        janela = len(plano.degraus) * (plano.passo_s - args.aquecimento)
    else:
        janela = min(teste.duracao_real_s, plano.duracao_s) - args.aquecimento
    return {
        "comando": " ".join(sys.argv),
        "inicio": datetime.datetime.fromtimestamp(teste.registros[0].inicio_epoch).isoformat(timespec="seconds")
                  if teste.registros else None,
        "url": args.url,
        "metodo": args.metodo,
        "modo": plano.modo,
        "duracao_s": plano.duracao_s,
        "aquecimento_descartado_s": args.aquecimento,
        "timeout_s": args.timeout,
        "requisicoes_no_aquecimento": len(teste.registros) - len(uteis),
        "geral": resume(uteis, janela),
        "degraus": fases,
    }


def grava_arquivos(teste, resumo, prefixo):
    pasta = os.path.dirname(prefixo)
    if pasta:
        os.makedirs(pasta, exist_ok=True)
    with open(f"{prefixo}-requisicoes.csv", "w", newline="", encoding="utf-8") as f:
        saida = csv.writer(f)
        saida.writerow(["inicio", "inicio_epoch", "trabalhador", "trabalhadores_ativos", "fase", "aquecimento",
                        "latencia_ms", "status", "x_pod", "x_versao", "x_cache", "erro"])
        for r in teste.registros:
            hora = datetime.datetime.fromtimestamp(r.inicio_epoch).isoformat(timespec="milliseconds")
            saida.writerow([hora, f"{r.inicio_epoch:.3f}", r.trabalhador, r.ativos, r.fase, int(r.aquecimento),
                            f"{r.latencia_ms:.2f}", r.status or "", r.pod or "", r.versao or "", r.cache or "", r.erro])
    with open(f"{prefixo}-serie.csv", "w", newline="", encoding="utf-8") as f:
        saida = csv.DictWriter(f, fieldnames=list(teste.serie[0]))
        saida.writeheader()
        saida.writerows(teste.serie)
    with open(f"{prefixo}-resumo.json", "w", encoding="utf-8") as f:
        json.dump(resumo, f, ensure_ascii=False, indent=2)


def imprime_resumo(resumo):
    geral = resumo["geral"]
    print(f"\nResumo ({resumo['aquecimento_descartado_s']:g} s de aquecimento descartados)")
    if resumo["degraus"]:
        print(f"{'trab':>4}  {'requisicoes':>11}  {'req/s':>8}  {'p50':>8}  {'p95':>8}  {'p99':>8}  "
              f"{'erros%':>6}  {'little':>6}  {'cpu ger%':>8}")
        for d in resumo["degraus"]:
            if not d["requisicoes"]:
                print(f"{d['trabalhadores']:>4}  sem requisições depois do aquecimento")
                continue
            print(f"{d['trabalhadores']:>4}  {d['requisicoes']:>11}  {d['vazao_req_s']:>8.1f}  {d['p50_ms']:>8.1f}  "
                  f"{d['p95_ms']:>8.1f}  {d['p99_ms']:>8.1f}  {d['taxa_erro_pct']:>6.2f}  "
                  f"{d['little_trabalhadores']:>6.1f}  {d['cpu_gerador_pct'] or 0:>8.1f}")
    else:
        print(f"  requisições: {geral['requisicoes']}   vazão: {geral['vazao_req_s']} req/s   "
              f"erros: {geral['taxa_erro_pct']}%")
        print(f"  p50: {geral['p50_ms']} ms   p95: {geral['p95_ms']} ms   p99: {geral['p99_ms']} ms   "
              f"Lei de Little: {geral['little_trabalhadores']} trabalhadores")
    print("  por pod:   ", geral["por_pod"])
    print("  por código:", geral["por_status"])
    if geral["por_erro"]:
        print("  por erro:  ", geral["por_erro"])
    if any((d["cpu_gerador_pct"] or 0) > 85 for d in resumo["degraus"]):
        print("  ATENÇÃO: o gerador passou de 85% de um núcleo; ele pode ser o gargalo dessa medição.")


# ---------------------------------------------------------------- linha de comando

def lista_de_degraus(texto):
    valores = [int(v) for v in texto.split(",")]
    if not valores or min(valores) < 1:
        raise argparse.ArgumentTypeError("use inteiros positivos, ex.: 1,2,4,8")
    return valores


def le_argumentos():
    parser = argparse.ArgumentParser(description="Gerador de carga em laço fechado da APS (Etapa 4).")
    parser.add_argument("url", help="URL no Ingress local, ex.: http://localhost:8081/flooding/health/live")
    parser.add_argument("-c", "--workers", type=int, default=8, help="trabalhadores (padrão: 8; máximo da rampa)")
    parser.add_argument("-d", "--duration", type=float, default=30,
                        help="segundos do teste; com --degraus, segundos de CADA degrau (padrão: 30)")
    parser.add_argument("-X", "--metodo", choices=["GET", "POST"], help="padrão: POST se houver corpo; senão GET")
    parser.add_argument("--payload", choices=sorted(PAYLOADS), help="gera uma leitura diferente a cada POST")
    parser.add_argument("--body", help="corpo JSON fixo do POST (dados repetidos: prefira --payload)")
    parser.add_argument("--rampa", type=float, metavar="S", help="sobe de 1 a -c trabalhadores em S segundos")
    parser.add_argument("--degraus", type=lista_de_degraus, metavar="1,2,4", help="trabalhadores de cada degrau")
    parser.add_argument("--timeout", type=float, default=10, help="tempo limite por requisição em s (padrão: 10)")
    parser.add_argument("--aquecimento", type=float, metavar="S",
                        help="segundos descartados no início de cada degrau (padrão: 5; na rampa: 0)")
    parser.add_argument("--prefixo", help="nome dos arquivos dentro de resultados/, ex.: base/post-rep1")
    parser.add_argument("--semente", type=int, help="repete a mesma sequência de leituras")
    args = parser.parse_args()

    alvo = urllib.parse.urlsplit(args.url)
    if alvo.scheme != "http" or alvo.hostname not in HOSTS_PERMITIDOS:
        parser.error("o alvo deve ser o Ingress local (http://localhost:8081/...). "
                     "Gerar carga contra serviços de terceiros é ataque de negação de serviço.")
    if args.rampa and args.degraus:
        parser.error("escolha --rampa ou --degraus, não os dois")
    if args.body and args.payload:
        parser.error("escolha --body ou --payload, não os dois")
    if args.metodo is None:
        args.metodo = "POST" if args.body or args.payload else "GET"
    if args.metodo == "POST" and not (args.body or args.payload):
        parser.error("POST precisa de --payload ou --body")
    if args.rampa and args.rampa > args.duration:
        parser.error("a rampa não pode ser maior que a duração (-d)")
    if args.aquecimento is None:
        args.aquecimento = 0 if args.rampa else 5
    if args.aquecimento >= args.duration:
        parser.error(f"-d ({args.duration:g} s) precisa ser maior que o aquecimento ({args.aquecimento:g} s)")
    return args, alvo


def main():
    sys.stdout.reconfigure(errors="replace")  # terminal do Windows nem sempre mostra todo caractere
    args, alvo = le_argumentos()
    prefixo = args.prefixo or datetime.datetime.now().strftime("carga-%Y%m%d-%H%M%S")
    prefixo = os.path.join("resultados", prefixo)

    teste = Teste(args, alvo)
    print(f"{args.metodo} {args.url} | modo {teste.plano.modo} | até {teste.plano.maximo} trabalhadores | "
          f"{teste.plano.duracao_s:g} s | timeout {args.timeout:g} s")
    teste.executa()

    if not teste.registros:
        print("Nenhuma requisição foi feita.")
        return
    resumo = monta_resumo(teste, args)
    imprime_resumo(resumo)
    grava_arquivos(teste, resumo, prefixo)
    print(f"\nArquivos: {prefixo}-requisicoes.csv, -serie.csv e -resumo.json")


if __name__ == "__main__":
    main()
