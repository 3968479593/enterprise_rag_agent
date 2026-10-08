"""数据库会话管理：Engine / SessionLocal / 依赖注入 / 建表。

默认 SQLite（零配置可跑）；生产环境把 DATABASE_URL 换成 PostgreSQL/MySQL 即可。
"""
from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, declarative_base, sessionmaker

from app.config import settings
from app.utils.logger import logger

Base = declarative_base()

_IS_SQLITE = settings.DATABASE_URL.startswith("sqlite")

_connect_args = (
    {"check_same_thread": False, "timeout": 30}
    if _IS_SQLITE
    else {}
)

engine = create_engine(
    settings.DATABASE_URL,
    connect_args=_connect_args,
    pool_pre_ping=True,
)

if _IS_SQLITE:
    # SQLite 并发加固：WAL 模式允许读写并行，busy_timeout 降低多请求并发写锁概率
    from sqlalchemy import event

    @event.listens_for(engine, "connect")
    def _set_sqlite_pragma(dbapi_conn, _record):  # noqa: ANN001
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA journal_mode=WAL")
        cur.execute("PRAGMA busy_timeout=30000")
        cur.close()

SessionLocal = sessionmaker(
    bind=engine,
    autoflush=False,
    autocommit=False,
    expire_on_commit=False,
)


def init_db() -> None:
    """确保所有模型已导入后建表（main.py 在 startup 中调用）。"""
    from app.models import orm  # noqa: F401

    Base.metadata.create_all(bind=engine)
    _migrate()
    logger.info("数据库表结构就绪")


def _migrate() -> None:
    """轻量迁移：SQLite 的 create_all 不会给已有表加列，这里补齐新增字段。"""
    from sqlalchemy import inspect, text

    with engine.begin() as conn:
        # conversations.user_id（历史会话归属）
        cols = [c["name"] for c in inspect(conn).get_columns("conversations")]
        if "user_id" not in cols:
            conn.execute(text("ALTER TABLE conversations ADD COLUMN user_id VARCHAR(64)"))
            logger.info("迁移: conversations 新增 user_id 列")
        # auth_tokens.user_id（旧 token 无归属，直接清空，需重新登录）
        cols = [c["name"] for c in inspect(conn).get_columns("auth_tokens")]
        if "user_id" not in cols:
            conn.execute(text("ALTER TABLE auth_tokens ADD COLUMN user_id VARCHAR(64)"))
            conn.execute(text("DELETE FROM auth_tokens"))
            logger.info("迁移: auth_tokens 新增 user_id 列并清空旧令牌")
        # auth_tokens.expires_at（旧 token 无过期时间 = 永久有效，安全起见全部作废，需重新登录）
        cols = [c["name"] for c in inspect(conn).get_columns("auth_tokens")]
        if "expires_at" not in cols:
            conn.execute(text("ALTER TABLE auth_tokens ADD COLUMN expires_at DATETIME"))
            conn.execute(text("DELETE FROM auth_tokens"))
            logger.info("迁移: auth_tokens 新增 expires_at 列并作废旧令牌")
        # messages.feedback（在线回答反馈）
        cols = [c["name"] for c in inspect(conn).get_columns("messages")]
        if "feedback" not in cols:
            conn.execute(text("ALTER TABLE messages ADD COLUMN feedback VARCHAR(16)"))
            logger.info("迁移: messages 新增 feedback 列")
        if "feedback_shared" not in cols:
            conn.execute(text("ALTER TABLE messages ADD COLUMN feedback_shared BOOLEAN NOT NULL DEFAULT 0"))
            logger.info("迁移: messages 新增 feedback_shared 列（用户授权管理员查看）")
        if "feedback_note" not in cols:
            conn.execute(text("ALTER TABLE messages ADD COLUMN feedback_note TEXT"))
            logger.info("迁移: messages 新增 feedback_note 列（反馈意见）")


def get_db() -> Generator[Session, None, None]:
    """FastAPI 依赖：每个请求一个会话，请求结束自动关闭。"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
