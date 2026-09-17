import json
from datetime import datetime
from urllib.request import Request, urlopen

payload = {
    "fonte": {"id": "sensor-ar-01", "tipo": "sensor"},
    "estacao": "Centro",
    "dataColetada": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    "dados": {"mp25": 12.5, "co": 0.8, "no3": 4.2, "temp": 24.0},
}
source_id = payload["fonte"]["id"]
request = Request(
    f"http://api1:3001/api/v1/sensores/{source_id}/leituras",
    data=json.dumps(payload).encode(),
    method="POST",
    headers={"Content-Type": "application/json", "X-Source-Id": source_id},
)
with urlopen(request, timeout=10) as response:
    print(f"HTTP {response.status}: {response.read().decode()}")
