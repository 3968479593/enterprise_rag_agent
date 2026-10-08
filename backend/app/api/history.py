"""会话历史接口：会话列表 / 详情 / 删除（按当前登录用户隔离）。"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.api.auth import get_current_user
from app.models.orm import Conversation, Message
from app.models.database import get_db
from app.models.schemas import (
    ConversationDetail,
    ConversationOut,
    DeleteConversationResponse,
    MessageOut,
)

router = APIRouter()


def _own_filter(user_id: str, is_admin: bool):
    """会话归属过滤：管理员 = 自己的 + 无主遗留数据（升级前无归属）；普通用户 = 仅自己的，杜绝跨用户可见。"""
    if is_admin:
        return or_(Conversation.user_id == user_id, Conversation.user_id.is_(None))
    return Conversation.user_id == user_id


def _can_access(conv: Conversation, payload: dict) -> bool:
    """ORM 对象级归属校验：无主遗留数据仅管理员可见；有主会话仅本人可见。"""
    if conv.user_id is None:
        return payload.get("role") == "admin"
    return conv.user_id == payload.get("user_id")


@router.get("", response_model=list[ConversationOut])
def list_conversations(
    payload: dict = Depends(get_current_user),
    q: str = "",
    limit: int = 50,
    db: Session = Depends(get_db),
) -> list[ConversationOut]:
    query = db.query(Conversation).filter(
        _own_filter(payload["user_id"], payload.get("role") == "admin")
    )
    if q.strip():
        query = query.filter(Conversation.title.contains(q.strip()))
    conversations = (
        query.order_by(Conversation.updated_at.desc()).limit(min(limit, 200)).all()
    )
    out: list[ConversationOut] = []
    for conv in conversations:
        count = (
            db.query(func.count(Message.id))
            .filter(Message.conversation_id == conv.id)
            .scalar()
            or 0
        )
        out.append(
            ConversationOut(
                id=conv.id,
                title=conv.title,
                created_at=conv.created_at,
                updated_at=conv.updated_at,
                message_count=count,
            )
        )
    return out


@router.get("/{conversation_id}", response_model=ConversationDetail)
def get_conversation(
    conversation_id: str,
    payload: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ConversationDetail:
    conv = db.get(Conversation, conversation_id)
    if conv is None:
        raise HTTPException(status_code=404, detail="会话不存在")
    # 管理员：自己的会话直接可看；别人的（有主）会话只返回用户明确授权共享（feedback_shared=1）的消息（隐私边界，按消息粒度过滤）
    if (
        payload.get("role") == "admin"
        and conv.user_id is not None
        and conv.user_id != payload.get("user_id")
    ):
        messages = (
            db.query(Message)
            .filter(
                Message.conversation_id == conv.id,
                Message.feedback_shared.is_(True),
            )
            .order_by(Message.created_at.asc())
            .all()
        )
        if not messages:
            raise HTTPException(status_code=404, detail="会话不存在或未获得用户共享授权")
        return ConversationDetail(
            id=conv.id,
            title=conv.title,
            messages=[
                MessageOut(
                    id=m.id,
                    role=m.role,
                    content=m.content,
                    sources=m.sources,
                    trace=m.trace,
                    latency_ms=m.latency_ms,
                    feedback=m.feedback,
                    feedback_shared=bool(m.feedback_shared),
                    feedback_note=m.feedback_note,
                    created_at=m.created_at,
                )
                for m in messages
            ],
        )
    elif not _can_access(conv, payload):
        raise HTTPException(status_code=404, detail="会话不存在")

    messages = (
        db.query(Message)
        .filter(Message.conversation_id == conv.id)
        .order_by(Message.created_at.asc())
        .all()
    )
    return ConversationDetail(
        id=conv.id,
        title=conv.title,
        messages=[
            MessageOut(
                id=m.id,
                role=m.role,
                content=m.content,
                sources=m.sources,
                trace=m.trace,
                latency_ms=m.latency_ms,
                feedback=m.feedback,
                feedback_shared=bool(m.feedback_shared),
                feedback_note=m.feedback_note,
                created_at=m.created_at,
            )
            for m in messages
        ],
    )


@router.delete("/{conversation_id}", response_model=DeleteConversationResponse)
def delete_conversation(
    conversation_id: str,
    payload: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> DeleteConversationResponse:
    conv = db.get(Conversation, conversation_id)
    if conv is None or not _can_access(conv, payload):
        raise HTTPException(status_code=404, detail="会话不存在")
    db.delete(conv)
    db.commit()
    return DeleteConversationResponse(conversation_id=conversation_id, deleted=True)
