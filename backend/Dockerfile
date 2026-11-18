FROM python:3.11-slim

# 不在磁盘写 .pyc；日志实时输出到 docker logs；关掉 chromadb 遥测（避免容器内联网探测被拦）
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    CHROMA_TELEMETRY_IMPL=none \
    ANONYMIZED_TELEMETRY=False \
    TZ=Asia/Shanghai

WORKDIR /app

# curl 供 HEALTHCHECK 使用，其余依赖都有预编译 wheel，不需要编译器
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

# 优先用锁清单保证版本可复现；锁清单若在 Linux 上装不通，回退到声明式依赖
COPY requirements.txt requirements.lock.txt ./
RUN pip install --no-cache-dir -i https://pypi.tuna.tsinghua.edu.cn/simple -r requirements.lock.txt \
    || pip install --no-cache-dir -i https://pypi.tuna.tsinghua.edu.cn/simple -r requirements.txt

COPY . .

# 种子数据：把现有知识库（rag.db + Chroma 向量）另存一份，
# 新机器首次启动时由 entrypoint.sh 注入数据卷，避免拿到一个空库
RUN mkdir -p /opt/seed \
    && cp -a /app/data /opt/seed/data \
    && cp -a /app/rag.db /opt/seed/rag.db

COPY entrypoint.sh /usr/local/bin/entrypoint.sh
RUN sed -i 's/\r$//' /usr/local/bin/entrypoint.sh && chmod +x /usr/local/bin/entrypoint.sh

EXPOSE 8001

HEALTHCHECK --interval=30s --timeout=5s --start-period=90s --retries=3 \
    CMD curl -fsS http://127.0.0.1:8001/api/health || exit 1

ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8001"]
