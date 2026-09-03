FROM python:3.12-slim
WORKDIR /code
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY main.py .
EXPOSE 8001
CMD ["python","-m","uvicorn","main:app","--host","0.0.0.0","--port","8001"]
