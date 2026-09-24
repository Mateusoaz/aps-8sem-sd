#!/usr/bin/env python3
"""
Gerador de carga das APIs ambientais (APS 2026).

Simula estações e pontos de monitoramento enviando leituras aleatórias, mas realistas,
para as 3 APIs. Os valores evoluem aos poucos (passeio aleatório) e de vez em quando
acontecem "episódios" (poluição, chuva forte, inversão térmica) que disparam os alertas.

Usa só a biblioteca padrão do Python: não precisa de pip install.

Exemplos:
    python generator.py                              # 20 leituras/s até Ctrl+C
    python generator.py --rate 100 --duration 60     # 100 leituras/s por 1 min (6.000 leituras)
    python generator.py --apis flooding --dry-run    # só mostra o que seria enviado
"""
from __future__ import annotations

import argparse
import functools
import http.client
import json
import os
import random
import threading
import time
import urllib.parse
import urllib.request
from concurrent.futures import Future, ThreadPoolExecutor
from datetime import datetime, timezone

AREAS = ["CENTRO", "MOOCA", "PINHEIROS", "SANTANA", "ITAQUERA", "BUTANTA"]

API_NAMES = {"air": "qualidade do ar", "flooding": "alagamento", "thermal": "inversão térmica"}


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def drift(value: float, target: float, volatility: float, low: float, high: float, pull: float = 0.1) -> float:
    """Passeio aleatório com retorno à média: anda uma fração em direção ao alvo, mais um ruído."""
    value += (target - value) * pull + random.gauss(0, volatility)
    return round(min(max(value, low), high), 2)


# ============================ Simuladores de sensores ============================
# Cada simulador guarda o "estado" da estação (valores atuais) e, a cada chamada de
# next_reading(), devolve (api, caminho, corpo JSON) de uma leitura nova.

class AirQualityStation:
    """Estação de qualidade do ar. Episódio de poluição: PM2.5 sobe até ~60 µg/m³."""

    def __init__(self, index: int):
        self.station_id = f"EST-AR-{index:02d}"
        self.area_id = AREAS[(index - 1) % len(AREAS)]
        self.pm25 = random.uniform(8, 18)
        self.co2 = random.uniform(400, 450)
        self.tvoc = random.uniform(100, 300)
        self.temperature = random.uniform(18, 26)
        self.humidity = random.uniform(50, 75)
        self.episode_left = 0  # leituras restantes do episódio de poluição

    def next_reading(self) -> tuple[str, str, dict]:
        if self.episode_left == 0 and random.random() < 0.01:
            self.episode_left = random.randint(10, 40)
        polluted = self.episode_left > 0
        self.episode_left = max(0, self.episode_left - 1)

        kind = random.choices(["particulate", "gases", "environment"], weights=[2, 1, 1])[0]
        base = {"stationId": self.station_id, "areaId": self.area_id, "timestamp": now_iso()}

        if kind == "particulate":
            self.pm25 = drift(self.pm25, 60 if polluted else 12, 2.5, 0, 1000, pull=0.2)
            payload = {**base, "sensorId": f"{self.station_id}-PM", "pm25": self.pm25,
                       "pm10": round(self.pm25 * random.uniform(1.5, 2.2), 2)}
        elif kind == "gases":
            self.co2 = drift(self.co2, 650 if polluted else 420, 8, 0, 50000)
            self.tvoc = drift(self.tvoc, 900 if polluted else 200, 20, 0, 60000)
            payload = {**base, "sensorId": f"{self.station_id}-GAS", "co2": self.co2, "tvoc": self.tvoc}
        else:
            self.temperature = drift(self.temperature, 22, 0.3, -50, 70)
            self.humidity = drift(self.humidity, 65, 1.0, 0, 100)
            payload = {**base, "sensorId": f"{self.station_id}-ENV",
                       "temperatureC": self.temperature, "humidityPercent": self.humidity}

        return "air", f"/api/v1/air-quality/{kind}", payload


