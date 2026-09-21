"""Envia novas leituras do sensor térmico e mede cada POST."""
import argparse, json, time
from datetime import datetime, timedelta
from pathlib import Path
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
JSON_FILE = ROOT / "jsons" / "inversao_termica.json"
SUFFIX = "leituras"

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--amostras", type=int, default=1)
    parser.add_argument("--docker", action="store_true", help="opção legada; a API usa PostgreSQL")
    args = parser.parse_args()
    if args.amostras < 1: parser.error("--amostras deve ser maior que zero")
    for indice in range(args.amostras):
        payload = json.loads(JSON_FILE.read_text(encoding="utf-8"))
        payload["dataColetada"] = (datetime.now() + timedelta(microseconds=indice)).strftime("%Y-%m-%d %H:%M:%S.%f")
        sensor = payload["fonte"]["id"]
        body = json.dumps(payload, ensure_ascii=False).encode()
        request = Request(f"http://127.0.0.1:3004/api/v1/sensores/{sensor}/{SUFFIX}", data=body, method="POST", headers={"Content-Type":"application/json", "X-Source-Id":sensor})
        inicio = time.perf_counter()
        with urlopen(request, timeout=5) as response:
            print(f"HTTP {response.status} | {(time.perf_counter()-inicio)*1000:.2f} ms | {response.read().decode()}")
    with urlopen("http://127.0.0.1:3004/api/v1/leituras?limite=1", timeout=5) as response:
        print("Última leitura persistida:", response.read().decode())
if __name__ == "__main__": main()
