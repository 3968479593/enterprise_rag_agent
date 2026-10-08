"""文档管理接口：上传 / 列表 / 删除。"""
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from sqlalchemy.orm import Session

from app.config import settings
from app.models.database import get_db
from app.models.orm import Document
from app.models.schemas import DeleteResponse, DocumentOut, UploadResponse
from app.rag.ingestion import IngestionService, save_upload
from app.utils.logger import logger

router = APIRouter()
ingestion = IngestionService()

_ALLOWED_EXTENSIONS = {".txt", ".md", ".pdf", ".docx", ".csv", ".json"}


@router.post("/upload", response_model=UploadResponse, status_code=status.HTTP_201_CREATED)
def upload_document(
    file: UploadFile = File(..., description="支持 txt/md/pdf/docx/csv/json"),
    db: Session = Depends(get_db),
) -> UploadResponse:
    """上传并解析文档，切块后向量化入库，原始文件落盘 data/uploads。"""
    max_bytes = settings.MAX_UPLOAD_SIZE_MB * 1024 * 1024
    raw = file.file.read(max_bytes + 1)
    if len(raw) > max_bytes:
        raise HTTPException(status_code=413, detail=f"文件超过 {settings.MAX_UPLOAD_SIZE_MB}MB 限制")

    from app.rag.document_processor import safe_filename

    filename = safe_filename(file.filename or "unnamed.txt")
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if f".{ext}" not in _ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"不支持的文件类型 .{ext}，支持: txt / md / pdf / docx / csv / json",
        )

    try:
        save_upload(filename, raw)
        doc = ingestion.ingest(db, filename, raw)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        logger.exception("文档入库异常: %s", filename)
        # 不把内部异常细节回显给前端（详情保留在服务端日志）
        raise HTTPException(status_code=500, detail="文档解析/入库失败，请检查文件内容或格式后重试") from exc

    return UploadResponse(
        document_id=doc.id,
        filename=doc.filename,
        source_type=doc.source_type,
        status=doc.status,
        chunk_count=doc.chunk_count,
        char_count=int(doc.meta.get("char_count", 0)),
        created_at=doc.created_at,
    )


@router.get("", response_model=list[DocumentOut])
def list_documents(db: Session = Depends(get_db)) -> list[Document]:
    return db.query(Document).order_by(Document.created_at.desc()).limit(200).all()


@router.delete("/{document_id}", response_model=DeleteResponse)
def delete_document(document_id: str, db: Session = Depends(get_db)) -> DeleteResponse:
    doc = db.get(Document, document_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="文档不存在")
    try:
        ingestion.delete_document(db, doc)
    except Exception as exc:  # noqa: BLE001
        logger.exception("删除文档异常: %s", document_id)
        raise HTTPException(status_code=500, detail="删除失败，请稍后重试") from exc
    return DeleteResponse(document_id=document_id, deleted=True)
