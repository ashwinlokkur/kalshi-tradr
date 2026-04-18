FROM python:3.11-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Install runtime system deps. cryptography and asyncpg both ship manylinux
# wheels for 3.11, so no compiler toolchain is needed.
RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates tini \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt ./
RUN pip install -r requirements.txt

COPY pyproject.toml ./
COPY src ./src

# Non-root user for the runtime container.
RUN useradd --system --uid 1001 --create-home kalshi \
    && mkdir -p /app/secrets \
    && chown -R kalshi:kalshi /app
USER kalshi

ENV PYTHONPATH=/app/src

ENTRYPOINT ["tini", "--"]
CMD ["python", "-m", "kalshi_tradr.main"]
