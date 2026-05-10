FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN mkdir -p data/raw data/processed ml/artifacts \
    && useradd -r -u 1001 appuser \
    && chown -R appuser:appuser /app

USER appuser

EXPOSE 8000
