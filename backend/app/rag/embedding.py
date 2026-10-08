"""Embedding 客户端：调用 OpenAI 兼容的 /embeddings 接口。

特性：
- 自动分批（batch_size=32），降低超时与限流概率；
- 内存缓存（MD5 去重），同一文本重复向量化只请求一次；
- 内置指数退避重试（429 / 5xx / 网络抖动）。
"""
import hashlib
import time
from typing import Optional

import httpx

from app.config import settings
from app.utils.logger import logger


class EmbeddingClient:
    def __init__(self) -> None:
        # Embedding 可独立配置；未配置时回退到 LLM 的地址与密钥
        self.base_url = (settings.EMBEDDING_API_BASE or settings.LLM_API_BASE).rstrip("/")
        self.api_key = settings.EMBEDDING_API_KEY or settings.LLM_API_KEY
        self.model = settings.EMBEDDING_MODEL
        self.timeout = settings.LLM_TIMEOUT
        self.batch_size = 32
        self._cache: dict[str, list[float]] = {}

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        """批量向量化，返回与输入等长的向量列表（顺序保持一致）。"""
        results: list[Optional[list[float]]] = [None] * len(texts)
        todo: list[tuple[int, str, str]] = []
        for i, text in enumerate(texts):
            key = hashlib.md5(text.encode("utf-8")).hexdigest()
            if key in self._cache:
                results[i] = self._cache[key]
            else:
                todo.append((i, key, text))

        if not todo:
            return results  # type: ignore[return-value]

        for start in range(0, len(todo), self.batch_size):
            batch = todo[start : start + self.batch_size]
            payload = {"model": self.model, "input": [t for _, _, t in batch]}
            data = self._post("/embeddings", payload)
            for (i, key, _), item in zip(batch, data["data"]):
                vec = item["embedding"]
                self._cache[key] = vec
                results[i] = vec

        return results  # type: ignore[return-value]

    def embed_query(self, text: str) -> list[float]:
        return self.embed_texts([text])[0]

    def _post(self, path: str, payload: dict) -> dict:
        url = f"{self.base_url}{path}"
        headers = {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}
        last_error: Optional[Exception] = None
        for attempt in range(3):
            try:
                resp = httpx.post(url, json=payload, headers=headers, timeout=self.timeout)
                resp.raise_for_status()
                return resp.json()
            except Exception as exc:  # noqa: BLE001
                last_error = exc
                logger.warning("embedding 请求失败(第 %s 次): %s", attempt + 1, exc)
                if attempt < 2:
                    time.sleep(0.5 * (attempt + 1))
        raise RuntimeError(f"Embedding 接口不可用: {last_error}")
