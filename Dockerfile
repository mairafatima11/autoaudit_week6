# AutoAudit AI — backend image (FastAPI + CLI)
FROM python:3.12-slim AS base

# semgrep/git are used by the Security/Repository agents when available;
# the app degrades to its offline fallback scanner if they're absent, but
# the real integrations are preferred (see tools/static_analysis.py).
RUN apt-get update \
    && apt-get install -y --no-install-recommends git curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY autoaudit ./autoaudit
COPY README.md prompts.md ./

RUN pip install --no-cache-dir semgrep || echo "semgrep unavailable for this platform — fallback scanner will be used"

ENV AUTOAUDIT_DATA_DIR=/data \
    AUTOAUDIT_LOG_DIR=/logs \
    AUTOAUDIT_MODE=mock \
    PYTHONUNBUFFERED=1

RUN mkdir -p /data /logs

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -fsS http://127.0.0.1:8000/api/health || exit 1

CMD ["uvicorn", "autoaudit.api.app:app", "--host", "0.0.0.0", "--port", "8000"]
