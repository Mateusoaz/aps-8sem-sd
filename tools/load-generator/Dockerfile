# Gerador de carga: script Python sem dependências externas, então um estágio só basta
# (não há nada para compilar nem pacotes para instalar).
FROM python:3.12-alpine

WORKDIR /app

# Logs aparecem na hora no "docker compose logs" (sem buffer)
ENV PYTHONUNBUFFERED=1

RUN adduser -D -u 1000 app
COPY generator.py ./
USER app

ENTRYPOINT ["python", "generator.py"]
