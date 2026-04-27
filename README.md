# MapForge

MapForge is a printable city map wall art generator. It produces high-resolution PNG posters ready to print and frame, along with bonus SVG and DXF vector files for CNC hobbyists and laser cutters.

## Quick Start

### Local Development (Docker Compose)

```bash
cp backend/.env.example backend/.env
# Edit backend/.env and set your API keys

docker-compose up --build
```

The app is available at http://localhost:3000. The backend API runs at http://localhost:8000.

### Local Development (without Docker)

**Backend:**

```bash
cd backend
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env        # then edit .env
uvicorn app.main:app --reload --port 8000
```

**Frontend:**

```bash
cd frontend
npm install
npm run dev
```

## Environment Variables

Copy `backend/.env.example` to `backend/.env` and configure:

| Variable | Required | Description |
|---|---|---|
| `SECRET_KEY` | **Yes** (prod) | JWT signing key — min 32 chars |
| `DATABASE_URL` | **Yes** (prod) | PostgreSQL connection string |
| `MAPTILER_API_KEY` | Recommended | Vector tile API key for coastal cities |
| `STRIPE_SECRET_KEY` | For payments | Stripe live/test secret key |
| `STRIPE_WEBHOOK_SECRET` | For payments | Stripe webhook signing secret |
| `SENTRY_DSN` | Recommended | Sentry error reporting DSN |
| `STORAGE_BACKEND` | No | `local` (default) or `s3` |
| `REDIS_URL` | No | Redis URL for caching/rate limiting |
| `FRONTEND_URL` | No | CORS allowed origin for the frontend |

## Testing

```bash
cd backend
pip install -r requirements.txt
pytest -q --cov=app --cov-report=term-missing
```

## Production Deployment

### Railway (Recommended)

The repo is pre-configured for [Railway](https://railway.app/). The root `Dockerfile` builds both frontend and backend into a single image.

1. Create a new Railway project and connect this repo.
2. Set environment variables in the Railway dashboard (see table above).
3. Provision a Postgres database — Railway auto-sets `DATABASE_URL`.
4. Deploy. Railway uses `railway.toml` for health checks.

### Docker (Standalone)

```bash
# Build the combined image
docker build -t mapforge:latest .

# Run with environment file
docker run -d --name mapforge \
  --env-file .env \
  -p 8000:8000 \
  mapforge:latest
```

### Kubernetes

Manifests are provided in the `k8s/` directory:

```bash
# 1. Edit k8s/secret.yaml with base64-encoded secrets
# 2. Edit k8s/ingress.yaml to set your domain
kubectl apply -f k8s/
```

This deploys 2 replicas with a HorizontalPodAutoscaler (2–10 pods based on CPU/memory).

## Architecture

| Component | Technology |
|---|---|
| Backend | Python 3.12 + FastAPI |
| Frontend | React 19 + Vite |
| Database | PostgreSQL (SQLite for dev) |
| Migrations | Alembic |
| Auth | JWT (python-jose + bcrypt) |
| Payments | Stripe |
| File Storage | Local filesystem or S3-compatible |
| Caching | Redis (optional) |
| Monitoring | Sentry (backend + frontend) |
| Deployment | Railway / Docker / Kubernetes |

## CI/CD

GitHub Actions runs on every push and pull request:

- **Backend**: syntax check + pytest with coverage
- **Frontend**: `npm run build`
- **Docker**: `docker build .` on pushes to `master`

## Security

- Non-root container execution
- CORS restricted to configured origins
- Content Security Policy headers in production
- Rate limiting on search and generate endpoints
- JWT authentication with configurable expiry
- Stripe webhook signature verification
- Production fail-fast checks for required secrets

## License

See [PRODUCT_STORY_BIBLE.md](PRODUCT_STORY_BIBLE.md) for product details.
