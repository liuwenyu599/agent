"""知识库仓储接口。"""
from typing import List, Optional

from app.domain.base import Repository
from app.domain.knowledge.entities import DocumentChunk, KnowledgeBase, KnowledgeDocument


class KnowledgeBaseRepository(Repository[KnowledgeBase]):
    def list_accessible(self, user_id: str, user_role: str) -> List[KnowledgeBase]:
        raise NotImplementedError

    def get_personal_kb(self, user_id: str) -> Optional[KnowledgeBase]:
        raise NotImplementedError

    def count_active(self) -> int:
        raise NotImplementedError

    def update(self, kb: KnowledgeBase) -> KnowledgeBase:
        raise NotImplementedError


class DocumentRepository(Repository[KnowledgeDocument]):
    def list_by_kb(self, kb_id: str, status: Optional[str] = None,
                   page: int = 1, page_size: int = 20) -> tuple:
        """返回 (total, items)。"""
        raise NotImplementedError

    def list_by_status(self, status: str) -> List[KnowledgeDocument]:
        raise NotImplementedError

    def list_all(self, status: Optional[str] = None, page: int = 1, page_size: int = 20) -> tuple:
        raise NotImplementedError

    def find_by_source_url(self, source_url: str) -> Optional[KnowledgeDocument]:
        raise NotImplementedError

    def count(self, status: Optional[str] = None) -> int:
        raise NotImplementedError

    def update(self, doc: KnowledgeDocument) -> KnowledgeDocument:
        raise NotImplementedError


class ChunkRepository(Repository[DocumentChunk]):
    def list_by_document(self, doc_id: str) -> List[DocumentChunk]:
        raise NotImplementedError

    def add_many(self, chunks: List[DocumentChunk]) -> None:
        raise NotImplementedError
