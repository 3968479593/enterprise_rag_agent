"""文档入库服务：解析 → 切分 → 向量化 → 持久化（向量库 + 数据库）。

对外暴露两个稳定的业务入口：
- ingest(db, filename, raw_bytes) -> Document
- delete_document(db, doc)
"""
from pathlib import Path

from sqlalchemy.orm import Session

from app.config import settings
from app.rag.document_processor import parse_file, safe_filename
from app.rag.embedding import EmbeddingClient
from app.rag.retriever import HybridRetriever
from app.models.orm import Chunk, Document
from app.utils.chunker import split_text
from app.utils import new_id
from app.utils.logger import logger


class IngestionService:
    def __init__(self) -> None:
        self.emb = EmbeddingClient()
        self.retriever = HybridRetriever()

    def ingest(self, db: Session, filename: str, raw: bytes) -> Document:
        safe_name = safe_filename(filename)
        text, source_type = parse_file(safe_name, raw)

        doc_id = new_id("doc")
        doc = Document(
            id=doc_id,
            filename=safe_name,
            source_type=source_type,
            status="ingesting",
            meta={"char_count": len(text)},
        )
        db.add(doc)
        db.commit()

        try:
            chunks = split_text(text, chunk_size=settings.CHUNK_SIZE, overlap=settings.CHUNK_OVERLAP)
            if not chunks:
                raise ValueError("未提取到有效文本，无法切分")

            ids = [f"{doc_id}_c{i:04d}" for i in range(len(chunks))]
            contents = [c.content for c in chunks]
            vectors = self.emb.embed_texts(contents)
            metadatas = [
                {
                    "document_id": doc_id,
                    "filename": safe_name,
                    "source_type": source_type,
                    "chunk_index": c.index,
                }
                for c in chunks
            ]

            self.retriever.vs.upsert(ids=ids, embeddings=vectors, documents=contents, metadatas=metadatas)
            self.retriever.invalidate()

            db.add_all(
                [
                    Chunk(
                        id=ids[i],
                        document_id=doc_id,
                        index=chunks[i].index,
                        content=contents[i],
                        token_estimate=chunks[i].token_estimate,
                        meta={"char_count": len(contents[i])},
                    )
                    for i in range(len(chunks))
                ]
            )
            doc.status = "ingested"
            doc.chunk_count = len(chunks)
            doc.error = None
            db.commit()
            logger.info("文档入库完成: %s (%s 块)", safe_name, len(chunks))
        except Exception as exc:  # noqa: BLE001
            db.rollback()
            failed = db.get(Document, doc_id)
            if failed is not None:
                failed.status = "failed"
                failed.error = str(exc)[:2000]
                db.commit()
            logger.exception("文档入库失败: %s", safe_name)
            raise

        return doc

    def delete_document(self, db: Session, doc: Document) -> None:
        self.retriever.vs.delete_document(doc.id)
        self.retriever.invalidate()
        db.delete(doc)
        db.commit()


def save_upload(filename: str, raw: bytes) -> Path:
    """把上传文件落盘到 data/uploads（保留原始文件，便于审计与重入库）。"""
    upload_dir = Path(settings.UPLOAD_DIR)
    upload_dir.mkdir(parents=True, exist_ok=True)
    target = upload_dir / f"{new_id('f')}_{safe_filename(filename)}"
    target.write_bytes(raw)
    return target
