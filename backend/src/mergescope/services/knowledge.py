import hashlib
import math
import re
from datetime import UTC, datetime
from pathlib import PurePath
from uuid import uuid4

from mergescope.db.repository import ReviewRepository
from mergescope.domain.models import ContextSource, KnowledgeChunk, KnowledgeDocument
from mergescope.integrations.embeddings import Embedder

ALLOWED_EXTENSIONS = {".md", ".markdown", ".txt"}
HEADING = re.compile(r"^(#{1,6})\s+(.+)$")


def chunk_document(
    content: str, max_chars: int = 1_400, overlap_chars: int = 180
) -> list[tuple[str | None, str]]:
    sections: list[tuple[str | None, str]] = []
    heading: str | None = None
    buffer: list[str] = []

    def flush() -> None:
        nonlocal buffer
        text = "\n".join(buffer).strip()
        if text:
            sections.extend(_split_section(heading, text, max_chars, overlap_chars))
        buffer = []

    for line in content.splitlines():
        match = HEADING.match(line.strip())
        if match:
            flush()
            heading = match.group(2).strip()
        else:
            buffer.append(line)
    flush()
    return sections or [(None, content.strip())]


def _split_section(
    heading: str | None, text: str, max_chars: int, overlap_chars: int
) -> list[tuple[str | None, str]]:
    chunks: list[tuple[str | None, str]] = []
    remaining = text
    while remaining:
        if len(remaining) <= max_chars:
            chunks.append((heading, remaining.strip()))
            break
        split_at = remaining.rfind("\n\n", 0, max_chars)
        if split_at < max_chars // 2:
            split_at = remaining.rfind(" ", 0, max_chars)
        if split_at <= 0:
            split_at = max_chars
        part = remaining[:split_at].strip()
        if part:
            chunks.append((heading, part))
        restart = max(0, split_at - overlap_chars)
        remaining = remaining[restart:].strip()
    return chunks


class KnowledgeService:
    def __init__(
        self,
        repository: ReviewRepository,
        embedder: Embedder | None,
        embedding_model: str,
        max_document_bytes: int,
    ) -> None:
        self.repository = repository
        self.embedder = embedder
        self.embedding_model = embedding_model
        self.max_document_bytes = max_document_bytes

    async def ingest(self, filename: str, content_type: str, payload: bytes) -> KnowledgeDocument:
        suffix = PurePath(filename).suffix.lower()
        if suffix not in ALLOWED_EXTENSIONS:
            raise ValueError("Only Markdown and plain-text documents are supported.")
        if not payload:
            raise ValueError("The selected document is empty.")
        if len(payload) > self.max_document_bytes:
            raise ValueError(
                f"Document exceeds the {self.max_document_bytes // 1_000_000} MB limit."
            )
        if self.embedder is None:
            raise ValueError("OPENAI_API_KEY is required to index knowledge documents.")
        try:
            content = payload.decode("utf-8").strip()
        except UnicodeDecodeError as exc:
            raise ValueError("The document must use UTF-8 text encoding.") from exc
        if not content:
            raise ValueError("The selected document contains no readable text.")

        content_hash = hashlib.sha256(payload).hexdigest()
        existing = await self.repository.find_document_by_hash(content_hash)
        if existing:
            return existing

        raw_chunks = chunk_document(content)
        vectors = await self.embedder.embed(
            [f"{heading}\n{text}" if heading else text for heading, text in raw_chunks]
        )
        document_id = str(uuid4())
        created_at = datetime.now(UTC)
        document = KnowledgeDocument(
            id=document_id,
            name=PurePath(filename).name,
            content_type=content_type or "text/plain",
            size_bytes=len(payload),
            chunk_count=len(raw_chunks),
            embedding_model=self.embedding_model,
            created_at=created_at,
        )
        chunks = [
            KnowledgeChunk(
                id=str(uuid4()),
                document_id=document_id,
                document_name=document.name,
                position=position,
                heading=heading,
                content=text,
                embedding=vector,
            )
            for position, ((heading, text), vector) in enumerate(
                zip(raw_chunks, vectors, strict=True)
            )
        ]
        return await self.repository.create_document(document, content_hash, chunks)


class KnowledgeRetriever:
    def __init__(
        self, repository: ReviewRepository, embedder: Embedder | None, top_k: int = 5
    ) -> None:
        self.repository = repository
        self.embedder = embedder
        self.top_k = top_k

    async def retrieve(self, query: str) -> list[ContextSource]:
        if self.embedder is None:
            return []
        chunks = await self.repository.all_chunks()
        if not chunks:
            return []
        query_vector = (await self.embedder.embed([query]))[0]
        ranked = sorted(
            ((_cosine_similarity(query_vector, chunk.embedding), chunk) for chunk in chunks),
            key=lambda item: item[0],
            reverse=True,
        )[: self.top_k]
        return [
            ContextSource(
                source_id=f"document:{chunk.id}",
                name=(
                    f"{chunk.document_name} · {chunk.heading}"
                    if chunk.heading
                    else chunk.document_name
                ),
                source_type="knowledge_document",
                excerpt=chunk.content[:1_500],
                relevance_score=round(score, 4),
            )
            for score, chunk in ranked
            if score > 0
        ]


def _cosine_similarity(left: list[float], right: list[float]) -> float:
    if len(left) != len(right) or not left:
        return 0.0
    dot_product = sum(a * b for a, b in zip(left, right, strict=True))
    left_norm = math.sqrt(sum(value * value for value in left))
    right_norm = math.sqrt(sum(value * value for value in right))
    if not left_norm or not right_norm:
        return 0.0
    return dot_product / (left_norm * right_norm)
