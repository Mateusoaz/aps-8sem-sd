#!/usr/bin/env python3
"""Carga controlada da APS. Um trabalhador envia uma requisição e espera a resposta antes da próxima."""
from __future__ import annotations

import argparse
import csv
import json
import math
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from urllib.parse import urlsplit
import http.client


def percentile(values: list[float], p: float) -> float:
    """Usa nearest-rank: p95 é o valor na posição ceil(0,95*N), sem interpolação."""
    if not values:
        return 0.0
    ordered = sorted(values)
    return ordered[max(0, math.ceil(p * len(ordered)) - 1)]


def summarize(records: list[dict], elapsed: float) -> dict:
    """Calcula capacidade e cauda de latência; erros entram nos percentis, mas não na vazão OK."""
    latencies = [r["latency_ms"] for r in records]
    oks = sum(200 <= r["status"] < 300 for r in records)
    errors = len(records) - oks
    pods: dict[str, int] = {}
    statuses: dict[str, int] = {}
    versions: dict[str, int] = {}
    for row in records:
        pods[row["pod"] or "(sem X-Pod)"] = pods.get(row["pod"] or "(sem X-Pod)", 0) + 1
        status = str(row["status"] or row["error"] or "sem_resposta")
        statuses[status] = statuses.get(status, 0) + 1
        if row["version"]:
            versions[row["version"]] = versions.get(row["version"], 0) + 1
    return {
        "requests": len(records), "successes": oks, "errors": errors,
        "error_rate_percent": (errors * 100 / len(records)) if records else 0.0,
        "throughput_success_rps": oks / elapsed if elapsed > 0 else 0.0,
        "latency_ms": {"p50": percentile(latencies, .50), "p95": percentile(latencies, .95),
                       "p99": percentile(latencies, .99), "mean": sum(latencies) / len(latencies) if latencies else 0.0},
        "by_pod": pods, "by_status_or_error": statuses, "by_version": versions,
    }


class Sender:
    """Cliente HTTP por thread, com conexão keep-alive reutilizada para reduzir custo artificial."""

    def __init__(self, url: str, method: str, body_template: str | None, timeout: float, headers: dict[str, str]):
        self.url = urlsplit(url)
        self.method, self.body_template, self.timeout, self.headers = method, body_template, timeout, headers
        self._local = threading.local()
        if self.url.scheme not in ("http", "https") or not self.url.hostname:
            raise ValueError("URL precisa começar com http:// ou https://")

    def send(self, worker_id: int) -> dict:
        # Relógio de parede vira timestamp exportável; perf_counter mede duração sem saltos do relógio.
        start_wall = datetime.now().astimezone().isoformat(timespec="milliseconds")
        started = time.perf_counter()
        conn = getattr(self._local, "conn", None)
        try:
            if conn is None:
                # Cada thread guarda sua própria conexão: HTTPConnection não é compartilhado entre workers.
                port = self.url.port or (443 if self.url.scheme == "https" else 80)
                cls = http.client.HTTPSConnection if self.url.scheme == "https" else http.client.HTTPConnection
                conn = cls(self.url.hostname, port, timeout=self.timeout)
                self._local.conn = conn
            path = self.url.path or "/"
            if self.url.query:
                path += "?" + self.url.query
            body = None
            if self.body_template is not None:
                # Substituições deixam cada POST com sensor/leitura diferentes, sem montar JSON inválido.
                sequence = getattr(self._local, "sequence", 0) + 1
                self._local.sequence = sequence
                replacements = {"__WORKER__": str(worker_id), "__SEQ__": str(sequence),
                                "__VALUE__": str(80 + (sequence % 400)),
                                "__TIMESTAMP__": datetime.now().astimezone().isoformat(timespec="milliseconds")}
                rendered = self.body_template
                for token, value in replacements.items():
                    rendered = rendered.replace(token, value)
                body = rendered.encode("utf-8")
            conn.request(self.method, path, body=body, headers=self.headers)
            response = conn.getresponse()
            # Consumir o corpo libera a conexão persistente para a próxima requisição desse worker.
            response.read()
            return {"started_at": start_wall, "epoch": time.time(), "latency_ms": (time.perf_counter() - started) * 1000,
                    "status": response.status, "pod": response.getheader("X-Pod", ""),
                    "version": response.getheader("X-Versao", ""), "error": ""}
        except (OSError, http.client.HTTPException, TimeoutError) as exc:
            # Uma conexão que falhou não é reaproveitada; o próximo ciclo tenta abrir outra.
            if conn is not None:
                conn.close()
            self._local.conn = None
            return {"started_at": start_wall, "epoch": time.time(), "latency_ms": (time.perf_counter() - started) * 1000,
                    "status": 0, "pod": "", "version": "", "error": type(exc).__name__ + ": " + str(exc)}


