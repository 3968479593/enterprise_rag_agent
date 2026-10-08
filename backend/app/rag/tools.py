"""Agent 自定义工具集：检索、计算、时间、联网搜索、文档清单。

工具设计原则：
- 每个工具继承 Tool，实现 run(args: str) -> str，入参出参都是字符串，
  与 LLM 的 ReAct 协议天然对齐；
- 工具内部兜底错误信息，绝不让异常打断 Agent 主循环；
- 新增工具只需继承 Tool 并注册，无需改动 Agent 核心。
"""
import ast
import datetime
import operator
from typing import Optional

import httpx

from app.config import settings
from app.models.database import SessionLocal
from app.models.orm import Document
from app.rag.retriever import HybridRetriever
from app.utils.logger import logger

# 中国标准时间（优先 zoneinfo，Windows 无 tzdata 时回退固定 UTC+8）
try:
    from zoneinfo import ZoneInfo

    _CN_TZ = ZoneInfo("Asia/Shanghai")
except Exception:  # noqa: BLE001
    _CN_TZ = datetime.timezone(datetime.timedelta(hours=8))


class Tool:
    name: str = ""
    description: str = ""

    def run(self, args: str) -> str:
        raise NotImplementedError


class RetrieverTool(Tool):
    """企业知识库检索工具，Agent 可在推理中主动召回。"""

    name = "retrieve_knowledge"
    description = "从企业知识库检索相关资料。入参为查询问题，例如：差旅住宿标准是多少"

    def __init__(self, retriever: HybridRetriever, top_k: int = 4) -> None:
        self.retriever = retriever
        self.top_k = top_k

    def run(self, args: str) -> str:
        query = args.strip()
        if query.lower().startswith("query:"):
            query = query.split(":", 1)[1].strip()
        if not query:
            return "错误：检索入参不能为空。"
        chunks = self.retriever.retrieve(query, top_k=self.top_k)
        if not chunks:
            return "知识库中没有检索到相关内容。"
        return "\n\n".join(
            f"【资料 {i + 1}】来源《{c.filename}》相关度 {c.score:.3f}\n{c.content}"
            for i, c in enumerate(chunks)
        )


class CalculatorTool(Tool):
    """安全计算器：AST 白名单求值，杜绝任意代码执行。"""

    name = "calculator"
    description = "执行数学计算。入参为数学表达式，例如：3.5 * (12 - 4) / 2"

    _BINARY = {
        ast.Add: operator.add,
        ast.Sub: operator.sub,
        ast.Mult: operator.mul,
        ast.Div: operator.truediv,
        ast.FloorDiv: operator.floordiv,
        ast.Mod: operator.mod,
        ast.Pow: operator.pow,
    }
    _UNARY = {ast.USub: operator.neg, ast.UAdd: operator.pos}

    def run(self, args: str) -> str:
        expr = args.strip().strip("`")
        try:
            node = ast.parse(expr, mode="eval")
            value = self._eval(node.body)
            return f"{value:g}"
        except Exception as exc:  # noqa: BLE001
            return f"错误：无法计算表达式（{exc}）。请检查表达式语法。"

    def _eval(self, node: ast.AST) -> float:
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
            return float(node.value)
        if isinstance(node, ast.BinOp) and type(node.op) in self._BINARY:
            return self._BINARY[type(node.op)](self._eval(node.left), self._eval(node.right))
        if isinstance(node, ast.UnaryOp) and type(node.op) in self._UNARY:
            return self._UNARY[type(node.op)](self._eval(node.operand))
        raise ValueError(f"不支持的表达式节点: {type(node).__name__}")


class CurrentTimeTool(Tool):
    """返回中国标准时间（Asia/Shanghai），与用户本地时间一致。"""

    name = "current_time"
    description = "获取当前日期与时间（中国标准时间）。入参填写任意内容，例如：now"

    def run(self, args: str) -> str:
        now = datetime.datetime.now(_CN_TZ)
        weekday = "周" + "一二三四五六日"[now.weekday()]
        return f"当前时间：{now:%Y-%m-%d %H:%M:%S}（{weekday}，中国标准时间）"


class WebSearchTool(Tool):
    """联网搜索（Tavily API）。未配置 Key 时返回明确提示而非报错。"""

    name = "web_search"
    description = "联网搜索最新信息。入参为搜索关键词，例如：2025 年新能源汽车销量"

    def run(self, args: str) -> str:
        if not settings.TAVILY_API_KEY:
            return "错误：未配置 TAVILY_API_KEY，无法联网搜索。"
        try:
            resp = httpx.post(
                settings.TAVILY_SEARCH_URL,
                json={"api_key": settings.TAVILY_API_KEY, "query": args.strip(), "max_results": 4},
                timeout=20,
            )
            resp.raise_for_status()
            results = resp.json().get("results", [])
            if not results:
                return "未搜索到相关结果。"
            return "\n\n".join(
                f"[{i + 1}] {r.get('title', '')}\n{r.get('content', '')}\n来源链接: {r.get('url', '')}"
                for i, r in enumerate(results)
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("联网搜索失败: %s", exc)
            return "搜索失败，请稍后重试或检查网络。"


class DocumentListTool(Tool):
    """列出知识库中已入库的文档，帮助说明知识库覆盖范围。"""

    name = "list_documents"
    description = "列出知识库中已上传并入库的文档清单。入参可忽略，例如：list"

    def run(self, args: str) -> str:
        try:
            with SessionLocal() as db:
                docs = (
                    db.query(Document)
                    .filter(Document.status == "ingested")
                    .order_by(Document.created_at.desc())
                    .all()
                )
        except Exception as exc:  # noqa: BLE001
            return f"错误：读取文档清单失败（{exc}）。"
        if not docs:
            return "知识库中暂无已入库文档。"
        return "\n".join(f"- {d.filename}（{d.chunk_count} 个片段）" for d in docs)
