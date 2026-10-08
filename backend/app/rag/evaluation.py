"""评估服务：检索质量 + 生成质量双层指标。

检索层（无需 LLM，可离线计算）：
- hit_rate@k / mrr@k / precision@k / recall@k（标准答案 token 重叠代理指标）

生成层（需要 LLM）：
- faithfulness    ：答案是否完全由检索上下文支撑（0-1，防幻觉）
- answer_relevancy：答案是否切题（0-1）

任何 LLM 判分失败/未配置时该指标记为 None 并从聚合中剔除。
"""
import re
import time
from typing import Optional

from app.rag.llm import LLMClient
from app.rag.qa import QAService
from app.rag.retrieval import RetrievalService
from app.utils.chunker import tokenize
from app.utils.logger import logger

_HIT_OVERLAP = 0.3  # 显著重叠阈值

_FAITHFULNESS_PROMPT = """阅读以下【答案】与【参考上下文】，判断答案是否完全由参考上下文支持（没有编造/幻觉）。
评分标准：0=完全虚构，5=完全由上下文支持。只输出一个 0-5 的整数或小数。

【参考上下文】
{context}

【答案】
{answer}

分数："""

_RELEVANCY_PROMPT = """判断以下【答案】是否切题回答了【问题】（考虑完整性、相关性与有用性）。
评分标准：0=完全跑题，5=完整切题。只输出一个 0-5 的整数或小数。

【问题】
{question}

【答案】
{answer}

分数："""


def _mean(values: list[float]) -> Optional[float]:
    return round(sum(values) / len(values), 4) if values else None


def overlap_ratio(ground_truth: str, text: str) -> float:
    """标准答案 token 被文本覆盖的比例。"""
    if not ground_truth:
        return 0.0
    g = set(tokenize(ground_truth))
    if not g:
        return 0.0
    t = set(tokenize(text))
    return len(g & t) / len(g)


class EvaluationService:
    def __init__(self) -> None:
        self.retrieval = RetrievalService()
        self.llm = LLMClient()
        self.qa = QAService()

    def run(self, questions: list[dict], top_k: int = 5) -> tuple[dict, list[dict]]:
        hits: list[float] = []
        mrrs: list[float] = []
        precisions: list[float] = []
        recalls: list[float] = []
        faiths: list[float] = []
        relevancies: list[float] = []
        latencies: list[float] = []
        detail: list[dict] = []

        for item in questions:
            question = item["question"].strip()
            ground_truth = (item.get("ground_truth") or "").strip()

            t0 = time.perf_counter()
            chunks = self.retrieval.retrieve(question, top_k=top_k)
            latency_ms = int((time.perf_counter() - t0) * 1000)
            latencies.append(latency_ms)

            texts = [c.content for c in chunks]
            overlaps = [overlap_ratio(ground_truth, t) for t in texts] if ground_truth else []
            hit_idx = next((i for i, o in enumerate(overlaps) if o >= _HIT_OVERLAP), None) if overlaps else None

            hit = hit_idx is not None
            mrr = 1.0 / (hit_idx + 1) if hit_idx is not None else 0.0
            precision = sum(1 for o in overlaps if o >= _HIT_OVERLAP) / len(overlaps) if overlaps else None
            recall = max(overlaps) if overlaps else None

            hits.append(1.0 if hit else 0.0)
            mrrs.append(mrr)
            if precision is not None:
                precisions.append(precision)
            if recall is not None:
                recalls.append(recall)

            # 生成层（失败不影响检索指标）
            answer: Optional[str] = None
            try:
                answer = self.qa.generate(
                    query=question, history=None, top_k=top_k, use_agent=False, threshold=None
                ).answer
            except Exception as exc:  # noqa: BLE001
                logger.warning("评估时答案生成失败，跳过生成层指标: %s", exc)

            faith = self._judge(_FAITHFULNESS_PROMPT.format(context="\n".join(texts)[:3000], answer=answer or "")) if answer else None
            relevancy = self._judge(_RELEVANCY_PROMPT.format(question=question, answer=answer or "")) if answer else None
            if faith is not None:
                faiths.append(faith)
            if relevancy is not None:
                relevancies.append(relevancy)

            detail.append(
                {
                    "question": question,
                    "ground_truth": ground_truth,
                    "hit": hit,
                    "mrr": mrr,
                    "precision": precision,
                    "recall": recall,
                    "faithfulness": faith,
                    "answer_relevancy": relevancy,
                    "latency_ms": latency_ms,
                    "retrieved": [
                        {"chunk_id": c.chunk_id, "filename": c.filename, "score": round(c.score, 4), "snippet": c.content[:120]}
                        for c in chunks
                    ],
                }
            )

        metrics = {
            "hit_rate": _mean(hits),
            "mrr": _mean(mrrs),
            "precision_at_k": _mean(precisions),
            "recall_at_k": _mean(recalls),
            "faithfulness": _mean(faiths),
            "answer_relevancy": _mean(relevancies),
            "latency_ms_avg": _mean(latencies),
            "top_k": top_k,
        }
        return metrics, detail

    def _judge(self, prompt: str) -> Optional[float]:
        """让 LLM 输出 0-5 分，归一化到 0-1；任何失败返回 None。"""
        try:
            content, _ = self.llm.chat([{"role": "user", "content": prompt}], temperature=0.0, max_tokens=8)
        except Exception as exc:  # noqa: BLE001
            logger.warning("LLM 判分失败: %s", exc)
            return None
        match = re.search(r"(\d(?:\.\d+)?)", content)
        if not match:
            return None
        try:
            raw = float(match.group(1))
        except ValueError:
            return None
        score = raw / 5.0 if raw > 1.0 else raw
        return round(max(0.0, min(1.0, score)), 4)
