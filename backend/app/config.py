"""全局配置：pydantic-settings 读取项目根目录 .env / 环境变量。

字段名采用大写风格，与项目其余模块通过 `from app.config import settings` 使用。
"""
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# backend/app/config.py → backend 目录（.env 统一放 backend/.env）
_ROOT = Path(__file__).resolve().parent.parent
_ENV_FILE = _ROOT / ".env"


def _abs_path(value: str) -> str:
    """相对路径锚定到 backend 目录。"""
    p = Path(value)
    if p.is_absolute():
        return value
    return str((_ROOT / p).resolve())


def _abs_db_url(url: str) -> str:
    """sqlite:///./rag.db → sqlite:///<backend 绝对路径>。"""
    for marker in ("sqlite+aiosqlite:///", "sqlite:///"):
        if url.startswith(marker):
            raw = url[len(marker):]
            if Path(raw).is_absolute():
                return url
            return marker + (_ROOT / raw).resolve().as_posix()
    return url


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(_ENV_FILE),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # 应用
    APP_NAME: str = "企业文档智能客服"
    DEBUG: bool = False

    # 数据库
    DATABASE_URL: str = "sqlite:///./rag.db"

    # 向量库
    CHROMA_PERSIST_DIR: str = "./data/chroma_db"
    COLLECTION_NAME: str = "enterprise_rag"

    # 上传存储
    UPLOAD_DIR: str = "./data/uploads"
    MAX_UPLOAD_SIZE_MB: int = 20

    # LLM（OpenAI 兼容接口）
    LLM_API_BASE: str = "https://api.openai.com/v1"
    LLM_API_KEY: str = ""
    LLM_MODEL: str = "gpt-4o-mini"
    LLM_TEMPERATURE: float = 0.2
    LLM_MAX_TOKENS: int = 1024
    LLM_TIMEOUT: float = 60.0

    # Embedding（可独立于 LLM：DeepSeek 官方无 embedding 接口，可指向硅基流动等）
    # 留空则回退使用 LLM_API_BASE / LLM_API_KEY
    EMBEDDING_API_BASE: str = ""
    EMBEDDING_API_KEY: str = ""
    EMBEDDING_MODEL: str = "BAAI/bge-m3"

    # 检索
    RETRIEVAL_TOP_K: int = 10   # 召回候选数
    RERANK_TOP_K: int = 5       # 重排后保留数
    RERANK_ENABLED: bool = False  # 是否启用重排（可选，默认关闭）
    RERANK_MODEL: str = ""      # 专用重排模型（如 BAAI/bge-reranker-v2-m3，同硅基流动平台）；空则回退 LLM 重排
    TOP_K_DEFAULT: int = 5
    SCORE_THRESHOLD: float = 0.15  # 融合分门槛（alpha 融合尺度 0-1）：低于此值的低相关片段不进入上下文
    CHUNK_SIZE: int = 800
    CHUNK_OVERLAP: int = 120
    HYBRID_ALPHA: float = 0.7   # 向量分数权重（1-alpha 为关键词权重）
    RRF_K: int = 60             # RRF 融合常数

    # 联网搜索工具
    TAVILY_API_KEY: str = ""
    TAVILY_SEARCH_URL: str = "https://api.tavily.com/search"

    # 认证（可选，留空放行）
    ADMIN_API_KEY: str = ""
    TOKEN_TTL_HOURS: int = 168  # 登录 token 有效期（小时），默认 7 天

    # CORS：显式列出可信前端来源（不允许 * 与 credentials 同用）
    CORS_ORIGINS: list[str] = ["http://localhost:5173", "http://127.0.0.1:5173"]

    def model_post_init(self, __context) -> None:
        """统一把相对路径转成基于 backend 目录的绝对路径（避免因启动目录不同产生两套数据）。"""
        self.DATABASE_URL = _abs_db_url(self.DATABASE_URL)
        self.CHROMA_PERSIST_DIR = _abs_path(self.CHROMA_PERSIST_DIR)
        self.UPLOAD_DIR = _abs_path(self.UPLOAD_DIR)


settings = Settings()
