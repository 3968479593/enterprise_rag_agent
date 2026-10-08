"""注册 / 登录与鉴权：账号密码体系，user / admin 两档角色。

- 注册：普通用户直接注册；管理员需提供注册码（= .env 的 ADMIN_API_KEY），未配置时不可注册管理员。
- 登录：用户名 + 密码 → 签发 token（绑定用户，持久化到 SQLite，重启后登录态仍有效）。
- 鉴权：接口层通过 Authorization: Bearer <token> 携带；未登录 401、越权 403。
- 密码：PBKDF2-SHA256 加盐哈希存储，不保存明文。
"""
import hashlib
import hmac
import re
import secrets
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.config import settings
from app.models.database import get_db
from app.models.orm import AuthToken, User
from app.utils import new_id

router = APIRouter()

_USERNAME_RE = re.compile(r"^[\w\u4e00-\u9fff-]{2,20}$")  # 2-20 位字母数字下划线中文


class RegisterRequest(BaseModel):
    username: str = Field(..., max_length=20, description="用户名")
    password: str = Field(..., min_length=6, max_length=64, description="密码（至少 6 位）")
    invite_code: str = Field("", description="管理员注册码（= ADMIN_API_KEY）；留空注册普通用户")


class LoginRequest(BaseModel):
    username: str = Field(..., max_length=20)
    password: str = Field(..., min_length=1, max_length=64)


class AuthResponse(BaseModel):
    token: str
    role: str
    username: str


# ---------- 密码哈希（PBKDF2，标准库实现，零额外依赖） ----------

_ITERATIONS = 120_000


def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), _ITERATIONS)
    return f"{salt}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        salt, expected = stored.split("$", 1)
        digest = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), _ITERATIONS)
        return hmac.compare_digest(digest.hex(), expected)
    except (ValueError, TypeError):
        return False


# ---------- 注册 / 登录 ----------

@router.post("/register", response_model=AuthResponse, status_code=201)
def register(req: RegisterRequest, db: Session = Depends(get_db)) -> AuthResponse:
    username = req.username.strip()
    if not _USERNAME_RE.match(username):
        raise HTTPException(status_code=400, detail="用户名需为 2-20 位字母、数字、下划线或中文")

    role = "user"
    if req.invite_code.strip():
        expected = settings.ADMIN_API_KEY
        if not expected:
            raise HTTPException(status_code=400, detail="管理员注册码未配置（backend/.env 的 ADMIN_API_KEY）")
        if not hmac.compare_digest(req.invite_code, expected):
            raise HTTPException(status_code=400, detail="管理员注册码不正确")
        role = "admin"

    if db.query(User).filter(User.username == username).first() is not None:
        raise HTTPException(status_code=409, detail="用户名已存在")

    user = User(id=new_id("user"), username=username, password_hash=hash_password(req.password), role=role)
    db.add(user)
    db.commit()
    return _issue_token(db, user)


@router.post("/login", response_model=AuthResponse)
def login(req: LoginRequest, db: Session = Depends(get_db)) -> AuthResponse:
    user = db.query(User).filter(User.username == req.username.strip()).first()
    if user is None or not verify_password(req.password, user.password_hash):
        raise HTTPException(status_code=401, detail="用户名或密码不正确")
    return _issue_token(db, user)


def _issue_token(db: Session, user: User) -> AuthResponse:
    token = secrets.token_hex(16)
    expires_at = datetime.now(timezone.utc) + timedelta(hours=settings.TOKEN_TTL_HOURS)
    db.add(AuthToken(token=token, user_id=user.id, role=user.role, expires_at=expires_at))
    db.commit()
    return AuthResponse(token=token, role=user.role, username=user.username)


@router.post("/logout", status_code=200)
def logout(
    authorization: str | None = Header(default=None, alias="Authorization"),
    db: Session = Depends(get_db),
) -> dict:
    """登出：吊销当前 token（使服务端登录态立即失效）。"""
    if authorization and authorization.startswith("Bearer "):
        token = authorization[7:].strip()
        row = db.get(AuthToken, token)
        if row is not None:
            db.delete(row)
            db.commit()
    return {"success": True}


# ---------- 鉴权依赖 ----------

def _resolve(db: Session, authorization: str | None) -> dict | None:
    """解析 Authorization 头，返回 {user_id, role}；无效返回 None。"""
    if not authorization or not authorization.startswith("Bearer "):
        return None
    row = db.get(AuthToken, authorization[7:].strip())
    if row is None:
        return None
    # 过期校验：SQLite 读回的日期无时区，统一按 UTC 处理；过期时间为空视为无效（旧 token 已在迁移中作废）
    if row.expires_at is None:
        return None
    exp = row.expires_at
    if exp.tzinfo is None:
        exp = exp.replace(tzinfo=timezone.utc)
    if exp <= datetime.now(timezone.utc):
        return None
    return {"user_id": row.user_id, "role": row.role}


def get_current_user(
    authorization: str | None = Header(default=None, alias="Authorization"),
    db: Session = Depends(get_db),
) -> dict:
    """任意已登录角色（user / admin）。"""
    payload = _resolve(db, authorization)
    if payload is None:
        raise HTTPException(
            status_code=401,
            detail="未登录或登录已过期",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return payload


def get_current_admin(
    authorization: str | None = Header(default=None, alias="Authorization"),
    db: Session = Depends(get_db),
) -> dict:
    """仅管理员角色。"""
    payload = _resolve(db, authorization)
    if payload is None:
        raise HTTPException(
            status_code=401,
            detail="未登录或登录已过期",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if payload["role"] != "admin":
        raise HTTPException(status_code=403, detail="需要管理员权限")
    return payload
