# -*- coding: utf-8 -*-
"""全量回归：安全修复 + CORS + 无主会话 + 重排 API + SQLite WAL。"""
import io
import sys
import time
from pathlib import Path

import httpx
import sqlalchemy

BACKEND = r"D:\DesktopFiles\企业文档智能客服\enterprise_rag_agent\backend"
sys.path.insert(0, BACKEND)

BASE = "http://127.0.0.1:8010"
env = io.open(Path(BACKEND) / ".env", encoding="utf-8").read()
adm_key = next(
    (l.split("=", 1)[1].strip() for l in env.splitlines() if l.strip().startswith("ADMIN_API_KEY=")), ""
)

results = []
def check(name, ok, detail=""):
    results.append((name, ok))
    print(("PASS " if ok else "FAIL ") + name + ((" | " + detail) if detail else ""))

suffix = str(int(time.time()) % 1000000)
u1, p1 = f"tuser{suffix}", "test123456"
a1, pa = f"tadm{suffix}", "test123456"

c = httpx.Client(base_url=BASE, timeout=30)
try:
    # ---------- 安全回归（前轮 9 项） ----------
    r = c.post("/api/auth/register", json={"username": u1, "password": p1})
    t1 = r.json().get("token", "") if r.status_code == 201 else ""
    r = c.post("/api/auth/register", json={"username": a1, "password": pa, "invite_code": adm_key})
    t2 = r.json().get("token", "") if r.status_code == 201 else ""
    check("注册普通用户+管理员", bool(t1 and t2), str(r.status_code))

    up = Path(BACKEND) / "data" / "uploads"
    up.mkdir(parents=True, exist_ok=True)
    (up / "sec_test.txt").write_text("secret-content", encoding="utf-8")
    r = c.get("/uploads/sec_test.txt")
    check("uploads 未登录 401", r.status_code == 401)
    r = c.get("/uploads/sec_test.txt", headers={"Authorization": f"Bearer {t1}"})
    check("uploads 带 token 200", r.status_code == 200 and r.text == "secret-content")
    (up / "sec_test.txt").unlink()

    eng = sqlalchemy.create_engine(f"sqlite:///{Path(BACKEND) / 'rag.db'}", connect_args={"check_same_thread": False})
    with eng.begin() as conn:
        conn.execute(sqlalchemy.text("UPDATE auth_tokens SET expires_at='2020-01-01 00:00:00' WHERE token=:t"), {"t": t1})
    r = c.get("/api/conversations", headers={"Authorization": f"Bearer {t1}"})
    check("过期 token 401", r.status_code == 401)

    r = c.post("/api/auth/logout", headers={"Authorization": f"Bearer {t2}"})
    r = c.get("/api/conversations", headers={"Authorization": f"Bearer {t2}"})
    check("logout 后 token 401", r.status_code == 401)

    r = c.post("/api/auth/login", json={"username": u1, "password": p1})
    t1 = r.json()["token"]
    r = c.post("/api/auth/login", json={"username": a1, "password": pa})
    t3 = r.json()["token"]

    from app.models.database import SessionLocal
    from app.models.orm import AuthToken, Conversation, Message, User
    from app.utils import new_id

    with SessionLocal() as db:
        owner = db.query(User).filter(User.username == u1).first()
        conv = Conversation(id=new_id("conv"), user_id=owner.id, title="隐私测试会话")
        db.add(conv)
        db.flush()
        db.add_all([
            Message(id=new_id("msg"), conversation_id=conv.id, role="user", content="隐私问题一", feedback_shared=False),
            Message(id=new_id("msg"), conversation_id=conv.id, role="assistant", content="隐私回答二", feedback_shared=False),
            Message(id=new_id("msg"), conversation_id=conv.id, role="assistant", content="已授权回答三", feedback_shared=True),
        ])
        db.commit()
        conv_id = conv.id

    r = c.get(f"/api/conversations/{conv_id}", headers={"Authorization": f"Bearer {t3}"})
    ok = r.status_code == 200 and len(r.json().get("messages", [])) == 1 and r.json()["messages"][0]["content"] == "已授权回答三"
    check("管理员仅见被授权 1 条", ok, f"status={r.status_code}")
    r = c.get(f"/api/conversations/{conv_id}", headers={"Authorization": f"Bearer {t1}"})
    check("用户本人可见全部（回归）", r.status_code == 200 and len(r.json().get("messages", [])) == 3, str(r.status_code))

    # ---------- 越权回归：跨用户会话/消息 ----------
    u2, p2 = f"tuser2{suffix}", "test123456"
    r = c.post("/api/auth/register", json={"username": u2, "password": p2})
    t4 = r.json().get("token", "")
    check("注册用户 B", bool(t4), str(r.status_code))
    # B 用 A 的会话 ID 发消息 → 404
    r = c.post(
        "/api/chat",
        json={"message": "越权测试", "conversation_id": conv_id},
        headers={"Authorization": f"Bearer {t4}"},
    )
    check("他人会话不可发消息", r.status_code == 404, str(r.status_code))
    # B 对 A 的消息打反馈 / 授权共享 → 404
    with SessionLocal() as db:
        a_msg_id = (
            db.query(Message)
            .filter(Message.conversation_id == conv_id, Message.role == "assistant", Message.feedback_shared.is_(True))
            .first()
            .id
        )
    r = c.post(
        f"/api/chat/messages/{a_msg_id}/feedback",
        json={"value": "up"},
        headers={"Authorization": f"Bearer {t4}"},
    )
    check("他人消息不可反馈", r.status_code == 404, str(r.status_code))
    r = c.post(
        f"/api/chat/messages/{a_msg_id}/feedback",
        json={"shared": True},
        headers={"Authorization": f"Bearer {t4}"},
    )
    check("他人消息不可授权共享", r.status_code == 404, str(r.status_code))

    # ---------- CORS ----------
    r = c.options(
        "/api/auth/login",
        headers={
            "Origin": "http://localhost:5173",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "authorization,content-type",
        },
    )
    acao = r.headers.get("access-control-allow-origin", "")
    check("CORS 白名单生效（非 *）", acao == "http://localhost:5173", f"allow-origin={acao}")
    r = c.options(
        "/api/auth/login",
        headers={"Origin": "http://evil.example.com", "Access-Control-Request-Method": "POST"},
    )
    acao2 = r.headers.get("access-control-allow-origin", "")
    check("CORS 拒绝陌生来源", acao2 != "http://evil.example.com", f"allow-origin={acao2}")

    # ---------- 无主会话：普通用户不可见，管理员可见 ----------
    with SessionLocal() as db:
        orphan = Conversation(id=new_id("conv"), user_id=None, title="无主遗留会话")
        db.add(orphan)
        db.flush()
        db.add(Message(id=new_id("msg"), conversation_id=orphan.id, role="assistant", content="遗留内容"))
        db.commit()
        orphan_id = orphan.id
    r = c.get("/api/conversations", headers={"Authorization": f"Bearer {t1}"})
    check("普通用户列表不含无主会话", orphan_id not in [x["id"] for x in r.json()], str(r.status_code))
    r = c.get(f"/api/conversations/{orphan_id}", headers={"Authorization": f"Bearer {t1}"})
    check("普通用户访问无主会话 404", r.status_code == 404, str(r.status_code))
    r = c.delete(f"/api/conversations/{orphan_id}", headers={"Authorization": f"Bearer {t1}"})
    check("普通用户删除无主会话 404", r.status_code == 404, str(r.status_code))
    r = c.get(f"/api/conversations/{orphan_id}", headers={"Authorization": f"Bearer {t3}"})
    check("管理员可见无主会话", r.status_code == 200, str(r.status_code))

    # ---------- SQLite WAL ----------
    with eng.connect() as conn:
        mode = conn.execute(sqlalchemy.text("PRAGMA journal_mode")).scalar()
    check("SQLite WAL 模式生效", str(mode).lower() == "wal", str(mode))

    # ---------- 重排 API 实测（硅基流动 /rerank + bge-reranker-v2-m3） ----------
    emb_base = next((l.split("=", 1)[1].strip() for l in env.splitlines() if l.strip().startswith("EMBEDDING_API_BASE=")), "")
    emb_key = next((l.split("=", 1)[1].strip() for l in env.splitlines() if l.strip().startswith("EMBEDDING_API_KEY=")), "")
    model = next((l.split("=", 1)[1].strip() for l in env.splitlines() if l.strip().startswith("RERANK_MODEL=")), "")
    if emb_base and emb_key and model:
        rr = httpx.post(
            f"{emb_base}/rerank",
            json={
                "model": model,
                "query": "合同违约金比例是多少",
                "documents": ["今天天气很好适合出游", "合同中约定违约方需支付合同总价 30% 的违约金"],
            },
            headers={"Authorization": f"Bearer {emb_key}"},
            timeout=30,
        )
        ok = rr.status_code == 200 and rr.json().get("results")
        check("重排 API 实测可用", ok, f"status={rr.status_code}, results={len(rr.json().get('results', [])) if rr.status_code == 200 else rr.text[:100]}")
    else:
        check("重排 API 实测可用", False, "缺少 EMBEDDING/RERANK 配置")

    # ---------- 阈值配置生效 ----------
    from app.config import settings
    check("SCORE_THRESHOLD=0.15", abs(settings.SCORE_THRESHOLD - 0.15) < 1e-9, str(settings.SCORE_THRESHOLD))
    check("CORS_ORIGINS 不含 *", "*" not in settings.CORS_ORIGINS, str(settings.CORS_ORIGINS))

    # ---------- 清理测试数据 ----------
    with SessionLocal() as db:
        users = db.query(User).filter(User.username.in_([u1, a1, u2])).all()
        uids = [u.id for u in users]
        db.query(Message).filter(Message.conversation_id == conv_id).delete()
        db.query(Conversation).filter(Conversation.id == conv_id).delete()
        db.query(Message).filter(Message.conversation_id == orphan_id).delete()
        db.query(Conversation).filter(Conversation.id == orphan_id).delete()
        db.query(AuthToken).filter(AuthToken.user_id.in_(uids)).delete(synchronize_session=False)
        db.query(User).filter(User.username.in_([u1, a1, u2])).delete(synchronize_session=False)
        db.commit()
    print("测试数据已清理")
finally:
    c.close()

failed = [r for r in results if not r[1]]
print(f"\n结果: {len(results) - len(failed)}/{len(results)} 通过")
if failed:
    print("失败项:", [f[0] for f in failed])
    sys.exit(1)
