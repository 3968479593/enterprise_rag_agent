"""问答生成服务：检索 → 拼装上下文 →（Agent 推理 / 直接问答）→ 返回带来源的结果。"""
from dataclasses import dataclass, field
from typing import Optional

from app.rag.agent import AgentResult, ReActAgent
from app.rag.llm import LLMClient
from app.rag.retriever import RetrievedChunk
from app.rag.tools import (
    CalculatorTool,
    CurrentTimeTool,
    DocumentListTool,
    RetrieverTool,
    WebSearchTool,
)
from app.rag.retrieval import RetrievalService
from app.utils.logger import logger

_DIRECT_SYSTEM_PROMPT = (
    "你是一名企业知识库问答助手，请基于用户问题与【知识库片段】作答。回答风格要求：\n"
    "1. 排版清爽，像市面主流 AI 助手的回答：短句、分点、分块，少用括号、冒号等零碎标点；\n"
    "2. 数字信息紧凑呈现，如“全年营收 7517.66 亿元，同比 +14%”；\n"
    "3. 不要标注 [1][2] 来源编号，不要添加“仅供参考”等免责声明；\n"
    "4. 知识库没有相关内容时，明确说明“知识库中没有相关信息”，不要编造。"
)


@dataclass
class ChatResult:
    answer: str
    sources: list[dict] = field(default_factory=list)
    trace: dict = field(default_factory=dict)


class QAService:
    def __init__(self) -> None:
        self.llm = LLMClient()
        self.retrieval = RetrievalService()
        self._agent: Optional[ReActAgent] = None

    @property
    def agent(self) -> ReActAgent:
        """懒加载 Agent（避免初始化时做无用工具装配）。"""
        if self._agent is None:
            self._agent = ReActAgent(
                llm=self.llm,
                tools=[
                    RetrieverTool(self.retrieval.retriever, top_k=4),
                    CalculatorTool(),
                    CurrentTimeTool(),
                    WebSearchTool(),
                    DocumentListTool(),
                ],
            )
        return self._agent

    def generate(
        self,
        query: str,
        history: Optional[list[dict]] = None,
        top_k: int = 5,
        use_agent: bool = True,
        threshold: Optional[float] = None,
    ) -> ChatResult:
        chunks = self.retrieval.retrieve(query, top_k=top_k, threshold=threshold)
        context = self._format_context(chunks)
        sources = [
            {
                "chunk_id": c.chunk_id,
                "document_id": c.document_id,
                "filename": c.filename,
                "score": round(c.score, 4),
                "snippet": c.content[:200],
            }
            for c in chunks
        ]

        if use_agent:
            result: AgentResult = self.agent.answer(query, context=context, history=history)
            return ChatResult(
                answer=result.answer,
                sources=sources,
                trace={
                    "mode": "agent",
                    "retrieved_count": len(chunks),
                    "steps": result.steps,
                    "usage": result.usage,
                },
            )

        # 直接模式：一次 LLM 调用
        user_content = query if not context else f"{query}\n\n【知识库片段】\n{context}"
        messages: list[dict] = [{"role": "system", "content": _DIRECT_SYSTEM_PROMPT}]
        for h in (history or [])[-6:]:
            messages.append({"role": h["role"], "content": h["content"]})
        messages.append({"role": "user", "content": user_content})
        answer, usage = self.llm.chat(messages)
        return ChatResult(
            answer=answer,
            sources=sources,
            trace={"mode": "direct", "retrieved_count": len(chunks), "usage": usage},
        )

    @staticmethod
    def _format_context(chunks: list[RetrievedChunk]) -> str:
        if not chunks:
            return ""
        return "\n\n".join(
            f"[{i + 1}] (来源文件: {c.filename}, 相关度: {c.score:.3f})\n{c.content}"
            for i, c in enumerate(chunks)
        )
