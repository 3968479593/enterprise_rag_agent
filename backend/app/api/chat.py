"""问答接口：检索增强生成（支持 Agent 模式与流式输出）。"""
import json
import time
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.auth import get_current_user
from app.config import settings
from app.models.orm import Conversation, Message
from app.models.database import get_db
from app.models.schemas import ChatRequest, ChatResponse, SourceRef
from app.rag.qa import QAService, _DIRECT_SYSTEM_PROMPT
from app.utils import new_id
from app.utils.logger import logger

router = APIRouter()
qa_service = QAService()


def _sse(obj: dict) -> str:
    """SSE 事件行：data: <json>"""
    return f"data: {json.dumps(obj, ensure_ascii=False)}\n\n"


@router.post("", response_model=ChatResponse)
def chat(
    req: ChatRequest,
    payload: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ChatResponse:
    """单轮问答：检索知识库 →（可选 Agent 推理）→ 生成回答，并落库会话记录。"""
    start = time.perf_counter()
    message = req.message.strip()
    if not message:
        raise HTTPException(status_code=422, detail="message 不能为空")

    conversation = _get_or_create_conversation(db, req.conversation_id, payload["user_id"])
    history = _load_history(db, conversation.id)

    result = qa_service.generate(
        query=message,
        history=history,
        top_k=req.top_k,
        use_agent=req.use_agent,
        threshold=req.threshold,
    )
    latency_ms = int((time.perf_counter() - start) * 1000)

    user_msg = Message(id=new_id("msg"), conversation_id=conversation.id, role="user", content=message)
    assistant_msg = Message(
        id=new_id("msg"),
        conversation_id=conversation.id,
        role="assistant",
        content=result.answer,
        sources=result.sources,
        trace=result.trace,
        latency_ms=latency_ms,
    )
    db.add_all([user_msg, assistant_msg])

    if conversation.title == "新对话":
        conversation.title = message[:24]

    db.commit()

    return ChatResponse(
        answer=result.answer,
        conversation_id=conversation.id,
        message_id=assistant_msg.id,
        sources=[SourceRef(**s) for s in result.sources],
        trace=result.trace,
        latency_ms=latency_ms,
        model=settings.LLM_MODEL,
    )


def _get_or_create_conversation(
    db: Session, conversation_id: Optional[str], user_id: Optional[str]
) -> Conversation:
    if conversation_id:
        conv = db.get(Conversation, conversation_id)
        # 归属校验：只能在自己的会话中继续对话（无主遗留会话不可写），杜绝跨用户污染/读取
        if conv is None or conv.user_id is None or conv.user_id != user_id:
            raise HTTPException(status_code=404, detail="会话不存在")
        return conv
    conv = Conversation(id=new_id("conv"), title="新对话", user_id=user_id)
    db.add(conv)
    db.commit()
    return conv


def _load_history(db: Session, conversation_id: str) -> list[dict]:
    msgs = (
        db.query(Message)
        .filter(Message.conversation_id == conversation_id)
        .order_by(Message.created_at.desc())
        .limit(6)
        .all()
    )
    return [{"role": m.role, "content": m.content} for m in reversed(msgs)]


# ---------- 流式输出 ----------

class FeedbackRequest(BaseModel):
    value: Optional[str] = None  # "up" / "down" / null（取消反馈）
    shared: Optional[bool] = None  # 用户是否同意管理员查看该条反馈对话
    note: Optional[str] = None  # 补充的反馈意见（传空字符串可清除）


@router.post("/messages/{message_id}/feedback")
def feedback(
    message_id: str,
    req: FeedbackRequest,
    payload: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """回答反馈：value 打 👍/👎（可覆盖、可取消）；note 补充意见；shared 授权管理员查看（默认不授权）。

    隐私原则：反馈与对话内容默认仅用户自己可见，用户勾选共享后管理员端才出现该记录。
    """
    if req.value not in (None, "up", "down"):
        raise HTTPException(status_code=422, detail="value 仅支持 up / down / null")
    msg = db.get(Message, message_id)
    if msg is None or msg.role != "assistant":
        raise HTTPException(status_code=404, detail="消息不存在")
    # 归属校验：只能反馈自己的消息（含无主遗留会话的消息），防止跨用户篡改反馈/授权
    conv = db.get(Conversation, msg.conversation_id)
    if conv is None or conv.user_id is None or conv.user_id != payload.get("user_id"):
        raise HTTPException(status_code=404, detail="消息不存在")
    if req.value is not None:
        msg.feedback = req.value
    if req.shared is not None:
        msg.feedback_shared = bool(req.shared)
    if req.note is not None:
        msg.feedback_note = req.note.strip() or None
    db.commit()
    return {
        "message_id": message_id,
        "feedback": msg.feedback,
        "shared": bool(msg.feedback_shared),
        "note": msg.feedback_note,
    }


@router.post("/stream")
def chat_stream(
    req: ChatRequest,
    payload: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> StreamingResponse:
    """SSE 流式问答（直答模式）：检索 → LLM 逐字生成 → 落库会话。"""
    message = req.message.strip()
    if not message:
        raise HTTPException(status_code=422, detail="message 不能为空")

    conversation = _get_or_create_conversation(db, req.conversation_id, payload["user_id"])
    history = _load_history(db, conversation.id)

    # 流式仅支持直答（Agent 多轮工具推理不适合逐字推送，前端开关会强制直答）
    chunks = qa_service.retrieval.retrieve(
        query=message, top_k=req.top_k, threshold=req.threshold
    )
    context = QAService._format_context(chunks)
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

    user_content = message if not context else f"{message}\n\n【知识库片段】\n{context}"
    messages: list[dict] = [{"role": "system", "content": _DIRECT_SYSTEM_PROMPT}]
    for h in history[-6:]:
        messages.append({"role": h["role"], "content": h["content"]})
    messages.append({"role": "user", "content": user_content})

    start = time.perf_counter()

    def gen():
        parts: list[str] = []
        yield _sse({"type": "start", "conversation_id": conversation.id})
        try:
            for delta in qa_service.llm.stream(messages):
                parts.append(delta)
                yield _sse({"type": "delta", "content": delta})
        except Exception as exc:  # noqa: BLE001
            logger.exception("流式回答生成异常")
            yield _sse({"type": "error", "detail": "回答生成中断，请稍后重试"})
            return

        answer = "".join(parts)
        latency_ms = int((time.perf_counter() - start) * 1000)
        user_msg = Message(id=new_id("msg"), conversation_id=conversation.id, role="user", content=message)
        assistant_msg = Message(
            id=new_id("msg"),
            conversation_id=conversation.id,
            role="assistant",
            content=answer,
            sources=sources,
            latency_ms=latency_ms,
        )
        db.add_all([user_msg, assistant_msg])
        if conversation.title == "新对话":
            conversation.title = message[:24]
        db.commit()

        yield _sse(
            {
                "type": "done",
                "conversation_id": conversation.id,
                "message_id": assistant_msg.id,
                "sources": sources,
                "latency_ms": latency_ms,
            }
        )

    return StreamingResponse(gen(), media_type="text/event-stream")