class FloodingPoint:
    """Ponto de monitoramento de córrego. Chuva forte: nível sobe na direção de ~380 cm."""

    def __init__(self, index: int):
        self.point_id = f"PT-{index:02d}"
        self.level = random.uniform(50, 120)
        self.rain_left = 0  # leituras restantes da chuva forte

    def next_reading(self) -> tuple[str, str, dict]:
        if self.rain_left == 0 and random.random() < 0.01:
            self.rain_left = random.randint(20, 60)
        raining = self.rain_left > 0
        self.rain_left = max(0, self.rain_left - 1)

        kind = random.choices(["water-level", "rainfall", "flow-rate"], weights=[2, 1, 1])[0]
        base = {"monitoringPointId": self.point_id, "timestamp": now_iso()}

        if kind == "water-level":
            self.level = drift(self.level, 380 if raining else 80, 5, 0, 10000, pull=0.12)
            payload = {**base, "sensorId": f"{self.point_id}-NIVEL", "waterLevelCm": self.level}
        elif kind == "rainfall":
            if raining:
                rain = random.uniform(5, 40)
            else:
                rain = random.uniform(0, 2) if random.random() < 0.2 else 0.0
            payload = {**base, "sensorId": f"{self.point_id}-CHUVA", "rainfallMm": round(rain, 2)}
        else:
            # Vazão acompanha o nível do córrego
            flow = max(0.0, 0.5 + self.level * 0.05 + random.gauss(0, 0.3))
            payload = {**base, "sensorId": f"{self.point_id}-VAZAO", "flowRateM3s": round(flow, 2)}

        return "flooding", f"/api/v1/flooding/{kind}", payload


class ThermalStation:
    """Estação de inversão térmica. Na inversão, o ar de cima fica mais quente que o da superfície."""

    def __init__(self, index: int):
        self.station_id = f"EST-TI-{index:02d}"
        self.area_id = AREAS[(index - 1) % len(AREAS)]
        self.surface = random.uniform(18, 25)
        self.gradient = random.uniform(-4, -1)  # superior - superfície (negativo = normal)
        self.soil = random.uniform(20, 40)
        self.humidity = random.uniform(50, 70)
        self.pressure = random.uniform(1008, 1016)
        self.wind = random.uniform(2, 5)
        self.inversion_left = 0  # leituras restantes da inversão

    def next_reading(self) -> tuple[str, str, dict]:
        if self.inversion_left == 0 and random.random() < 0.01:
            self.inversion_left = random.randint(15, 50)
        inversion = self.inversion_left > 0
        self.inversion_left = max(0, self.inversion_left - 1)

        kind = random.choices(
            ["temperature-profile", "soil-moisture", "air-humidity", "atmospheric-pressure", "wind-speed"],
            weights=[3, 1, 1, 1, 1])[0]
        base = {"stationId": self.station_id, "timestamp": now_iso()}

        if kind == "temperature-profile":
            self.surface = drift(self.surface, 14 if inversion else 22, 0.4, -50, 70)
            self.gradient = drift(self.gradient, 3 if inversion else -3, 0.3, -20, 20, pull=0.25)
            upper = round(min(max(self.surface + self.gradient, -50), 70), 2)
            payload = {**base, "areaId": self.area_id,
                       "surfaceSensorId": f"{self.station_id}-SUP", "upperSensorId": f"{self.station_id}-ALT",
                       "surfaceTemperatureC": self.surface, "upperTemperatureC": upper}
        elif kind == "soil-moisture":
            self.soil = drift(self.soil, 30, 0.5, 0, 100)
            payload = {**base, "sensorId": f"{self.station_id}-SOLO", "soilMoisturePercent": self.soil}
        elif kind == "air-humidity":
            self.humidity = drift(self.humidity, 85 if inversion else 60, 1.5, 0, 100)
            payload = {**base, "sensorId": f"{self.station_id}-UMID", "airHumidityPercent": self.humidity}
        elif kind == "atmospheric-pressure":
            # Inversão costuma vir com alta pressão e vento fraco (ar parado)
            self.pressure = drift(self.pressure, 1022 if inversion else 1013, 0.5, 300, 1100)
            payload = {**base, "sensorId": f"{self.station_id}-PRES", "pressureHpa": self.pressure}
        else:
            self.wind = drift(self.wind, 0.8 if inversion else 3.5, 0.4, 0, 120)
            payload = {**base, "sensorId": f"{self.station_id}-VENTO", "windSpeedMs": self.wind}

        return "thermal", f"/api/v1/thermal-inversion/{kind}", payload


SIMULATORS = {"air": AirQualityStation, "flooding": FloodingPoint, "thermal": ThermalStation}


# ================================ Envio HTTP ================================

