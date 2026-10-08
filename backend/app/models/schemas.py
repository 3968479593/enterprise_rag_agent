"""Pydantic 请求/响应模型：集中定义，与 ORM 模型分离。"""
from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field


# ---------- 文档 ----------

class UploadResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    document_id: str
    filename: str
    source_type: str
    status: str
    chunk_count: int
    char_count: int
    created_at: datetime


class DocumentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    filename: str
    source_type: str
    status: str
    chunk_count: int
    meta: dict[str, Any]
    error: Optional[str]
    created_at: datetime


class DeleteResponse(BaseModel):
    document_id: str
    deleted: bool


# ---------- 问答 ----------

class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=8000, description="用户问题")
    conversation_id: Optional[str] = Field(None, description="会话 ID，不传则自动创建新会话")
    top_k: int = Field(5, ge=1, le=20, description="检索返回的切块数量")
    use_agent: bool = Field(True, description="是否启用 ReAct Agent（False 为直接问答）")
    threshold: Optional[float] = Field(None, ge=0.0, le=1.0, description="检索分数阈值")


class SourceRef(BaseModel):
    chunk_id: str
    document_id: str
    filename: str
    score: float
    snippet: str


class ChatResponse(BaseModel):
    answer: str
    conversation_id: str
    message_id: str
    sources: list[SourceRef]
    trace: Optional[dict[str, Any]]
    latency_ms: int
    model: str


# ---------- 会话历史 ----------

class MessageOut(BaseModel):
    id: str
    role: str
    content: str
    sources: Optional[list[dict]]
    trace: Optional[dict[str, Any]]
    latency_ms: Optional[int]
    feedback: Optional[str] = None
    feedback_shared: Optional[bool] = False
    feedback_note: Optional[str] = None
    created_at: datetime


class ConversationOut(BaseModel):
    id: str
    title: str
    created_at: datetime
    updated_at: datetime
    message_count: int


class ConversationDetail(BaseModel):
    id: str
    title: str
    messages: list[MessageOut]


class DeleteConversationResponse(BaseModel):
    conversation_id: str
    deleted: bool


# ---------- 评估 ----------

class EvalQuestion(BaseModel):
    question: str = Field(..., min_length=1, description="评测问题")
    ground_truth: str = Field("", description="标准答案（用于检索层指标）")


class EvalRunRequest(BaseModel):
    name: str = Field("eval", max_length=256)
    questions: list[EvalQuestion] = Field(..., min_length=1)
    top_k: int = Field(5, ge=1, le=20)


class EvalRunResponse(BaseModel):
    run_id: str
    name: str
    metrics: dict[str, Any]
    dataset_size: int
    created_at: datetime


class EvalRunOut(BaseModel):
    id: str
    name: str
    metrics: Optional[dict[str, Any]]
    dataset_size: int
    created_at: datetime
