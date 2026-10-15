#!/bin/sh
# Container entrypoint: optionally apply Alembic migrations exactly once at
# boot, then exec the supplied command (gunicorn/uvicorn).
set -e

if [ "${RUN_ALEMBIC_MIGRATIONS:-false}" = "true" ]; then
    echo "[entrypoint] RUN_ALEMBIC_MIGRATIONS=true -> alembic upgrade head"
    alembic upgrade head
fi

exec "$@"