class HttpSender:
    """
    Envia POSTs reaproveitando a conexão TCP (keep-alive): uma conexão por thread e por API.
    Abrir uma conexão nova a cada requisição esgota as portas do sistema em testes de carga.
    """

    def __init__(self, timeout: float):
        self.timeout = timeout
        self._local = threading.local()

    def _connection(self, host: str, port: int) -> http.client.HTTPConnection:
        pool = self._local.__dict__.setdefault("pool", {})
        if (host, port) not in pool:
            pool[(host, port)] = http.client.HTTPConnection(host, port, timeout=self.timeout)
        return pool[(host, port)]

    def post(self, url: str, payload: dict) -> tuple[bool, float, str | None]:
        """Devolve (sucesso, latência em ms, mensagem de erro)."""
        parts = urllib.parse.urlsplit(url)
        conn = self._connection(parts.hostname, parts.port or 80)
        start = time.perf_counter()
        try:
            # Corpo em bytes: o http.client envia cabeçalho + corpo num único pacote TCP.
            # Com str ele manda em dois, e o Nagle + delayed ACK somam ~40 ms a cada requisição.
            conn.request("POST", parts.path, body=json.dumps(payload).encode(),
                         headers={"Content-Type": "application/json"})
            response = conn.getresponse()
            body = response.read()
            elapsed = (time.perf_counter() - start) * 1000
            if 200 <= response.status < 300:
                return True, elapsed, None
            return False, elapsed, f"HTTP {response.status} em {parts.path}: {body[:300].decode(errors='replace')}"
        except (OSError, http.client.HTTPException) as ex:
            conn.close()  # descarta a conexão quebrada; a próxima requisição reconecta
            return False, (time.perf_counter() - start) * 1000, f"{type(ex).__name__} em {url}: {ex}"


def wait_until_ready(urls: dict[str, str], timeout_s: float) -> bool:
    """Espera o /health/ready de cada API responder, para não começar mandando em API que ainda está subindo."""
    deadline = time.monotonic() + timeout_s
    pending = dict(urls)
    while pending and time.monotonic() < deadline:
        for api, base in list(pending.items()):
            try:
                with urllib.request.urlopen(f"{base}/health/ready", timeout=3) as resp:
                    if resp.status == 200:
                        print(f"  [ok] {API_NAMES[api]} pronta ({base})")
                        del pending[api]
            except OSError:
                pass
        if pending:
            time.sleep(2)
    for api, base in pending.items():
        print(f"  [falhou] {API_NAMES[api]} não respondeu em {base}/health/ready")
    return not pending


# ================================ Estatísticas ================================

class Stats:
    MAX_ERRORS_SHOWN = 5

    def __init__(self):
        self._lock = threading.Lock()
        self.started = time.perf_counter()
        self.ok = 0
        self.failed = 0
        self.per_api = {api: 0 for api in SIMULATORS}
        self.latency_sum = 0.0
        self._window: list[float] = []  # latências desde o último relatório (para o p95)
        self._errors_shown = 0

    def record(self, api: str, result: tuple[bool, float, str | None]):
        ok, latency_ms, error = result
        with self._lock:
            self.per_api[api] += 1
            self.latency_sum += latency_ms
            self._window.append(latency_ms)
            if ok:
                self.ok += 1
            else:
                self.failed += 1
                if self._errors_shown < self.MAX_ERRORS_SHOWN:
                    self._errors_shown += 1
                    print(f"  ! erro: {error}")
                    if self._errors_shown == self.MAX_ERRORS_SHOWN:
                        print("  ! (próximos erros serão apenas contados)")

    def report_line(self) -> str:
        with self._lock:
            window, self._window = self._window, []
            total = self.ok + self.failed
            elapsed = time.perf_counter() - self.started
            p95 = sorted(window)[int(len(window) * 0.95)] if window else 0
            average = sum(window) / len(window) if window else 0
            apis = " · ".join(f"{API_NAMES[a]} {n}" for a, n in self.per_api.items() if n)
            return (f"[{elapsed:6.0f}s] enviadas {total:>7} | ok {self.ok:>7} | erros {self.failed:>5} | "
                    f"{total / elapsed if elapsed else 0:6.1f}/s | latência média {average:5.1f} ms, p95 {p95:5.1f} ms | {apis}")


