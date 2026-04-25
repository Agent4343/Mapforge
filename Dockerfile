# Stage 1: Build the frontend. The Vite build picks up any VITE_*
# environment variable at compile time; Railway passes those through
# from the service config to `docker build --build-arg …`.
FROM node:22-alpine AS frontend-build

WORKDIR /frontend

# Build-time arguments exposed to Vite.
# VITE_SENTRY_DSN   — browser-side Sentry DSN. Leave unset for dev
#                     and Sentry is a no-op; set in Railway to light
#                     up client error tracking.
# VITE_GIT_SHA      — used as the Sentry release tag so errors are
#                     attributed to a specific deploy; wire Railway's
#                     RAILWAY_GIT_COMMIT_SHA into this.
ARG VITE_SENTRY_DSN=""
ARG VITE_GIT_SHA=""
ENV VITE_SENTRY_DSN=$VITE_SENTRY_DSN
ENV VITE_GIT_SHA=$VITE_GIT_SHA

# Bump FRONTEND_VERSION to bust the npm install layer cache when
# dependencies change without a package-lock change (rare, mostly a
# safety valve for transitive updates).
ARG FRONTEND_VERSION=12

# Copy lockfile + manifest first so the npm install layer is cached
# independently of application source changes.
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund

COPY frontend/ .
RUN npm run build

# Stage 2: Python backend + built frontend
FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    libgeos-dev \
    libproj-dev \
    libcairo2-dev \
    libpango1.0-dev \
    libgdk-pixbuf-2.0-dev \
    build-essential \
    curl \
    fonts-dejavu-core \
    fonts-liberation \
    fonts-freefont-ttf \
    fonts-urw-base35 \
    && rm -rf /var/lib/apt/lists/*

COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/ .

# Copy built frontend into static directory
COPY --from=frontend-build /frontend/dist /app/static

# Run the app as a non-root user. `/tmp/mapforge_storage` is the
# default local file-storage path (see config.STORAGE_LOCAL_PATH);
# chowning it to the runtime user means file writes don't fall over
# on a fresh container. Everything else stays owned by root so a
# write-anywhere bug can't overwrite application code.
RUN useradd --create-home --uid 1000 app \
    && mkdir -p /tmp/mapforge_storage \
    && chown -R app:app /app /tmp/mapforge_storage
USER app

EXPOSE 8000

# Railway runs its own healthcheck (see railway.toml), but this
# HEALTHCHECK lets `docker ps` and any non-Railway orchestrator (our
# docker-compose, local testing) detect a dead process too.
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD curl -fsS "http://127.0.0.1:${PORT:-8000}/health" || exit 1

CMD ["python", "start.py"]
