"""检索服务：封装混合检索 + 可选重排，向上层提供统一的检索入口。"""
from typing import Optional

from app.config import settings
from app.rag.reranker import Reranker
from app.rag.retriever import HybridRetriever, RetrievedChunk


class RetrievalService:
    def __init__(self, retriever: Optional[HybridRetriever] = None) -> None:
        self.retriever = retriever or HybridRetriever()
        self.reranker = Reranker()

    def retrieve(
        self,
        query: str,
        top_k: Optional[int] = None,
        where: Optional[dict] = None,
        threshold: Optional[float] = None,
    ) -> list[RetrievedChunk]:
        """返回 top_k 条切块；启用重排时先召回 RETRIEVAL_TOP_K 再精排。"""
        top_k = top_k or settings.TOP_K_DEFAULT
        if self.reranker.enabled:
            candidates = self.retriever.retrieve(
                query, top_k=max(settings.RETRIEVAL_TOP_K, top_k), where=where, threshold=threshold
            )
            return self.reranker.rerank(query, candidates, top_k=min(top_k, settings.RERANK_TOP_K))
        return self.retriever.retrieve(query, top_k=top_k, where=where, threshold=threshold)
