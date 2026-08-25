FROM python:3.11-slim

WORKDIR /srv

COPY pyproject.toml ./
COPY app ./app
COPY common ./common
COPY extract/models.py ./extract/models.py
COPY extract/__init__.py ./extract/__init__.py

RUN pip install --no-cache-dir ".[api]"

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
