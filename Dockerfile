FROM python:3.11-slim
WORKDIR /app

# System deps. curl is occasionally useful in container debugging; libpq is
# pulled in transitively by psycopg2-binary so no separate install needed.
RUN apt-get update && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Source. .dockerignore keeps the local DB, venv, and secrets out of the
# image. The app calls init_schema() at startup to create a fresh schema
# (SQLite at /app/grievance_data.db when DATABASE_URL is unset, Postgres
# otherwise).
COPY . .
RUN chmod +x tools/*.sh

ENV PYTHONPATH=/app/src

# Cloud Run injects PORT; fall back to 8080 for local docker run.
CMD uvicorn src.main:app --host 0.0.0.0 --port ${PORT:-8080}
