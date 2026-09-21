"""Importa registros SQLite antigos pelas APIs, sem modificar os volumes legados."""
import shutil
import sqlite3
import tempfile
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import quote
from urllib.request import Request, urlopen

SOURCES = (
    ("api1", "qualidade_ar.db", "leituras"),
    ("api2", "alagamentos.db", "ocorrencias"),
    ("api3", "transito.db", "eventos"),
    ("api4", "inversao_termica.db", "leituras"),
)


def main():
    failed = False
    for service, filename, endpoint in SOURCES:
        path = Path("/legacy") / service / filename
        if not path.is_file():
            print(f"{service}: banco legado ausente, nada para importar", flush=True)
            continue
        imported = duplicates = 0
        with tempfile.TemporaryDirectory() as directory:
            # SQLite em WAL precisa dos arquivos -wal e -shm em um diretório gravável.
            for suffix in ("", "-wal", "-shm"):
                source = Path(str(path) + suffix)
                if source.is_file():
                    shutil.copy2(source, Path(directory) / source.name)
            with sqlite3.connect(Path(directory) / filename) as db:
                rows = db.execute("SELECT source_id, payload_json FROM ingestoes ORDER BY id")
                for source_id, payload in rows:
                    url = f"http://{service}:300{service[-1]}/api/v1/sensores/{quote(source_id, safe='')}/{endpoint}"
                    request = Request(url, data=payload.encode("utf-8"), method="POST",
                                      headers={"Content-Type": "application/json", "X-Source-Id": source_id})
                    try:
                        with urlopen(request, timeout=15) as response:
                            response.read()
                            if response.status == 201:
                                imported += 1
                            elif response.status == 200:
                                duplicates += 1
                            else:
                                raise RuntimeError(f"HTTP {response.status}")
                    except HTTPError as error:
                        print(f"{service}: erro HTTP {error.code}: {error.read().decode()}", flush=True)
                        failed = True
                        break
        print(f"{service}: {imported} importados, {duplicates} já existentes", flush=True)
    if failed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
