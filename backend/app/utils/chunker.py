"""文本切分：递归字符切分 + 滑动重叠 + 中英混合 token 估算。

原则：
- 优先在句子边界（段落/句号/问号/感叹号/分号）断句，避免语义被拦腰截断；
- 重叠区保留上下文衔接，降低边界信息丢失；
- token 估算用于日志与容量观测，不参与检索打分。
"""
import re
from dataclasses import dataclass, field
from typing import Any

_SENTENCE_BOUNDARY = re.compile(r"[\n]{2,}|\n|。|！|？|；|\. |! |\? |; ")
_CJK_RE = re.compile(r"[\u4e00-\u9fff]+")
_WORD_RE = re.compile(r"[a-z0-9_]+")


@dataclass
class Chunk:
    index: int
    content: str
    token_estimate: int
    meta: dict[str, Any] = field(default_factory=dict)


def estimate_tokens(text: str) -> int:
    """近似 token 数：中文字符按 1 token/字，英文按 1 token/词。"""
    cjk = sum(1 for ch in text if "\u4e00" <= ch <= "\u9fff")
    words = len(_WORD_RE.findall(text))
    return cjk + words


def tokenize(text: str) -> list[str]:
    """中英混合分词：英文按词，中文按二元组（BM25 用）。"""
    text = text.lower()
    tokens: list[str] = _WORD_RE.findall(text)
    for seg in _CJK_RE.findall(text):
        if len(seg) <= 1:
            tokens.append(seg)
        else:
            tokens.extend(seg[i : i + 2] for i in range(len(seg) - 1))
    return tokens


def split_text(
    text: str,
    chunk_size: int = 800,
    overlap: int = 120,
) -> list[Chunk]:
    """递归切分主入口。返回带 index / token 估算的 Chunk 列表。"""
    text = re.sub(r"\r\n?", "\n", text).strip()
    if not text:
        return []

    chunks: list[Chunk] = []
    start, idx, n = 0, 0, len(text)
    while start < n:
        end = min(start + chunk_size, n)
        if end < n:
            window = text[start:end]
            best = -1
            for m in _SENTENCE_BOUNDARY.finditer(window):
                if m.end() >= chunk_size * 0.5:
                    best = m.end()
                    break
            if best == -1:  # 退化为最后一个边界
                matches = list(_SENTENCE_BOUNDARY.finditer(window))
                if matches:
                    best = matches[-1].end()
            if best != -1:
                end = start + best

        content = text[start:end].strip()
        if content:
            chunks.append(
                Chunk(index=idx, content=content, token_estimate=estimate_tokens(content))
            )
            idx += 1

        if end >= n:
            break
        start = max(end - overlap, start + 1)  # 保证向前推进，防止死循环

    return chunks
