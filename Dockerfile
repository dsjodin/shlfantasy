# --- Bygg frontend ---
FROM node:22-alpine AS frontend
WORKDIR /build
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

# --- Python-runtime ---
FROM python:3.13-slim
WORKDIR /app
ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    DATA_DIR=/data \
    STATIC_DIR=/app/static
COPY backend/pyproject.toml ./
COPY backend/app ./app
RUN pip install .
COPY --from=frontend /build/dist ./static
VOLUME /data
EXPOSE 8000
HEALTHCHECK --interval=60s --timeout=5s CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/status')"
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
