"""FastAPI 应用装配：中间件、路由、启动/关闭钩子、鉴权依赖。

启动：python run.py（或 cd backend && uvicorn app.main:app --reload）
文档：http://localhost:8000/docs
"""
import logging
import sys
from pathlib import Path

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.concurrency import run_in_threadpool
from starlette.responses import Response
from starlette.staticfiles import StaticFiles

from app.api import chat, evaluate, feedback, history, upload
from app.api.auth import get_current_admin, get_current_user, router as auth_router
from app.config import settings
from app.models.database import init_db

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger("app.main")

app = FastAPI(title=settings.APP_NAME, debug=settings.DEBUG)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------- 生命周期 ----------

@app.on_event("startup")
async def startup():
    init_db()
    Path(settings.UPLOAD_DIR).mkdir(parents=True, exist_ok=True)
    logger.info("%s 服务已就绪 | database=%s", settings.APP_NAME, settings.DATABASE_URL.split("://", 1)[0])


@app.on_event("shutdown")
async def shutdown():
    logger.info("服务关闭")


# ---------- 静态与路由 ----------

class AuthStaticFiles(StaticFiles):
    """受登录保护的文件下载：/uploads 下的原始文档须携带有效登录 token，未登录返回 401。

    前端仅通过带 Authorization 头的 fetch 访问（本项目前端未直链 /uploads）。
    """

    async def __call__(self, scope, receive, send):
        headers = {k.lower(): v for k, v in scope.get("headers") or []}
        auth = headers.get(b"authorization", b"").decode("latin-1", "ignore")
        token = auth[7:].strip() if auth.startswith("Bearer ") else ""
        if not token or not await run_in_threadpool(self._valid_token, token):
            response = Response("未登录或登录已过期", status_code=401)
            await response(scope, receive, send)
            return
        await super().__call__(scope, receive, send)

    @staticmethod
    def _valid_token(token: str) -> bool:
        from datetime import datetime, timezone

        from app.models.database import SessionLocal
        from app.models.orm import AuthToken

        try:
            with SessionLocal() as db:
                row = db.get(AuthToken, token)
                if row is None or row.expires_at is None:
                    return False
                exp = row.expires_at
                if exp.tzinfo is None:
                    exp = exp.replace(tzinfo=timezone.utc)
                return exp > datetime.now(timezone.utc)
        except Exception:  # noqa: BLE001
            return False


# 上传文件静态访问（data/uploads）：目录不存在时自动创建；仅登录用户可下载
Path(settings.UPLOAD_DIR).mkdir(parents=True, exist_ok=True)
app.mount("/uploads", AuthStaticFiles(directory=settings.UPLOAD_DIR), name="uploads")

# 登录接口公开，无需鉴权
app.include_router(auth_router, prefix="/api/auth", tags=["auth"])

# 权限：文档管理 / 评估 → 管理员；问答 / 历史 → 任意已登录用户
app.include_router(
    upload.router,
    prefix="/api/documents",
    tags=["documents"],
    dependencies=[Depends(get_current_admin)],
)
app.include_router(chat.router, prefix="/api/chat", tags=["chat"], dependencies=[Depends(get_current_user)])
app.include_router(
    history.router,
    prefix="/api/conversations",
    tags=["conversations"],
    dependencies=[Depends(get_current_user)],
)
# 反馈管理：管理员查看全部用户反馈与统计
app.include_router(
    feedback.router,
    prefix="/api/feedback",
    tags=["feedback"],
    dependencies=[Depends(get_current_admin)],
)
app.include_router(
    evaluate.router,
    prefix="/api/evaluation",
    tags=["evaluation"],
    dependencies=[Depends(get_current_admin)],
)


@app.get("/api/health")
async def health_check():
    return {"status": "ok", "service": settings.APP_NAME}
