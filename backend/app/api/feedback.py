"""反馈管理：管理员查看用户已授权共享的反馈，定位知识库问题。

隐私原则：反馈与对话默认仅用户自己可见。只有用户明确勾选
"同意管理员查看"（feedback_shared=1）的记录才会出现在这里。
"""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.auth import get_current_admin
from app.models.database import get_db
from app.models.orm import Conversation, Message, User

router = APIRouter()


@router.get("")
def list_feedback(
    kind: str = "",  # "" 全部 / up 有用 / down 没用
    limit: int = 200,
    _: dict = Depends(get_current_admin),
    db: Session = Depends(get_db),
) -> dict:
    # 仅用户授权共享的记录（feedback_shared=1）
    base = db.query(Message).filter(
        Message.role == "assistant",
        Message.feedback.isnot(None),
        Message.feedback_shared.is_(True),
    )

    # 统计
    stats = {"total": 0, "up": 0, "down": 0}
    for (fb,) in base.with_entities(Message.feedback).all():
        stats["total"] += 1
        stats[fb] = stats.get(fb, 0) + 1

    # 列表
    q = (
        db.query(Message, Conversation, User)
        .join(Conversation, Message.conversation_id == Conversation.id)
        .outerjoin(User, Conversation.user_id == User.id)
        .filter(
            Message.role == "assistant",
            Message.feedback.isnot(None),
            Message.feedback_shared.is_(True),
        )
    )
    if kind in ("up", "down"):
        q = q.filter(Message.feedback == kind)
    rows = q.order_by(Message.created_at.desc()).limit(min(limit, 500)).all()

    items = []
    for m, conv, user in rows:
        items.append(
            {
                "message_id": m.id,
                "content": m.content,
                "feedback": m.feedback,
                "note": m.feedback_note,
                "created_at": m.created_at.isoformat() if m.created_at else "",
                "conversation_id": conv.id,
                "conversation_title": conv.title,
                "username": user.username if user else "已注销",
                "sources": m.sources or [],
            }
        )

    # 按文档聚合"没用"反馈（仅已授权共享的）
    by_doc: dict[str, int] = {}
    for m in (
        db.query(Message)
        .filter(
            Message.role == "assistant",
            Message.feedback == "down",
            Message.feedback_shared.is_(True),
        )
        .all()
    ):
        seen: set[str] = set()
        for s in m.sources or []:
            fn = s.get("filename", "未知文档")
            if fn in seen:
                continue
            seen.add(fn)
            by_doc[fn] = by_doc.get(fn, 0) + 1
    doc_down = sorted(
        ({"filename": k, "count": v} for k, v in by_doc.items()),
        key=lambda x: -x["count"],
    )

    return {"items": items, "stats": stats, "doc_down": doc_down[:20]}
