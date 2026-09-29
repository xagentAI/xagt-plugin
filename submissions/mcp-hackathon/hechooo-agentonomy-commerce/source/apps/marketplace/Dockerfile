FROM python:3.11-slim AS builder

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    VIRTUAL_ENV=/opt/venv

RUN python -m venv "${VIRTUAL_ENV}"
ENV PATH="${VIRTUAL_ENV}/bin:${PATH}"

WORKDIR /build
COPY requirements.txt ./
RUN pip install --upgrade pip && pip install --requirement requirements.txt


FROM python:3.11-slim AS runtime

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    VIRTUAL_ENV=/opt/venv \
    PATH="/opt/venv/bin:${PATH}"

RUN groupadd --gid 10001 clink \
    && useradd --uid 10001 --gid clink --create-home --home-dir /home/clink clink

COPY --from=builder /opt/venv /opt/venv

WORKDIR /app
COPY --chown=clink:clink alembic.ini ./
COPY --chown=clink:clink adapters ./adapters
COPY --chown=clink:clink clink_middleware ./clink_middleware
COPY --chown=clink:clink mcp_servers ./mcp_servers
COPY --chown=clink:clink migrations ./migrations
COPY --chown=clink:clink services ./services
COPY --chown=clink:clink shared ./shared
COPY --chown=clink:clink storage ./storage
COPY --chown=clink:clink web ./web
COPY --chown=clink:clink scripts/container-entrypoint.sh ./scripts/container-entrypoint.sh
RUN chmod 0755 /app/scripts/container-entrypoint.sh

USER clink
STOPSIGNAL SIGTERM

ENTRYPOINT ["/app/scripts/container-entrypoint.sh"]
CMD ["api"]
