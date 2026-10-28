# Multi-stage production container build for Securities Grievance Routing Service
FROM python:3.11-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Install python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application codebase
COPY src/ /app/src/
COPY data/ /app/data/
COPY web/ /app/web/
COPY eval/ /app/eval/
COPY tests/ /app/tests/
COPY locustfile.py /app/
COPY .env.example /app/.env

# Build and verify idempotent vector index
RUN python -m src.retrieval.indexer

EXPOSE 8000

# Declare container healthcheck (Requirement D3)
HEALTHCHECK --interval=15s --timeout=5s --start-period=10s --retries=3 \
  CMD curl -f http://localhost:8000/health || exit 1

CMD ["python", "-m", "src.api.main"]