# ================================ Loop principal ================================

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Gera leituras aleatórias e envia para as APIs ambientais.")
    parser.add_argument("--rate", type=float, default=20, help="leituras por segundo, somando todas as APIs (padrão: 20)")
    parser.add_argument("--duration", type=float, default=0, help="duração em segundos; 0 = até Ctrl+C (padrão: 0)")
    parser.add_argument("--apis", default="air,flooding,thermal", help="quais APIs alimentar (padrão: air,flooding,thermal)")
    parser.add_argument("--entities", type=int, default=5, help="estações/pontos simulados por API (padrão: 5)")
    parser.add_argument("--workers", type=int, default=20, help="requisições simultâneas (padrão: 20)")
    parser.add_argument("--timeout", type=float, default=10, help="timeout de cada requisição em segundos (padrão: 10)")
    parser.add_argument("--report-every", type=float, default=5, help="intervalo do relatório em segundos (padrão: 5)")
    parser.add_argument("--seed", type=int, help="semente do random, para repetir exatamente a mesma sequência")
    parser.add_argument("--dry-run", action="store_true", help="só imprime as leituras, sem enviar")
    # 127.0.0.1 e não "localhost": no Windows, "localhost" vai por IPv6 e o Docker Desktop
    # adiciona ~40 ms por requisição nesse caminho. No Compose, as variáveis apontam para o nome do serviço.
    parser.add_argument("--air-url", default=os.getenv("AIR_QUALITY_API_URL", "http://127.0.0.1:5001"))
    parser.add_argument("--flooding-url", default=os.getenv("FLOODING_API_URL", "http://127.0.0.1:5002"))
    parser.add_argument("--thermal-url", default=os.getenv("THERMAL_INVERSION_API_URL", "http://127.0.0.1:5003"))
    args = parser.parse_args()

    args.apis = [api.strip() for api in args.apis.split(",") if api.strip()]
    invalid = [api for api in args.apis if api not in SIMULATORS]
    if invalid:
        parser.error(f"API desconhecida: {', '.join(invalid)} (use: {', '.join(SIMULATORS)})")
    if args.rate <= 0:
        parser.error("--rate precisa ser maior que zero")
    return args


def main():
    args = parse_args()
    if args.seed is not None:
        random.seed(args.seed)

    urls = {"air": args.air_url, "flooding": args.flooding_url, "thermal": args.thermal_url}
    urls = {api: urls[api].rstrip("/") for api in args.apis}
    entities = [SIMULATORS[api](i) for api in args.apis for i in range(1, args.entities + 1)]

    duration = f"{args.duration:.0f}s" if args.duration else "até Ctrl+C"
    print(f"Gerador de carga: {args.rate:g} leituras/s, {duration}, "
          f"{len(entities)} estações/pontos ({', '.join(API_NAMES[a] for a in args.apis)})")

    if not args.dry_run:
        print("Aguardando as APIs ficarem prontas...")
        if not wait_until_ready(urls, timeout_s=60):
            raise SystemExit("Abortado: alguma API não está pronta. Ela está rodando? (docker compose ps)")

    stats = Stats()
    sender = HttpSender(args.timeout)
    # Limita as requisições "em voo": se a API ficar lenta, o gerador espera em vez de acumular memória
    in_flight = threading.BoundedSemaphore(args.workers * 2)
    stop_reporting = threading.Event()

    def on_done(api: str, future: Future):
        stats.record(api, future.result())
        in_flight.release()

    def reporter():
        while not stop_reporting.wait(args.report_every):
            print(stats.report_line())

    if not args.dry_run:
        threading.Thread(target=reporter, daemon=True).start()

    interval = 1.0 / args.rate
    start = time.perf_counter()
    deadline = start + args.duration if args.duration else None
    next_at = start

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        try:
            while deadline is None or time.perf_counter() < deadline:
                api, path, payload = random.choice(entities).next_reading()

                if args.dry_run:
                    print(f"POST {urls[api]}{path} {json.dumps(payload, ensure_ascii=False)}")
                else:
                    in_flight.acquire()
                    future = pool.submit(sender.post, urls[api] + path, payload)
                    future.add_done_callback(functools.partial(on_done, api))

                # Ritmo constante: agenda a próxima leitura; se atrasou mais de 1 s, não tenta "compensar"
                next_at += interval
                delay = next_at - time.perf_counter()
                if delay > 0:
                    time.sleep(delay)
                elif delay < -1:
                    next_at = time.perf_counter()
        except KeyboardInterrupt:
            print("\nInterrompido. Esperando as requisições em andamento terminarem...")

    stop_reporting.set()
    if not args.dry_run:
        print(stats.report_line())
        total = stats.ok + stats.failed
        print(f"Fim: {total} leituras enviadas, {stats.ok} com sucesso, {stats.failed} com erro. "
              f"Latência média geral: {stats.latency_sum / total if total else 0:.1f} ms.")


if __name__ == "__main__":
    main()
