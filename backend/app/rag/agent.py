"""ReAct Agent：Thought → Action → Observation → 循环，直到 Final Answer。

健壮性设计：
- 最大迭代次数硬上限，防止工具循环失控；
- 模型未按协议输出时，把原文当最终答案兜底返回，不让用户拿到空响应；
- 工具不存在/执行异常均转成 Observation 文本喂回模型，不中断对话；
- 完整推理步骤（steps）随响应返回，供前端展示与审计。
"""
import re
from dataclasses import dataclass, field
from typing import Optional

from app.rag.llm import LLMClient
from app.rag.tools import Tool

_FINAL_RE = re.compile(r"Final Answer:\s*(.+)$", re.DOTALL)
_ACTION_RE = re.compile(r"Action:\s*(\w+)\s*\n\s*Action Input:\s*(.+)$", re.DOTALL)


def build_system_prompt(tool_descriptions: str, context_provided: bool = False) -> str:
    context_hint = ""
    if context_provided:
        context_hint = (
            "\n4. 已为你提供【知识库片段】，优先基于这些片段作答；"
            "只有片段中缺少所需信息（如需要计算、确认时间、联网或补充资料）时，才调用检索工具。\n"
        )
    return f"""你是一名企业知识库问答助手，可以调用工具获取信息，并基于【知识库片段】回答。

回答要求：
1. 排版清爽，像市面主流 AI 助手的回答：短句、分点、分块，少用括号、冒号等零碎标点；数字信息紧凑呈现。
2. 不要标注 [1][2] 来源编号，不要添加"仅供参考"等免责声明；来源由前端列表展示。
3. 知识库无法回答时，明确说明"知识库中没有相关信息"，不要编造事实。
{context_hint}5. 需要计算、确认时间或联网搜索时，先调用对应工具；工具结果会以 Observation 返回。
6. 忠于原文，不编造工具未返回的数据。

可用工具：
{tool_descriptions}

使用格式（必须严格遵循，每轮只输出一个动作）：
Thought: 你的推理过程
Action: 工具名
Action Input: 工具入参
（等待 Observation 返回后继续推理，得到答案时再输出）
Thought: 我现在已经获得足够信息
Final Answer: 最终回答
"""


@dataclass
class AgentResult:
    answer: str
    steps: list[dict] = field(default_factory=list)
    usage: Optional[dict] = None


class ReActAgent:
    def __init__(
        self,
        llm: LLMClient,
        tools: list[Tool],
        max_iterations: int = 6,
    ) -> None:
        self.llm = llm
        self.tools: dict[str, Tool] = {t.name: t for t in tools}
        self.max_iterations = max_iterations

    def answer(
        self,
        query: str,
        context: str = "",
        history: Optional[list[dict]] = None,
    ) -> AgentResult:
        system = build_system_prompt(self._tool_desc(), context_provided=bool(context))
        user_content = query if not context else f"{query}\n\n【知识库片段】\n{context}"

        messages: list[dict] = [{"role": "system", "content": system}]
        for h in (history or [])[-6:]:
            messages.append({"role": h["role"], "content": h["content"]})
        messages.append({"role": "user", "content": user_content})

        steps: list[dict] = []
        usage_agg: dict = {}

        for _ in range(self.max_iterations):
            reply, usage = self.llm.chat(messages, temperature=0.0)
            if usage:
                usage_agg = usage
            steps.append({"type": "assistant_reply", "content": reply})

            final = _FINAL_RE.search(reply)
            if final:
                return AgentResult(answer=final.group(1).strip(), steps=steps, usage=usage_agg)

            action = _ACTION_RE.search(reply)
            if not action:
                # 协议解析失败：把模型输出原样作为答案，保证响应不为空
                return AgentResult(answer=reply.strip(), steps=steps, usage=usage_agg)

            tool_name, tool_input = action.group(1).strip(), action.group(2).strip()
            tool = self.tools.get(tool_name)
            if tool is None:
                observation = f"错误：未知工具 {tool_name}。可用工具: {', '.join(self.tools)}"
            else:
                try:
                    observation = tool.run(tool_input)
                except Exception as exc:  # noqa: BLE001
                    observation = f"工具执行失败: {exc}"

            steps.append(
                {"type": "tool_call", "tool": tool_name, "input": tool_input, "observation": observation}
            )
            messages.append({"role": "assistant", "content": reply})
            messages.append({"role": "user", "content": f"Observation: {observation}"})

        return AgentResult(
            answer="已达到最大推理轮次，未能得到最终答案，请尝试简化问题。",
            steps=steps,
            usage=usage_agg,
        )

    def _tool_desc(self) -> str:
        return "\n".join(f"- {t.name}: {t.description}" for t in self.tools.values())