def run_stage(label: str, concurrency: int, duration: float, ramp: bool, sender: Sender,
              records: list[dict], timeline: list[dict], lock: threading.Lock) -> None:
    # monotonic() é usado para duração; alterações no relógio do Windows não encurtam o ensaio.
    stage_start = time.monotonic()
    deadline = stage_start + duration
    print(f"Etapa {label}: até {concurrency} trabalhadores por {duration:g}s" + (" (rampa)" if ramp else ""))

    def active_count(now: float) -> int:
        # Na rampa, aumenta-se gradualmente o número de loops ativos, mantendo concorrência máxima.
        if not ramp:
            return concurrency
        fraction = min(1.0, max(0.0, (now - stage_start) / duration))
        return max(1, math.ceil(1 + (concurrency - 1) * fraction))

    def worker(worker_id: int) -> None:
        # Laço fechado: um cliente só envia de novo quando a resposta anterior já terminou.
        while time.monotonic() < deadline:
            now = time.monotonic()
            if worker_id >= active_count(now):
                time.sleep(.02)
                continue
            row = sender.send(worker_id + 1)
            row["stage"] = label
            row["active_workers"] = active_count(time.monotonic())
            with lock:
                records.append(row)
        
    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        # Abre até N threads; durante rampa, as acima da carga atual aguardam sem enviar pedidos.
        futures = [pool.submit(worker, i) for i in range(concurrency)]
        next_sample = stage_start
        while time.monotonic() < deadline:
            now_mono = time.monotonic()
            if now_mono >= next_sample:
                with lock:
                    recent = [r for r in records if r["stage"] == label and r["epoch"] >= time.time() - 1]
                # Uma linha por segundo alimenta gráfico e linha do tempo da análise do HPA/falhas.
                summary = summarize(recent, min(1.0, max(.001, now_mono - max(stage_start, next_sample - 1))))
                point = {"time": datetime.now().astimezone().isoformat(timespec="seconds"), "stage": label,
                         "seconds": round(now_mono - stage_start, 3), "active_workers": active_count(now_mono),
                         "requests": summary["requests"], "successes": summary["successes"],
                         "errors": summary["errors"], "throughput_success_rps": round(summary["throughput_success_rps"], 3),
                         "p50_ms": round(summary["latency_ms"]["p50"], 3), "p95_ms": round(summary["latency_ms"]["p95"], 3),
                         "distinct_pods": len({r["pod"] for r in recent if r["pod"]})}
                timeline.append(point)
                print(f"  {point['time']} c={point['active_workers']} ok={point['successes']} err={point['errors']} "
                      f"{point['throughput_success_rps']:.1f} req/s p95={point['p95_ms']:.1f}ms pods={point['distinct_pods']}")
                next_sample += 1
            time.sleep(min(.1, max(.005, next_sample - time.monotonic())))
        for future in futures:
            future.result()


