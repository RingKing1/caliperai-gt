# Sensor Fusion Annotation Platform - Backend Dockerfile

FROM python:3.11-slim AS base

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONFAULTHANDLER=1 \
    PIP_NO_CACHE_DIR=off \
    PIP_DISABLE_PIP_VERSION_CHECK=on

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    curl \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
FROM base AS builder

# Install pip-tools for better dependency management
RUN pip install pip-tools

# Copy requirements file and readme
COPY pyproject.toml README.md ./

# Install dependencies
RUN pip install .

# Production image
FROM base AS production

# Create non-root user
RUN useradd --create-home --shell /bin/bash appuser

# Create uploads directory with proper permissions
RUN mkdir -p /uploads && chown appuser:appuser /uploads

# Copy installed packages from builder
COPY --from=builder /usr/local/lib/python3.11/site-packages /usr/local/lib/python3.11/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

# Copy application code
COPY --chown=appuser:appuser ./app ./app
COPY --chown=appuser:appuser ./alembic ./alembic
COPY --chown=appuser:appuser ./alembic.ini ./alembic.ini
COPY --chown=appuser:appuser ./gunicorn.conf.py ./gunicorn.conf.py
COPY --chown=appuser:appuser ./knowledge_base ./knowledge_base
COPY --chown=appuser:appuser ./scripts/entrypoint.sh /usr/local/bin/entrypoint.sh

# Switch to non-root user
USER appuser

# Optional `alembic upgrade head` (RUN_ALEMBIC_MIGRATIONS=true) then exec CMD
ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]

# Expose port
EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# Default environment variables.
# TIMEOUT is the gunicorn worker timeout: a large dataset ZIP import streams for
# minutes before the worker writes its response, so it must be generous (see
# the comment in gunicorn.conf.py).
ENV WORKERS=4 \
    LOG_LEVEL=info \
    TIMEOUT=7200 \
    GRACEFUL_TIMEOUT=300

# Run with Gunicorn + Uvicorn workers for production
CMD ["gunicorn", "app.main:app", "-c", "gunicorn.conf.py"]


# Development image
FROM base AS development

# Install development dependencies
RUN pip install pip-tools pytest pytest-asyncio pytest-cov httpx black isort mypy ruff

# Copy application code
COPY . .

# Install package in development mode
RUN pip install -e .

# Expose port
EXPOSE 8000

# Run with hot reload
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]
