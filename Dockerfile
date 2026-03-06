# --- Build stage ---
FROM python:3.12-slim AS builder

WORKDIR /app

# Install build deps for sentence-transformers (C extensions)
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc g++ && \
    rm -rf /var/lib/apt/lists/*

COPY pyproject.toml .
# Install all dependencies into /usr/local
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir .

# Pre-download the embedding model so runtime has no network dependency
RUN python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('all-MiniLM-L6-v2')"

# --- Runtime stage ---
FROM python:3.12-slim AS runtime

WORKDIR /app

# Copy installed packages and binaries from builder
COPY --from=builder /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin
# Copy pre-downloaded model cache
COPY --from=builder /root/.cache /root/.cache

# Copy application code
COPY src/ src/
COPY api/ api/
COPY analyze.py .

# Persistent data directory (mount a volume in production)
RUN mkdir -p data

EXPOSE 8000

CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]
