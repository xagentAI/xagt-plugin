FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY web ./web

ENV HOST=0.0.0.0
ENV PORT=7860

EXPOSE 7860

CMD ["python", "-m", "app.main"]