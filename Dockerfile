FROM ghcr.io/astral-sh/uv:python3.13-bookworm-slim

WORKDIR /app

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright \
    PATH="/app/.venv/bin:$PATH"

# curl para el healthcheck
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Usuario sin privilegios y directorio para Chromium
RUN groupadd --gid 10001 app \
    && useradd --uid 10001 --gid app --shell /bin/bash --create-home app \
    && mkdir -p /ms-playwright /app \
    && chown -R app:app /ms-playwright /app

# Copiar archivos de dependencias para aprovechar caché de capas
COPY pyproject.toml uv.lock ./

# Instalar dependencias fijadas de ejecución sin herramientas de desarrollo (--no-dev)
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-install-project

# Instalar Chromium y sus bibliotecas del sistema para Playwright durante el build
RUN --mount=type=cache,target=/root/.cache/uv \
    uv run playwright install --with-deps chromium \
    && chmod -R 755 /ms-playwright

# Copiar código de la aplicación
COPY --chown=app:app app/ ./app/

# Sincronizar el proyecto en el entorno virtual
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev

USER app

EXPOSE 8000

# Verificación de salud integrada en el contenedor
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -f http://127.0.0.1:8000/health || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--no-access-log"]
