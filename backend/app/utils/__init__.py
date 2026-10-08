"""工具集：包级工具函数（ID 生成）集中于此，不再单独建文件。"""
import uuid


def new_id(prefix: str) -> str:
    """带前缀的短 UUID，便于日志与数据库索引。"""
    return f"{prefix}_{uuid.uuid4().hex[:16]}"
