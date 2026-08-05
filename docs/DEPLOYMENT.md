# Deployment Guide

## Option A — Docker Compose (recommended)

**Prerequisites:** Docker + Docker Compose v2.

```bash
git clone <this-repo>
cd autoaudit-ai
cp .env.example .env
# edit .env: add GROQ_API_KEY / GEMINI_API_KEY for live mode, or leave
# AUTOAUDIT_MODE=mock to run fully offline with deterministic responses
docker compose up --build
```

- Frontend: `http://localhost:3000`
- API + Swagger docs: `http://localhost:8000` / `http://localhost:8000/docs`

Data persists in two named Docker volumes (`autoaudit_data`,
`autoaudit_logs`) so audit history and the vector store survive container
restarts. To audit a repo from your local filesystem rather than a git URL,
set `LOCAL_REPO_PATH` in `.env` before `docker compose up` — it's bind-mounted
read-only into the API container at `/workspace`.

### Rebuilding after a code change

```bash
docker compose up --build api        # backend only
docker compose up --build frontend   # frontend only
```

### Stopping / resetting

```bash
docker compose down            # stop, keep volumes (history preserved)
docker compose down -v         # stop and wipe all persisted data
```

## Option B — Bare-metal / VM

**Backend:**

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
export AUTOAUDIT_MODE=live
export GROQ_API_KEY=...
export GEMINI_API_KEY=...
export AUTOAUDIT_DATA_DIR=/var/lib/autoaudit/data
export AUTOAUDIT_LOG_DIR=/var/lib/autoaudit/logs
uvicorn autoaudit.api.app:app --host 0.0.0.0 --port 8000 --workers 2
```

Use a process manager (systemd, supervisor) to keep it running; put nginx
or another reverse proxy in front for TLS termination.

**Frontend:**

```bash
cd frontend
npm install
npm run build
# serve dist/ with any static file server, proxying /api/* to the backend
```

## Production environment variables

| Variable | Required | Default | Notes |
|---|---|---|---|
| `AUTOAUDIT_MODE` | No | `mock` | Set to `live` to use real Groq/Gemini calls. |
| `GROQ_API_KEY` | For live mode | — | Security Agent + Fix Agent (precision profile). |
| `GROQ_MODEL` | No | `llama-3.3-70b-versatile` | |
| `GEMINI_API_KEY` | For live mode | — | Quality/Documentation Agent (cheap/bulk profile). |
| `GEMINI_MODEL` | No | `gemini-2.5-flash` | |
| `AUTOAUDIT_DATA_DIR` | No | `./data` | SQLite stores (vector store, audit history, cache). |
| `AUTOAUDIT_LOG_DIR` | No | `./logs` | Per-run JSONL trace logs. |
| `GITHUB_TOKEN` | No | — | Raises the GitHub metadata API's rate limit from 60 to 5000 req/hour. |
| `AUTOAUDIT_API_KEY` | No | — | **Auth placeholder** (see below). Unset = API is open. Set it to require `Authorization: Bearer <key>` on every `/api/*` request except `/api/health`. |

### Auth placeholder

This is deliberately minimal — a single shared key, not a real user/session
system — so the API isn't wide open in any deployment where you bother to
set `AUTOAUDIT_API_KEY`, while keeping local/demo use frictionless by
default. `docker-compose.yml` reads it from `.env` like the other
variables. To swap in real auth (OAuth/JWT/SSO) later, `verify_api_key()`
in `autoaudit/api/auth.py` is the one place that would need to change —
everything else (routers, frontend) is unaffected either way.

```bash
# .env
AUTOAUDIT_API_KEY=some-long-random-string

# frontend requests then need:
curl -H "Authorization: Bearer some-long-random-string" http://localhost:8000/api/audits
```

The bundled frontend does **not** currently have a UI for entering this key
— it's meant for API/CLI-driven deployments or as a base to build a login
screen on top of, not a finished multi-user auth experience.

The frontend has no build-time environment variables in the default
same-origin-via-nginx deployment (see `frontend/nginx.conf`); it always
calls `/api/*` relative to whatever origin serves it.

## Health checks

Both containers expose Docker `HEALTHCHECK`s:

- API: `GET /api/health` → `{"status": "ok"}`
- Frontend: `GET /` returns the SPA shell (200)

`docker compose ps` shows health status; `frontend` waits for `api` to
report healthy before starting (see `depends_on.condition` in
`docker-compose.yml`).

## Scaling notes

- The API's `JobStore` (in-memory job/progress tracking) is per-process —
  running multiple API replicas behind a load balancer would need a shared
  job store (e.g. Redis) instead. Single-instance deployment is the
  supported configuration today.
- SQLite is single-writer; for concurrent heavy write load, consider
  swapping `memory/vector_store.py` and `memory/audit_history.py` to a
  networked database. The interfaces are small and were kept intentionally
  narrow to make this swap straightforward later.
