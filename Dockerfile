# Single self-contained image: builds the React frontend, then runs the FastAPI
# backend which also serves the built static assets. No external CDN or cloud ML
# endpoint — matches the local-first / egress-blocked constraint.

# ---- Stage 1: build the frontend ----
FROM node:22-slim AS frontend
WORKDIR /fe
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# ---- Stage 2: backend runtime (Python 3.12 + uv) ----
FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim
WORKDIR /app

# Tesseract = the default local OCR reader; libgl/glib = OpenCV runtime deps.
RUN apt-get update && apt-get install -y --no-install-recommends \
        tesseract-ocr \
        libgl1 \
        libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies first (cached layer independent of app code).
COPY backend/pyproject.toml ./
RUN uv sync --no-dev --no-install-project

# App code + built frontend.
COPY backend/app ./app
COPY --from=frontend /fe/dist ./app/static

ENV PORT=8000
EXPOSE 8000
# Shell form so ${PORT} is expanded (deploy platforms inject their own port).
CMD uv run uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}
