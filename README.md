# Anomaly Detection System (Bill Debt Load Monitoring)

Enterprise-grade, **deterministic and explainable** anomaly detection for biller debt load monitoring.

## What this repo contains

- `backend/`: FastAPI + Celery backend implementing the 4-layer detection pipeline (DSL → Stats → ML → LLM explain)
- `infra/`: local infrastructure (`docker-compose`) for Postgres + Redis
- `frontend/`: React (Vite) ops panel (Institution Profile + DSL editor + validate + sandbox)

## Quickstart (local)

1. Start infra:

```bash
docker compose -f infra/docker-compose.yml up -d
```

2. Configure backend:

- Copy `backend/env.example` to `backend/env` and adjust values.

3. Install backend deps (from `backend/`):

```bash
python -m venv .venv
./.venv/Scripts/activate
python -m pip install -U pip
python -m pip install -e .
```

4. Run migrations:

```bash
alembic upgrade head
```

5. Run API:

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

6. Run worker:

```bash
celery -A app.workers.celery_app worker -l info
```

7. Run scheduler (Celery beat):

```bash
celery -A app.workers.celery_app beat -l info
```

## Frontend (local)

From `frontend/`:

```bash
npm install
npm run dev
```

Then open the UI at `http://localhost:5173` and set:
- API Base URL: `http://localhost:8000`
- X-Internal-API-Key: value from `backend/env`
- X-Actor-Id: your operator id (required for create/approve actions)


