FROM python:3.13-slim
WORKDIR /app
RUN pip install --no-cache-dir uv==0.12.13
COPY pyproject.toml uv.lock ./
COPY source ./source
RUN uv sync --locked --no-dev --no-editable
ENV PATH="/app/.venv/bin:$PATH"
ENV PORT=8000
CMD ["sh", "-c", "uvicorn life_exchange_rate.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
