"""混合检索：向量召回（ChromaDB cosine）+ 关键词召回（BM25）+ 归一化融合。

为什么混合：
- 纯向量对专业术语、缩写、编号（如"合同编号 2024-018"）召回不稳定；
- 纯关键词无法处理语义改写；
- 两者分数各自 min-max 归一化后，按 alpha 加权融合，取 Top-K。

性能说明：BM25 基于全量切块的惰性快照构建（缓存），入库/删除后自动失效重建。
数据量极大时，可把 BM25 替换为 ES/OpenSearch 或独立 BM25 服务（见项目目录详解）。
"""
import math
import threading
from collections import Counter
from dataclasses import dataclass
from typing import Optional

from app.config import settings
from app.rag.vector_store import VectorStore
from app.rag.embedding import EmbeddingClient
from app.utils.chunker import tokenize
def reciprocal_rank_fusion(rankings: list[dict[str, float]], k: int = 60) -> dict[str, float]:
    """RRF：融合多路 {id: score} 结果（只依赖排序，对分数绝对值不敏感）。"""
    fused: dict[str, float] = {}
    for ranking in rankings:
        ordered = sorted(ranking.items(), key=lambda kv: kv[1], reverse=True)
        for rank, (cid, _score) in enumerate(ordered, start=1):
            fused[cid] = fused.get(cid, 0.0) + 1.0 / (k + rank)
    return dict(sorted(fused.items(), key=lambda kv: kv[1], reverse=True))


from app.utils.logger import logger


@dataclass
class RetrievedChunk:
    chunk_id: str
    document_id: str
    filename: str
    content: str
    score: float
    vector_score: Optional[float] = None
    keyword_score: Optional[float] = None


class BM25:
    """轻量 BM25（k1=1.5, b=0.75），纯 Python 实现，无额外依赖。"""

    def __init__(self, k1: float = 1.5, b: float = 0.75) -> None:
        self.k1 = k1
        self.b = b
        self.doc_ids: list[str] = []
        self.doc_len: list[int] = []
        self.doc_tf: list[Counter] = []
        self.df: Counter = Counter()
        self.avgdl = 0.0
        self.n_docs = 0

    def fit(self, corpus: list[tuple[str, str]]) -> None:
        self.doc_ids, self.doc_len, self.doc_tf = [], [], []
        self.df = Counter()
        total_len = 0
        for cid, text in corpus:
            tokens = tokenize(text)
            tf = Counter(tokens)
            self.doc_ids.append(cid)
            self.doc_len.append(len(tokens))
            self.doc_tf.append(tf)
            self.df.update(tf.keys())
            total_len += len(tokens)
        self.n_docs = len(self.doc_ids)
        self.avgdl = total_len / self.n_docs if self.n_docs else 0.0

    def score(self, query: str) -> dict[str, float]:
        q_tokens = set(tokenize(query))
        if not q_tokens or self.n_docs == 0:
            return {}
        scores: dict[str, float] = {}
        for i, cid in enumerate(self.doc_ids):
            tf = self.doc_tf[i]
            dl = self.doc_len[i]
            s = 0.0
            for term in q_tokens:
                f = tf.get(term, 0)
                if f == 0:
                    continue
                idf = math.log(1.0 + (self.n_docs - self.df[term] + 0.5) / (self.df[term] + 0.5))
                denom = f + self.k1 * (1.0 - self.b + self.b * dl / self.avgdl)
                s += idf * (f * (self.k1 + 1.0)) / denom
            if s > 0:
                scores[cid] = s
        return scores


