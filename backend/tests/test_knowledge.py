from pathlib import Path

import pytest
from mergescope.db.repository import ReviewRepository
from mergescope.services.knowledge import KnowledgeRetriever, KnowledgeService, chunk_document


class FakeEmbedder:
    async def embed(self, texts: list[str]) -> list[list[float]]:
        return [[1.0, 0.0] if "security" in text.lower() else [0.0, 1.0] for text in texts]


def test_chunk_document_preserves_headings_and_splits_large_sections() -> None:
    content = "# Security\n" + ("Validate tokens carefully. " * 100) + "\n# Style\nUse Ruff."

    chunks = chunk_document(content, max_chars=300, overlap_chars=30)

    assert len(chunks) > 2
    assert chunks[0][0] == "Security"
    assert chunks[-1] == ("Style", "Use Ruff.")


async def test_documents_are_deduplicated_retrieved_and_deleted(tmp_path: Path) -> None:
    repository = ReviewRepository(tmp_path / "reviews.db")
    await repository.initialize()
    embedder = FakeEmbedder()
    service = KnowledgeService(repository, embedder, "fake-embedding", 1_000_000)
    payload = b"# Security\nRotate security tokens.\n# Style\nUse Ruff for Python."

    first = await service.ingest("standards.md", "text/markdown", payload)
    duplicate = await service.ingest("copy.md", "text/markdown", payload)
    sources = await KnowledgeRetriever(repository, embedder, top_k=1).retrieve(
        "security token changes"
    )

    assert duplicate.id == first.id
    assert (await repository.list_documents()).total == 1
    assert len(sources) == 1
    assert "Security" in sources[0].name
    assert sources[0].relevance_score == 1.0
    assert await repository.delete_document(first.id) is True
    assert await repository.all_chunks() == []


async def test_ingestion_rejects_unsupported_and_oversized_documents(tmp_path: Path) -> None:
    repository = ReviewRepository(tmp_path / "reviews.db")
    await repository.initialize()
    service = KnowledgeService(repository, FakeEmbedder(), "fake-embedding", 10)

    with pytest.raises(ValueError, match="Markdown"):
        await service.ingest("rules.pdf", "application/pdf", b"content")
    with pytest.raises(ValueError, match="exceeds"):
        await service.ingest("rules.md", "text/markdown", b"more than ten bytes")
