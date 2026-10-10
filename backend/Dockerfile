FROM python:3.12-slim
WORKDIR /app
RUN pip install --no-cache-dir uv==0.9.7
COPY backend/pyproject.toml backend/uv.lock ./
COPY backend/src ./src
COPY backend/alembic.ini ./
COPY backend/migrations ./migrations
RUN uv sync --frozen --no-dev && groupadd --gid 10001 sentinel && useradd --uid 10001 --gid sentinel sentinel
ENV PATH="/app/.venv/bin:$PATH" PYTHONUNBUFFERED=1
USER sentinel
CMD ["sentinel-api"]
