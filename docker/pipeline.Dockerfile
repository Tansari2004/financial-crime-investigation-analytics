FROM python:3.12-slim

WORKDIR /app
COPY pyproject.toml README.md ./
COPY src ./src
COPY pipeline ./pipeline
COPY scripts/verify_banking_full_run.py ./scripts/verify_banking_full_run.py
RUN pip install --no-cache-dir -e ".[orchestration]"

ENV PYTHONPATH=/app/src
ENV DAGSTER_HOME=/app/.dagster
RUN mkdir -p /app/.dagster /app/data/raw

CMD ["dagster", "dev", "-m", "banking_pipeline.orchestration", "-h", "0.0.0.0", "-p", "3000"]
