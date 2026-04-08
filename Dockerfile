FROM python:3.12-slim AS builder

WORKDIR /build
RUN apt-get update && apt-get install -y --no-install-recommends gcc && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

FROM python:3.12-slim

WORKDIR /app

COPY --from=builder /install /usr/local

COPY src/ src/
COPY static/ static/
COPY server.py main.py config.py ./

RUN useradd -r -s /bin/false appuser && \
    mkdir -p /app/cache && chown -R appuser:appuser /app
USER appuser

EXPOSE 8000

CMD ["python", "main.py"]
