FROM python:3.12-slim

ARG SOURCE_COMMIT

RUN test -n "${SOURCE_COMMIT}" \
    && printf '%s\n' "${SOURCE_COMMIT}" | grep -Eq '^[0-9a-f]{40}$'

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    AGENTONOMY_SOURCE_COMMIT=${SOURCE_COMMIT} \
    AGENTONOMY_STATE_DIR=/data \
    AGENTONOMY_PROJECT_SLUG=hechooo-agentonomy-commerce \
    AGENTONOMY_HOST=0.0.0.0 \
    AGENTONOMY_PORT=8080 \
    AGENTONOMY_MERCHANT_PORT=18081

WORKDIR /app

COPY requirements.lock /tmp/requirements.lock
RUN python -m pip install --no-cache-dir --requirement /tmp/requirements.lock

COPY apps/node /app/apps/node
RUN python -m pip install --no-cache-dir --no-deps --editable /app/apps/node

COPY apps/core /app/apps/core
COPY apps/marketplace /app/apps/marketplace
COPY examples /app/examples
COPY agentonomy_commerce /app/agentonomy_commerce
COPY scripts/check_review_container.py /app/scripts/check_review_container.py
COPY scripts/verify_review_api.py /app/scripts/verify_review_api.py
COPY scripts/__init__.py /app/scripts/__init__.py

RUN groupadd --system --gid 10001 agentonomy \
    && useradd --system --uid 10001 --gid 10001 --home-dir /nonexistent \
       --shell /usr/sbin/nologin agentonomy \
    && mkdir -p /data \
    && chown 10001:10001 /data \
    && chmod 0700 /data

VOLUME ["/data"]
EXPOSE 8080
USER 10001:10001

CMD ["python", "-m", "uvicorn", "agentonomy_commerce.api:create_app", "--factory", "--host", "0.0.0.0", "--port", "8080", "--workers", "1"]
