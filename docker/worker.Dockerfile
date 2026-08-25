FROM python:3.11-slim

WORKDIR /srv

COPY pyproject.toml ./
COPY app ./app
COPY worker ./worker
COPY pipeline ./pipeline
COPY extract ./extract
COPY common ./common

RUN pip install --no-cache-dir ".[worker]" \
    && playwright install --with-deps chromium

CMD ["arq", "worker.main.WorkerSettings"]