class HybridRetriever:
    _MAX_KEYWORD_CORPUS = 20000  # BM25 全量构建的规模上限，超出则自动退化为纯向量

    def __init__(self, use_rrf: bool = False) -> None:
        self.vs = VectorStore.get()
        self.emb = EmbeddingClient()
        self.use_rrf = use_rrf  # True 时用 RRF 融合替代 alpha 加权
        self._corpus_cache: Optional[dict[str, dict]] = None
        self._bm25_cache: Optional[tuple[object, tuple, "BM25"]] = None  # (语料快照对象, where 键, 模型)
        self._lock = threading.Lock()  # 缓存惰性重建的并发保护

    # ---------- 语料快照 ----------

    def invalidate(self) -> None:
        with self._lock:
            self._corpus_cache = None
            self._bm25_cache = None

    def _corpus(self) -> dict[str, dict]:
        """惰性加载全量切块快照，入库/删除后调用 invalidate() 失效。"""
        with self._lock:
            if self._corpus_cache is None:
                res = self.vs.get_all()
                self._corpus_cache = {
                    cid: {"text": doc, "meta": meta}
                    for cid, doc, meta in zip(res["ids"], res["documents"], res["metadatas"])
                }
            return self._corpus_cache

    def _keyword_scores(self, query: str, where: Optional[dict]) -> dict[str, float]:
        corpus = self._corpus()
        where_key = tuple(sorted((where or {}).items()))
        if where:
            corpus = {
                cid: v
                for cid, v in corpus.items()
                if all(v["meta"].get(k) == val for k, val in where_key)
            }
        if len(corpus) > self._MAX_KEYWORD_CORPUS or not corpus:
            return {}
        # BM25 索引按 (语料快照, where 条件) 缓存：同条件重复查询不再全量重建（入库/删除后 invalidate 自动失效）
        cached = self._bm25_cache
        if cached is not None and cached[0] is self._corpus_cache and cached[1] == where_key:
            return cached[2].score(query)
        with self._lock:
            cached = self._bm25_cache
            if cached is not None and cached[0] is self._corpus_cache and cached[1] == where_key:
                return cached[2].score(query)
            bm25 = BM25()
            bm25.fit([(cid, v["text"]) for cid, v in corpus.items()])
            self._bm25_cache = (self._corpus_cache, where_key, bm25)
            return bm25.score(query)

    # ---------- 检索主入口 ----------

    def retrieve(
        self,
        query: str,
        top_k: int = 5,
        where: Optional[dict] = None,
        alpha: Optional[float] = None,
        threshold: Optional[float] = None,
    ) -> list[RetrievedChunk]:
        alpha = settings.HYBRID_ALPHA if alpha is None else alpha
        threshold = settings.SCORE_THRESHOLD if threshold is None else threshold

        # 1) 向量召回（多召回 3 倍，给融合留余量）
        q_vec = self.emb.embed_query(query)
        vec = self.vs.query(q_vec, max(top_k * 3, 10), where=where)
        merged: dict[str, dict] = {}
        for cid, dist, doc, meta in zip(
            vec["ids"][0], vec["distances"][0], vec["documents"][0], vec["metadatas"][0]
        ):
            merged[cid] = {
                "content": doc,
                "meta": meta,
                "vector": max(0.0, 1.0 - float(dist)),
            }

        # 2) 关键词召回（失败不影响主链路）
        try:
            kw = self._keyword_scores(query, where)
        except Exception as exc:  # noqa: BLE001
            logger.warning("关键词检索不可用，退化为纯向量: %s", exc)
            kw = {}
        for cid, kscore in kw.items():
            entry = merged.setdefault(
                cid,
                {"content": self._corpus()[cid]["text"], "meta": self._corpus()[cid]["meta"], "vector": None},
            )
            entry["keyword"] = kscore

        # 3) 融合
        if self.use_rrf and kw:
            results = self._rrf_merge(merged, alpha, threshold, top_k)
        else:
            results = self._alpha_merge(merged, alpha, threshold, top_k)
        return results

    def _alpha_merge(
        self, merged: dict[str, dict], alpha: float, threshold: float, top_k: int
    ) -> list[RetrievedChunk]:
        v_vals = [e["vector"] for e in merged.values() if e.get("vector") is not None]
        k_vals = [e["keyword"] for e in merged.values() if e.get("keyword") is not None]
        v_min, v_max = (min(v_vals), max(v_vals)) if v_vals else (0.0, 1.0)
        k_min, k_max = (min(k_vals), max(k_vals)) if k_vals else (0.0, 1.0)

        def _norm(val: Optional[float], lo: float, hi: float) -> float:
            if val is None:
                return 0.0
            if hi > lo:
                return (val - lo) / (hi - lo)
            return 1.0

        results: list[RetrievedChunk] = []
        for cid, entry in merged.items():
            score = alpha * _norm(entry.get("vector"), v_min, v_max) + (1.0 - alpha) * _norm(
                entry.get("keyword"), k_min, k_max
            )
            if score >= threshold:
                results.append(self._to_chunk(cid, entry, score))
        results.sort(key=lambda r: r.score, reverse=True)
        return results[:top_k]

    def _rrf_merge(
        self, merged: dict[str, dict], alpha: float, threshold: float, top_k: int
    ) -> list[RetrievedChunk]:
        """基于排名做 RRF 融合（对分数绝对值不敏感，更鲁棒）。"""
        vec_rank = {cid: e["vector"] for cid, e in merged.items() if e.get("vector") is not None}
        kw_rank = {cid: e["keyword"] for cid, e in merged.items() if e.get("keyword") is not None}
        fused = reciprocal_rank_fusion([vec_rank, kw_rank], k=settings.RRF_K)
        results = [
            self._to_chunk(cid, merged[cid], fused[cid])
            for cid in fused
            if fused[cid] >= threshold
        ]
        results.sort(key=lambda r: r.score, reverse=True)
        return results[:top_k]

    @staticmethod
    def _to_chunk(cid: str, entry: dict, score: float) -> RetrievedChunk:
        meta = entry["meta"]
        return RetrievedChunk(
            chunk_id=cid,
            document_id=meta.get("document_id", ""),
            filename=meta.get("filename", ""),
            content=entry["content"],
            score=score,
            vector_score=entry.get("vector"),
            keyword_score=entry.get("keyword"),
        )