def main() -> None:
    # CLI torna concorrência, duração, timeout e forma da carga repetíveis no relatório.
    parser = argparse.ArgumentParser(description="Carga concorrente via Ingress com CSV por requisição, série temporal e JSON.")
    parser.add_argument("url", help="URL completa da rota; use o Ingress do cluster")
    parser.add_argument("-X", "--method", default="POST", help="verbo HTTP (padrão: POST)")
    parser.add_argument("-b", "--body", default='{"monitoringPointId":"PT-__WORKER__","sensorId":"SEN-__WORKER__-__SEQ__","waterLevelCm":__VALUE__,"timestamp":"__TIMESTAMP__"}', help="corpo JSON; tokens __WORKER__, __SEQ__, __VALUE__, __TIMESTAMP__ são variados por requisição")
    parser.add_argument("-c", "--workers", type=int, default=8, help="concorrência máxima")
    parser.add_argument("-d", "--duration", type=float, default=30, help="duração total ou duração de cada degrau, em segundos")
    parser.add_argument("--rampa", action="store_true", help="cresce de 1 até -c trabalhadores ao longo de -d")
    parser.add_argument("--degraus", help="lista de concorrências, por exemplo 1,2,4,8,16,32,64")
    parser.add_argument("--warmup", type=float, default=5, help="segundos iniciais excluídos dos resumos")
    parser.add_argument("--timeout", type=float, default=5, help="timeout por requisição")
    parser.add_argument("--header", action="append", default=[], help="cabeçalho adicional no formato Nome:Valor")
    parser.add_argument("--prefixo", default="resultados/execucao", help="prefixo dos três arquivos de saída")
    args = parser.parse_args()
    if args.workers < 1 or args.duration <= 0 or args.timeout <= 0 or args.warmup < 0:
        parser.error("workers e duração precisam ser positivos; warmup não pode ser negativo")
    if args.rampa and args.degraus:
        parser.error("use --rampa ou --degraus, não os dois")
    headers = {"User-Agent": "APS-2026-loadgen/1.0", "Accept": "*/*"}
    body = args.body if args.body and args.method.upper() not in ("GET", "HEAD") else None
    if body is not None:
        headers["Content-Type"] = "application/json"
    for item in args.header:
        if ":" not in item:
            parser.error("cabeçalho deve estar no formato Nome:Valor")
        key, value = item.split(":", 1)
        headers[key.strip()] = value.strip()
    sender = Sender(args.url, args.method.upper(), body, args.timeout, headers)
    out_prefix = Path(args.prefixo)
    out_prefix.parent.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    prefix = out_prefix.with_name(f"{out_prefix.name}-{stamp}")
    records: list[dict] = []
    timeline: list[dict] = []
    lock = threading.Lock()
    plan: list[tuple[str, int, float, bool]]
    if args.degraus:
        try:
            steps = [int(x.strip()) for x in args.degraus.split(",")]
        except ValueError:
            parser.error("--degraus deve conter inteiros separados por vírgula")
        if not steps or any(x < 1 for x in steps):
            parser.error("todos os degraus precisam ser positivos")
        plan = [(str(n), n, args.duration, False) for n in steps]
    else:
        plan = [("rampa" if args.rampa else "constante", args.workers, args.duration, args.rampa)]
    for label, concurrency, duration, ramp in plan:
        run_stage(label, concurrency, duration, ramp, sender, records, timeline, lock)

    # Preserva todos os pedidos no CSV; só o resumo exclui o aquecimento inicial do degrau.
    results_by_stage = {}
    for label, concurrency, duration, _ in plan:
        stage_records = [r for r in records if r["stage"] == label]
        first_epoch = min((x["epoch"] for x in stage_records), default=time.time())
        eligible = [r for r in stage_records if r["epoch"] - first_epoch >= args.warmup]
        results_by_stage[label] = {"workers_max": concurrency, "duration_seconds": duration,
                                   "warmup_discarded_seconds": args.warmup,
                                   **summarize(eligible, max(.001, duration - args.warmup))}
    req_path = prefix.with_name(prefix.name + "-requisicoes.csv")
    series_path = prefix.with_name(prefix.name + "-serie.csv")
    json_path = prefix.with_name(prefix.name + "-resumo.json")
    request_fields = ["started_at", "stage", "active_workers", "latency_ms", "status", "pod", "version", "error"]
    with req_path.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=request_fields, extrasaction="ignore")
        writer.writeheader(); writer.writerows(records)
    series_fields = ["time", "stage", "seconds", "active_workers", "requests", "successes", "errors", "throughput_success_rps", "p50_ms", "p95_ms", "distinct_pods"]
    with series_path.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=series_fields)
        writer.writeheader(); writer.writerows(timeline)
    summary = {"url": args.url, "method": args.method.upper(), "generated_at": datetime.now().astimezone().isoformat(),
               "timeout_seconds": args.timeout, "stages": results_by_stage,
               "files": {"requests_csv": str(req_path), "time_series_csv": str(series_path)}}
    json_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print("\nResumo por degrau (métricas excluem o aquecimento):")
    for stage, result in results_by_stage.items():
        lat = result["latency_ms"]
        print(f"  {stage:>10}: {result['throughput_success_rps']:.2f} req/s | p50 {lat['p50']:.1f} | "
              f"p95 {lat['p95']:.1f} | p99 {lat['p99']:.1f} ms | erros {result['error_rate_percent']:.2f}% | pods {result['by_pod']}")
    print(f"\nArquivos: {req_path}\n          {series_path}\n          {json_path}")


if __name__ == "__main__":
    main()
