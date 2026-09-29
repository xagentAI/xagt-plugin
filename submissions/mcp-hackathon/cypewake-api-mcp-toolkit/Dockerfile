# MCPForge · API→MCP 全链路工厂
#
# 单进程镜像：uvicorn 启动 demo_app，它同时提供
#   /            可视化四阶段走查页
#   /api/health  健康检查（提交要求的 live 证据）
#   /mcp         MCP 服务端点（streamable-http）
# 因此一个容器 = 一个公网端点，直接满足「deploy and validate the online API」硬门槛。
#
# 构建：docker build -t mcpsforge .
# 运行：docker run -p 8000:8000 -v mcpsforge-data:/data mcpsforge
# 验证：curl http://localhost:8000/api/health

FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8000 \
    MCPFORGE_REGISTRY=/data/registry.json \
    MCPFORGE_USAGE=/data/usage.json

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# 非 root 运行；/data 挂卷后注册表与用量可跨容器重启保留
RUN mkdir -p /data \
    && useradd --create-home --shell /usr/sbin/nologin appuser \
    && chown -R appuser:appuser /app /data
USER appuser

VOLUME ["/data"]

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=4).status == 200 else 1)"

CMD ["sh", "-c", "uvicorn demo_app:app --host 0.0.0.0 --port ${PORT:-8000}"]
