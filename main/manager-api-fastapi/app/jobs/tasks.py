from __future__ import annotations

from app.core.config import get_settings
from app.core.database import get_session_factory
from app.core.redis import distributed_lock
from app.repositories.knowledge import KnowledgeRepository
from app.services.knowledge import KnowledgeDocumentService


async def sync_running_knowledge_documents() -> int:
    """Run one document-status pass under a cross-process Redis lock."""

    settings = get_settings()
    async with distributed_lock("jobs:knowledge-document-status", settings.job_lock_ttl_seconds) as acquired:
        if not acquired:
            return 0
        async with get_session_factory()() as session:
            return await KnowledgeDocumentService(KnowledgeRepository(session)).sync_running()
