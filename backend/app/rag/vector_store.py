"""向量库封装：ChromaDB 持久化，全局单例。

对外只暴露业务需要的操作（upsert / query / delete / count），
屏蔽 chromadb SDK 细节，便于未来替换为 Milvus / Qdrant / ES。
"""
from typing import Optional

import chromadb

from app.config import settings
from app.utils.logger import logger

_instances: dict[str, "VectorStore"] = {}


class VectorStore:
    def __init__(self) -> None:
        self._client = chromadb.PersistentClient(path=settings.CHROMA_PERSIST_DIR)
        self.collection = self._client.get_or_create_collection(
            name=settings.COLLECTION_NAME,
            metadata={"hnsw:space": "cosine"},
        )
        logger.info(
            "向量库就绪: collection=%s, 现有向量=%s",
            settings.COLLECTION_NAME,
            self.collection.count(),
        )

    @classmethod
    def get(cls) -> "VectorStore":
        if "default" not in _instances:
            _instances["default"] = cls()
        return _instances["default"]

    def upsert(
        self,
        ids: list[str],
        embeddings: list[list[float]],
        documents: list[str],
        metadatas: list[dict],
    ) -> None:
        self.collection.upsert(
            ids=ids, embeddings=embeddings, documents=documents, metadatas=metadatas
        )

    def query(
        self,
        query_embedding: list[float],
        top_k: int,
        where: Optional[dict] = None,
    ) -> dict:
        kwargs: dict = {"query_embeddings": [query_embedding], "n_results": top_k}
        if where:
            kwargs["where"] = where
        return self.collection.query(**kwargs)

    def delete_document(self, document_id: str) -> None:
        self.collection.delete(where={"document_id": document_id})

    def count(self) -> int:
        return self.collection.count()

    def get_all(self, include_docs: bool = True) -> dict:
        include = ["metadatas"]
        if include_docs:
            include.append("documents")
        return self.collection.get(include=include)
