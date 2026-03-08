# Platform Dockerfile — Python FastAPI service
FROM python:3.12-slim

# Install uv for fast dependency management
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app

# Copy dependency files first for layer caching
COPY pyproject.toml uv.lock ./

# Install dependencies (frozen from lock file)
RUN uv sync --frozen --no-dev

# Copy application code
COPY core/ core/
COPY tools/ tools/
COPY channels/ channels/
COPY agents/ agents/
COPY config/ config/
COPY main.py .

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')" || exit 1

CMD ["uv", "run", "python", "main.py"]
