# ── 构建阶段 ──────────────────────────────────────────────────────────────────
FROM python:3.11-slim AS builder

WORKDIR /app

# 先只复制依赖文件，利用 Docker layer 缓存
# 只要 requirements.txt 没变，这层就不会重新跑（pip install 最慢）
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt


# ── 运行阶段 ──────────────────────────────────────────────────────────────────
FROM python:3.11-slim

WORKDIR /app

# 从 builder 复制已安装的包（避免 build 工具进生产镜像）
COPY --from=builder /usr/local/lib/python3.11/site-packages /usr/local/lib/python3.11/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

# 复制项目代码（.dockerignore 会排除 .venv / chroma_db / .env 等）
COPY . .

# 关闭 Python 输出缓冲，日志实时刷出（容器内必须，否则看不到实时 log）
ENV PYTHONUNBUFFERED=1

# FastAPI 服务端口
EXPOSE 8765

# 启动命令
CMD ["uvicorn", "tech_showcase.fastapi_service:app", \
     "--host", "0.0.0.0", \
     "--port", "8765", \
     "--log-level", "info"]
