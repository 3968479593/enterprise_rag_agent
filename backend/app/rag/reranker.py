"""可选重排器：对混合检索结果做二次精排。

三种模式（按优先级）：
1. 未启用（RERANK_ENABLED=false，默认）：按已有分数顺序截断返回；
2. 专用重排模型（配置 RERANK_MODEL，如 BAAI/bge-reranker-v2-m3）：
   调用 OpenAI 兼容平台的 /rerank 接口精排，质量最好、延迟低；
3. LLM 重排（RERANK_MODEL 留空）：调用 LLM 逐条打分（0-10），按分数重排。
"""
from typing import Optional

import httpx

from app.config import settings
from app.rag.llm import LLMClient
from app.rag.retriever import RetrievedChunk
from app.utils.logger import logger

_RERANK_PROMPT = """你是检索重排器。请判断以下【问题】与【片段】的相关性，输出 0-10 的整数分数（10 表示完全相关）。
只输出数字。

【问题】
{query}

【片段】
{content}

分数："""


class Reranker:
    def __init__(self, llm: Optional[LLMClient] = None) -> None:
        self.llm = llm or LLMClient()
        self.enabled = settings.RERANK_ENABLED
        self.model = settings.RERANK_MODEL

    def rerank(self, query: str, chunks: list[RetrievedChunk], top_k: int) -> list[RetrievedChunk]:
        if not chunks:
            return []
        if not self.enabled:
            return chunks[:top_k]
        if self.model:
            return self._rerank_api(query, chunks, top_k)
        return self._rerank_llm(query, chunks, top_k)

    # ---------- 模式 2：专用重排模型（/rerank 接口） ----------

    def _rerank_api(self, query: str, chunks: list[RetrievedChunk], top_k: int) -> list[RetrievedChunk]:
        base = (settings.EMBEDDING_API_BASE or settings.LLM_API_BASE).rstrip("/")
        api_key = settings.EMBEDDING_API_KEY or settings.LLM_API_KEY
        try:
            resp = httpx.post(
                f"{base}/rerank",
                json={
                    "model": self.model,
                    "query": query,
                    "documents": [c.content[:1000] for c in chunks],
                },
                headers={"Authorization": f"Bearer {api_key}"} if api_key else {},
                timeout=settings.LLM_TIMEOUT,
            )
            resp.raise_for_status()
            results = sorted(
                resp.json().get("results", []),
                key=lambda r: r.get("relevance_score", 0.0),
                reverse=True,
            )
            out = [chunks[r["index"]] for r in results if 0 <= r.get("index", -1) < len(chunks)]
            logger.info("专用重排完成: %s 条 → %s 条", len(chunks), len(out))
            return out[:top_k]
        except Exception as exc:  # noqa: BLE001
            logger.warning("专用重排模型调用失败，使用原始顺序: %s", exc)
            return chunks[:top_k]

    # ---------- 模式 3：LLM 逐条打分 ----------

    def _rerank_llm(self, query: str, chunks: list[RetrievedChunk], top_k: int) -> list[RetrievedChunk]:
        try:
            scored: list[tuple[float, RetrievedChunk]] = []
            for chunk in chunks:
                content, _ = self.llm.chat(
                    [{"role": "user", "content": _RERANK_PROMPT.format(query=query, content=chunk.content[:500])}],
                    temperature=0.0,
                    max_tokens=4,
                )
                score = self._parse_score(content)
                scored.append((score if score is not None else chunk.score, chunk))
            scored.sort(key=lambda kv: kv[0], reverse=True)
            return [c for _, c in scored][:top_k]
        except Exception as exc:  # noqa: BLE001
            logger.warning("LLM 重排失败，使用原始顺序: %s", exc)
            return chunks[:top_k]

    @staticmethod
    def _parse_score(content: str) -> Optional[float]:
        import re

        match = re.search(r"(\d+(?:\.\d+)?)", content)
        if not match:
            return None
        try:
            return float(match.group(1))
        except ValueError:
            return None
