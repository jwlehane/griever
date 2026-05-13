FROM python:3.11-slim
WORKDIR /app

# Install dependencies
RUN apt-get update && apt-get install -y curl && rm -rf /var/lib/apt/lists/*
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy source code and database
COPY . .
RUN chmod +x tools/*.sh

# Ensure the database is accessible in the working directory
# The app looks for 'grievance_data.db' in the CWD.
# We stay in /app so it finds /app/grievance_data.db

# Ensure PYTHONPATH includes src so 'from app.core' works from src/main.py
ENV PYTHONPATH=/app/src

# Run from root, targeting src.main
CMD uvicorn src.main:app --host 0.0.0.0 --port ${PORT:-8080}
