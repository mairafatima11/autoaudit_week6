# Runbook

Operational procedures for running AutoAudit AI day to day.

## Starting / stopping (Docker)

```bash
docker compose up -d --build      # start
docker compose ps                  # check health
docker compose logs -f api         # tail backend logs
docker compose logs -f frontend    # tail frontend logs
docker compose down                # stop (keeps volumes)
```

## Checking system health

```bash
curl http://localhost:8000/api/health          # expect {"status": "ok"}
curl http://localhost:8000/api/models/available # confirm provider config
```

If `live: false` for a provider you expect to be live, the corresponding
API key env var isn't set or `AUTOAUDIT_MODE` isn't `live` — check
`docker compose config` output or the container's environment.

## An audit run is stuck at "running"

1. `GET /api/audits/{run_id}/events` — check the last event's `actor`/`event`
   to see which agent it's stuck in.
2. `docker compose logs api` — look for a stack trace around that time.
3. Common causes: a provider timing out repeatedly (network egress to
   `api.groq.com` / Gemini's endpoint blocked), or an extremely large repo
   taking a long time to clone/embed (no hard timeout on `git clone` today
   — see Troubleshooting).
4. If it's genuinely wedged, the process-local `JobStore` has no persistence
   — restarting the `api` container clears in-flight (not-yet-persisted)
   jobs. Completed runs already written to `audit_history.db` are
   unaffected.

## Rotating API keys

```bash
# edit .env with new GROQ_API_KEY / GEMINI_API_KEY
docker compose up -d --force-recreate api
```

## Clearing the cache (force full re-embedding)

The incremental-scan cache lives in `AUTOAUDIT_DATA_DIR/cache.db`. To force
a full re-index of a repo (e.g. after changing the embedding function):

```bash
docker compose exec api python -c "
from autoaudit.tools.cache import Cache
from autoaudit.config import load_config
c = Cache(load_config().data_dir / 'cache.db')
c.clear_namespace('embeddings')
"
```

(File-hash records for incremental scanning live in a separate table and
aren't cleared by this — the next run will still re-detect any changed
file correctly; this only forces embeddings to be recomputed rather than
reused from cache.)

## Backing up persisted data

```bash
docker compose exec api tar -C /data -czf - . > autoaudit-data-backup.tar.gz
```

Restore by extracting into the `autoaudit_data` volume before starting the
container, or via `docker compose exec api tar -C /data -xzf -  < backup.tar.gz`.

## Rolling back a bad deploy

```bash
git checkout <previous-tag-or-commit>
docker compose up -d --build
```

Data volumes are untouched by a rollback, so audit history persists across
versions as long as `AuditReport`'s schema stays backward-compatible.
