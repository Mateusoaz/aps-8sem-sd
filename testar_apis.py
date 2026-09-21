import argparse
import json
from datetime import datetime, timezone
from urllib.request import Request, urlopen


def request(method, url, payload=None):
    data = json.dumps(payload).encode() if payload is not None else None
    req = Request(url, data=data, method=method, headers={"Content-Type": "application/json"})
    with urlopen(req, timeout=10) as response:
        body = response.read().decode()
        return json.loads(body) if body else None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--somente-consulta", action="store_true")
    args = parser.parse_args()
    timestamp = datetime.now(timezone.utc).isoformat()

    if not args.somente_consulta:
        samples = [
            ("http://127.0.0.1:3001/api/v1/air-quality/particulate", {
                "stationId": "station-central", "sensorId": "japa-air-01", "areaId": "area-central",
                "pm25": 18.5, "pm10": 27.2, "timestamp": timestamp
            }),
            ("http://127.0.0.1:3002/api/v1/overflow/water-level", {
                "monitoringPointId": "river-central", "sensorId": "japa-overflow-01",
                "waterLevelCm": 82.4, "timestamp": timestamp
            }),
            ("http://127.0.0.1:3003/api/v1/thermal-inversion/temperature-profile", {
                "stationId": "station-central", "surfaceSensorId": "japa-surface-01",
                "upperSensorId": "japa-upper-01", "surfaceTemperatureC": 18.0,
                "upperTemperatureC": 22.5, "timestamp": timestamp
            }),
        ]
        for url, payload in samples:
            print("POST", url, "=>", request("POST", url, payload))

    checks = [
        "http://127.0.0.1:3001/api/v1/air-quality/particulate",
        "http://127.0.0.1:3002/api/v1/overflow/water-level",
        "http://127.0.0.1:3003/api/v1/thermal-inversion/temperature-profile",
    ]
    for url in checks:
        rows = request("GET", url)
        print("GET", url, "=>", len(rows), "registro(s)")


if __name__ == "__main__":
    main()
