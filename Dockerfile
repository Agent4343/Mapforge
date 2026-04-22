# Stage 1: Build frontend
FROM node:22-alpine AS frontend-build

WORKDIR /frontend
COPY frontend/package.json ./
RUN npm install
COPY frontend/ .
ARG FRONTEND_VERSION=11
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

EXPOSE 8000

CMD ["python", "start.py"]
