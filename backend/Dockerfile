FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    libgeos-dev \
    libproj-dev \
    build-essential \
    curl \
    fonts-dejavu-core \
    fonts-liberation \
    fonts-freefont-ttf \
    fonts-urw-base35 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Run as a non-root user. Writable dirs (local storage, tmp work) are
# chowned; everything else is read-only for the app user so a file-write
# bug can't overwrite the code.
RUN useradd --create-home --uid 1000 app \
    && mkdir -p /tmp/mapforge_storage \
    && chown -R app:app /app /tmp/mapforge_storage
USER app

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD curl -fsS "http://127.0.0.1:${PORT:-8000}/health" || exit 1

CMD ["python", "start.py"]
