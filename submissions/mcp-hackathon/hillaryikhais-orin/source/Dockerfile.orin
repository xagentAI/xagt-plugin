FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY REVISION ./REVISION
COPY orin ./orin
ARG GIT_SHA=
ENV ORIN_COMMIT=${GIT_SHA}
EXPOSE 8000
CMD ["uvicorn", "orin.api:app", "--host", "0.0.0.0", "--port", "8000"]