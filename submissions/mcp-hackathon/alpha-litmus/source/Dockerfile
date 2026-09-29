FROM python:3.12-slim
ARG ALPHALITMUS_COMMIT=local-dev
LABEL org.opencontainers.image.title="AlphaLitmus" \
      org.opencontainers.image.description="Read-only bounded strategy failure experiments and evidence reconciliation" \
      org.opencontainers.image.version="2.0" \
      org.opencontainers.image.revision="${ALPHALITMUS_COMMIT}"
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    ALPHALITMUS_COMMIT=${ALPHALITMUS_COMMIT} \
    ALPHALITMUS_ENABLE_NEXUS=false
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir --require-hashes -r requirements.txt
COPY app ./app
COPY evidence ./evidence
RUN useradd --create-home --uid 10001 runner
USER runner
EXPOSE 8040
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8040/health', timeout=3).close()"
CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8040"]
