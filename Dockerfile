FROM node:20-alpine AS web
WORKDIR /web
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.11-slim
ENV PYTHONUNBUFFERED=1 UV_COMPILE_BYTECODE=1
RUN pip install --no-cache-dir uv
WORKDIR /app
COPY pyproject.toml uv.lock README.md ./
COPY backend ./backend
RUN uv sync --frozen --no-dev
COPY scripts ./scripts
COPY data/samples ./data/samples
COPY --from=web /web/dist ./frontend/dist
RUN useradd -m app && mkdir -p data/uploads data/processed storage/reports && chown -R app /app
USER app
EXPOSE 8000
HEALTHCHECK CMD python -c "import urllib.request as u; u.urlopen('http://127.0.0.1:8000/api/v1/health')"
CMD [".venv/bin/uvicorn", "backend.app.main:app", "--host", "0.0.0.0", "--port", "8000"]
