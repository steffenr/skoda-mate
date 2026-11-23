# Build stage: install the exact dependency versions from uv.lock into a virtualenv.
FROM python:3.13.18-slim-trixie AS build
COPY --from=ghcr.io/astral-sh/uv:0.13.8 /uv /bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never UV_PYTHON=/usr/local/bin/python3.13
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

# Runtime stage: no uv, just the virtualenv and the app; the app runs as uid 10001 (see docker-entrypoint.sh).
FROM python:3.13.18-slim-trixie
RUN useradd --system --uid 10001 --user-group --home-dir /nonexistent --no-create-home --shell /usr/sbin/nologin mate \
    && mkdir -p /data && chown 10001:10001 /data && chmod 700 /data
WORKDIR /app
COPY --from=build /app/.venv /app/.venv
COPY skoda_mate ./skoda_mate
COPY --chmod=755 docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
ENV PATH=/app/.venv/bin:$PATH PYTHONPATH=/app DB_PATH=/data/skoda_mate.db PYTHONUNBUFFERED=1
VOLUME /data
EXPOSE 8080
HEALTHCHECK CMD python -c "import urllib.request as u;u.urlopen('http://localhost:8080/health')"
ENTRYPOINT ["/usr/local/bin/docker-entrypoint.sh"]
CMD ["uvicorn", "--factory", "skoda_mate.web:app", "--host", "0.0.0.0", "--port", "8080"]
