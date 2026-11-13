"""一键启动：后端 (FastAPI :8001) + 前端 (Vite :5173)。

用法：python run.py
"""
import os
import subprocess
import sys

# 关闭 chromadb 遥测（避免 Windows 安全策略拦截 grpc DLL 导致启动失败）
os.environ.setdefault("CHROMA_TELEMETRY_IMPL", "none")
os.environ.setdefault("ANONYMIZED_TELEMETRY", "False")

ROOT = os.path.dirname(os.path.abspath(__file__))

# 后端端口：默认 8001（避开 ai-news-assistant 占用的 8000），可用环境变量 RAG_PORT 覆盖
PORT = os.environ.get("RAG_PORT", "8001")


def resolve_python():
    """优先使用项目虚拟环境，其次系统 Python。"""
    candidates = [
        [os.path.join(ROOT, ".venv", "Scripts", "python.exe")],
        [os.path.join(ROOT, ".venv", "bin", "python")],
        ["py", "-3.11"],
        [sys.executable],
    ]
    for cmd in candidates:
        try:
            subprocess.run(
                cmd + ["-c", "import fastapi, uvicorn"],
                check=True, capture_output=True, timeout=30,
            )
            return cmd
        except Exception:
            continue
    return [sys.executable]


print(f"启动后端 (http://localhost:{PORT}) ...")
backend = subprocess.Popen(
    resolve_python() + ["-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", PORT, "--reload"],
    cwd=os.path.join(ROOT, "backend"),
)

print("启动前端 (http://localhost:5173) ...")
frontend = subprocess.Popen(
    ["npm", "run", "dev"],
    cwd=os.path.join(ROOT, "frontend"),
    shell=True,
)

print()
print(f"后端: http://localhost:{PORT}  (API 文档: http://localhost:{PORT}/docs)")
print("前端: http://localhost:5173")
print("按 Ctrl+C 关闭")
print()

try:
    backend.wait()
    frontend.wait()
except KeyboardInterrupt:
    backend.terminate()
    frontend.terminate()
    print("\n已关闭")
