"""Envia exemplos para todos os sensores e fontes não sensoriais da API v2."""
import json
from datetime import datetime
from urllib.request import Request, urlopen


def send(port, path, payload, source_id=None):
    headers = {"Content-Type": "application/json"}
    if source_id:
        headers["X-Source-Id"] = source_id
    request = Request(
        f"http://127.0.0.1:{port}{path}",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        method="POST",
        headers=headers,
    )
    with urlopen(request, timeout=10) as response:
        print(f"{response.status} {path}: {response.read().decode('utf-8')}")


def main():
    collected_at = datetime.now().astimezone().isoformat(timespec="microseconds")

    # Qualidade do ar: quatro fontes independentes.
    send(3001, "/api/v2/sensores/ar-particulado-01/material-particulado",
         {"dataColetada": collected_at, "localId": "estacao-centro", "mp25": 40.0}, "ar-particulado-01")
    send(3001, "/api/v2/sensores/ar-co-01/monoxido-carbono",
         {"dataColetada": collected_at, "localId": "estacao-centro", "co": 4.2}, "ar-co-01")
    send(3001, "/api/v2/sensores/ar-no2-01/oxidos-nitrogenio",
         {"dataColetada": collected_at, "localId": "estacao-centro", "no2": 85.0}, "ar-no2-01")
    send(3001, "/api/v2/sensores/ar-meteo-01/meteorologia",
         {"dataColetada": collected_at, "localId": "estacao-centro", "temperaturaC": 26.0, "umidadePercentual": 58.0}, "ar-meteo-01")
    send(3001, "/api/v2/boletins",
         {"localId": "estacao-centro", "classificacao": "moderada", "recomendacao": "Acompanhar novas medições", "geradoPor": "operador", "dataReferencia": collected_at})

    # Alagamentos: nível, chuva e vazão, mais uma ocorrência informada por operador.
    send(3002, "/api/v2/sensores/agua-nivel-01/nivel-agua",
         {"dataColetada": collected_at, "localId": "ponte-central", "nivelAguaMetros": 2.2}, "agua-nivel-01")
    send(3002, "/api/v2/sensores/agua-chuva-01/precipitacao",
         {"dataColetada": collected_at, "localId": "ponte-central", "chuvaAcumuladaMm": 18.0}, "agua-chuva-01")
    send(3002, "/api/v2/sensores/agua-vazao-01/vazao",
         {"dataColetada": collected_at, "localId": "ponte-central", "vazaoM3s": 72.0}, "agua-vazao-01")
    send(3002, "/api/v2/ocorrencias",
         {"origem": "operador", "origemId": "defesa-civil-01", "localId": "ponte-central", "descricao": "Via parcialmente alagada", "severidade": "alta", "status": "aberta", "dataOcorrencia": collected_at})

    # Trânsito: medições físicas, resultado derivado de câmera e ocorrência externa.
    send(3003, "/api/v2/sensores/radar-01/velocidades",
         {"dataColetada": collected_at, "localId": "br101-km200", "velocidadeKmh": 92.0}, "radar-01")
    send(3003, "/api/v2/sensores/fluxo-01/fluxo-veicular",
         {"dataColetada": collected_at, "localId": "br101-km200", "quantidadeVeiculos": 480, "ocupacaoPercentual": 67.0, "periodoMinutos": 60}, "fluxo-01")
    send(3003, "/api/v2/sensores/balanca-01/pesagens",
         {"dataColetada": collected_at, "localId": "br101-km200", "pesoKg": 18000.0, "numeroEixos": 4}, "balanca-01")
    send(3003, "/api/v2/cameras/camera-01/reconhecimentos",
         {"dataColetada": collected_at, "localId": "br101-km200", "placa": "ABC1D23", "tipoVeiculo": "automovel", "confianca": 0.97}, "camera-01")
    send(3003, "/api/v2/ocorrencias",
         {"origem": "sistema-externo", "origemId": "central-operacional", "localId": "br101-km200", "descricao": "Faixa interditada para manutenção", "severidade": "media", "status": "aberta", "dataOcorrencia": collected_at})

    # Inversão térmica: três alturas, umidade, vento e diagnóstico automático.
    for sensor_id, height, temperature in (
        ("temp-superficie-01", 2.0, 21.0),
        ("temp-intermediaria-01", 50.0, 24.0),
        ("temp-superior-01", 100.0, 27.0),
    ):
        send(3004, f"/api/v2/sensores/{sensor_id}/temperaturas",
             {"dataColetada": collected_at, "localId": "torre-centro", "alturaMetros": height, "temperaturaC": temperature}, sensor_id)
    send(3004, "/api/v2/sensores/umidade-01/umidade",
         {"dataColetada": collected_at, "localId": "torre-centro", "umidadePercentual": 18.0}, "umidade-01")
    send(3004, "/api/v2/sensores/vento-01/vento",
         {"dataColetada": collected_at, "localId": "torre-centro", "velocidadeKmh": 3.0, "direcaoGraus": 135.0}, "vento-01")


if __name__ == "__main__":
    main()
