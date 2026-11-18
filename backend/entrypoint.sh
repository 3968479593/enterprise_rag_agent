#!/bin/sh
set -e

DATA_DIR="${APP_DATA_DIR:-/app/data}"
mkdir -p "$DATA_DIR"

# 首次启动：把镜像内置的种子知识库注入数据卷，避免新机器上是空库
if [ ! -f "$DATA_DIR/rag.db" ] && [ -f /opt/seed/rag.db ]; then
  echo "[entrypoint] 初始化 rag.db"
  cp /opt/seed/rag.db "$DATA_DIR/rag.db"
fi

if [ ! -d "$DATA_DIR/chroma_db" ] || [ -z "$(ls -A "$DATA_DIR/chroma_db" 2>/dev/null || true)" ]; then
  if [ -d /opt/seed/data/chroma_db ]; then
    echo "[entrypoint] 初始化 Chroma 向量库"
    mkdir -p "$DATA_DIR/chroma_db"
    cp -a /opt/seed/data/chroma_db/. "$DATA_DIR/chroma_db/"
  fi
fi

mkdir -p "$DATA_DIR/uploads"

exec "$@"
