#!/usr/bin/env python3
"""Gera PNGs para linha de base, comparações e séries temporais do loadgen."""
import argparse
import csv
import json
from pathlib import Path

import matplotlib.pyplot as plt


def from_json(paths: list[Path], mode: str, labels: list[str] | None, output: Path) -> None:
    points = []
    for path_index, path in enumerate(paths):
        data = json.loads(path.read_text(encoding="utf-8"))
        for stage, result in data["stages"].items():
            label = stage if mode == "baseline" else (labels[path_index] if labels else path.stem)
            points.append({"label": label, "sort": result["workers_max"] if mode == "baseline" else path_index,
                           "workers": result["workers_max"], "result": result})
    points.sort(key=lambda p: p["sort"])
    x = list(range(len(points)))
    labels_out = [p["label"] for p in points]
    fig, ax = plt.subplots(figsize=(9, 5.2))
    for metric in ("p50", "p95", "p99"):
        ax.plot(x, [p["result"]["latency_ms"][metric] for p in points], marker="o", label=metric)
    ax.set_ylabel("Latência (ms)")
    ax.set_xlabel("Trabalhadores" if mode == "baseline" else "Cenário")
    ax.set_xticks(x, labels_out)
    ax.grid(True, alpha=.25)
    ax2 = ax.twinx()
    ax2.plot(x, [p["result"]["throughput_success_rps"] for p in points], color="black", marker="s", linestyle="--", label="vazão OK")
    ax2.set_ylabel("Vazão bem-sucedida (req/s)")
    lines, names = ax.get_legend_handles_labels()
    lines2, names2 = ax2.get_legend_handles_labels()
    ax.legend(lines + lines2, names + names2, loc="best")
    ax.set_title("Latência e vazão por nível de carga" if mode == "baseline" else "Comparação de cenários")
    fig.tight_layout()
    output.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output, dpi=160)
    plt.close(fig)


def from_timeline(path: Path, metric: str, output: Path) -> None:
    with path.open(newline="", encoding="utf-8-sig") as stream:
        rows = list(csv.DictReader(stream))
    fig, ax = plt.subplots(figsize=(9, 5.2))
    x = [float(row["seconds"]) for row in rows]
    ax.plot(x, [float(row[metric]) for row in rows], marker=".", label=metric)
    ax.set_xlabel("Tempo desde o início (s)")
    ax.set_ylabel("Latência p95 (ms)" if metric == "p95_ms" else "Vazão OK (req/s)")
    ax.grid(True, alpha=.25)
    ax.legend()
    ax.set_title(f"Série temporal: {path.name}")
    fig.tight_layout()
    output.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output, dpi=160)
    plt.close(fig)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("inputs", nargs="+", type=Path)
    parser.add_argument("--modo", choices=("baseline", "comparacao", "serie"), default="baseline")
    parser.add_argument("--rotulos", help="rótulos dos JSONs no modo comparação, separados por vírgula")
    parser.add_argument("--metrica", choices=("p95_ms", "throughput_success_rps"), default="p95_ms", help="métrica para CSV de série temporal")
    parser.add_argument("--saida", type=Path, default=Path("resultados/grafico.png"))
    args = parser.parse_args()
    if args.modo == "serie":
        if len(args.inputs) != 1:
            parser.error("modo serie aceita exatamente um CSV")
        from_timeline(args.inputs[0], args.metrica, args.saida)
    else:
        labels = args.rotulos.split(",") if args.rotulos else None
        if labels and len(labels) != len(args.inputs):
            parser.error("informe um rótulo para cada arquivo JSON")
        from_json(args.inputs, args.modo, labels, args.saida)
    print(f"Gráfico salvo em {args.saida}")


if __name__ == "__main__":
    main()
