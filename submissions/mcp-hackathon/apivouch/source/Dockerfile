FROM python:3.12-slim AS runtime-base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8000 \
    DATABASE_URL=sqlite:////tmp/apivouch.db

WORKDIR /code
COPY backend/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt
COPY backend/app ./app
COPY frontend ./frontend

FROM runtime-base AS test

COPY backend/requirements-dev.txt ./requirements-dev.txt
RUN pip install --no-cache-dir -r requirements-dev.txt
COPY backend ./backend
COPY scripts ./scripts
COPY examples ./examples
COPY pytest.ini ./pytest.ini
COPY deploy ./deploy
RUN DATABASE_URL=sqlite:// PYTHONPATH=/code/backend python -m pytest -q \
    && touch /tmp/apivouch-tests-passed

FROM runtime-base AS runtime

COPY --from=test /tmp/apivouch-tests-passed /tmp/apivouch-tests-passed
RUN useradd --create-home --uid 10001 apivouch
USER 10001

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import json, os, urllib.request; data=json.load(urllib.request.urlopen('http://127.0.0.1:' + os.getenv('PORT', '8000') + '/health', timeout=3)); raise SystemExit(0 if data.get('status') == 'ok' else 1)"
CMD ["sh", "-c", "exec python -m uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --no-access-log --timeout-keep-alive 5 --limit-concurrency 64"]
