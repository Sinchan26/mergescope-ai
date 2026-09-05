from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import aiosqlite

from mergescope.domain.models import (
    KnowledgeChunk,
    KnowledgeDocument,
    KnowledgeDocumentList,
    ReviewList,
    ReviewResult,
    ReviewRun,
    ReviewStatus,
)

BASE_SCHEMA = """
CREATE TABLE IF NOT EXISTS review_runs (
    id TEXT PRIMARY KEY,
    repository TEXT,
    pr_number INTEGER,
    pr_url TEXT NOT NULL,
    head_sha TEXT,
    title TEXT,
    author TEXT,
    status TEXT NOT NULL,
    dry_run INTEGER NOT NULL,
    ticket_reference TEXT,
    result_json TEXT,
    issue_count INTEGER NOT NULL DEFAULT 0,
    model TEXT,
    input_tokens INTEGER,
    output_tokens INTEGER,
    latency_ms INTEGER,
    error_message TEXT,
    cache_key TEXT,
    cache_hit INTEGER NOT NULL DEFAULT 0,
    cached_from_id TEXT,
    prompt_version TEXT,
    demo_mode INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS knowledge_documents (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    content_hash TEXT NOT NULL UNIQUE,
    content_type TEXT NOT NULL,
    size_bytes INTEGER NOT NULL,
    chunk_count INTEGER NOT NULL,
    embedding_model TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS document_chunks (
    id TEXT PRIMARY KEY,
    document_id TEXT NOT NULL REFERENCES knowledge_documents(id) ON DELETE CASCADE,
    position INTEGER NOT NULL,
    heading TEXT,
    content TEXT NOT NULL,
    embedding_json TEXT NOT NULL,
    UNIQUE(document_id, position)
);
"""

INDEX_SCHEMA = """
CREATE INDEX IF NOT EXISTS idx_review_runs_created_at
    ON review_runs(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_review_runs_pull_request
    ON review_runs(repository, pr_number, head_sha);
CREATE INDEX IF NOT EXISTS idx_review_runs_status
    ON review_runs(status);
CREATE INDEX IF NOT EXISTS idx_review_runs_cache
    ON review_runs(cache_key, created_at DESC)
    WHERE status = 'completed';
CREATE INDEX IF NOT EXISTS idx_document_chunks_document_id
    ON document_chunks(document_id, position);
"""

REVIEW_COLUMN_MIGRATIONS = {
    "cache_key": "TEXT",
    "cache_hit": "INTEGER NOT NULL DEFAULT 0",
    "cached_from_id": "TEXT",
    "prompt_version": "TEXT",
    "demo_mode": "INTEGER NOT NULL DEFAULT 0",
}


class ReviewRepository:
    def __init__(self, database_path: Path) -> None:
        self.database_path = database_path

    async def initialize(self) -> None:
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        async with aiosqlite.connect(self.database_path) as connection:
            await connection.execute("PRAGMA foreign_keys=ON")
            await connection.executescript(BASE_SCHEMA)
            await self._migrate_review_columns(connection)
            await connection.executescript(INDEX_SCHEMA)
            await connection.execute("PRAGMA journal_mode=WAL")
            await connection.execute("PRAGMA optimize")
            await connection.commit()

    async def _migrate_review_columns(self, connection: aiosqlite.Connection) -> None:
        cursor = await connection.execute("PRAGMA table_info(review_runs)")
        existing = {row[1] for row in await cursor.fetchall()}
        for name, definition in REVIEW_COLUMN_MIGRATIONS.items():
            if name not in existing:
                await connection.execute(f"ALTER TABLE review_runs ADD COLUMN {name} {definition}")

    async def ping(self) -> bool:
        try:
            async with aiosqlite.connect(self.database_path) as connection:
                await connection.execute("SELECT 1")
            return True
        except aiosqlite.Error:
            return False

    async def create(self, run: ReviewRun) -> ReviewRun:
        async with aiosqlite.connect(self.database_path) as connection:
            await connection.execute(
                """
                INSERT INTO review_runs (
                    id, repository, pr_number, pr_url, head_sha, title, author, status,
                    dry_run, ticket_reference, result_json, issue_count, model,
                    input_tokens, output_tokens, latency_ms, error_message, cache_key,
                    cache_hit, cached_from_id, prompt_version, demo_mode, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                self._values(run),
            )
            await connection.commit()
        return run

    async def save(self, run: ReviewRun) -> ReviewRun:
        run.updated_at = datetime.now(UTC)
        async with aiosqlite.connect(self.database_path) as connection:
            await connection.execute(
                """
                UPDATE review_runs SET
                    repository = ?, pr_number = ?, pr_url = ?, head_sha = ?, title = ?,
                    author = ?, status = ?, dry_run = ?, ticket_reference = ?,
                    result_json = ?, issue_count = ?, model = ?, input_tokens = ?,
                    output_tokens = ?, latency_ms = ?, error_message = ?, cache_key = ?,
                    cache_hit = ?, cached_from_id = ?, prompt_version = ?, demo_mode = ?,
                    updated_at = ?
                WHERE id = ?
                """,
                (
                    run.repository,
                    run.pr_number,
                    run.pr_url,
                    run.head_sha,
                    run.title,
                    run.author,
                    run.status.value,
                    int(run.dry_run),
                    run.ticket_reference,
                    run.result.model_dump_json() if run.result else None,
                    run.issue_count,
                    run.model,
                    run.input_tokens,
                    run.output_tokens,
                    run.latency_ms,
                    run.error_message,
                    run.cache_key,
                    int(run.cache_hit),
                    run.cached_from_id,
                    run.prompt_version,
                    int(run.demo_mode),
                    run.updated_at.isoformat(),
                    run.id,
                ),
            )
            await connection.commit()
        return run

    async def get(self, review_id: str) -> ReviewRun | None:
        async with aiosqlite.connect(self.database_path) as connection:
            connection.row_factory = aiosqlite.Row
            cursor = await connection.execute(
                "SELECT * FROM review_runs WHERE id = ?", (review_id,)
            )
            row = await cursor.fetchone()
        return self._review_from_row(row) if row else None

    async def find_cached(self, cache_key: str) -> ReviewRun | None:
        async with aiosqlite.connect(self.database_path) as connection:
            connection.row_factory = aiosqlite.Row
            cursor = await connection.execute(
                """
                SELECT * FROM review_runs
                WHERE cache_key = ? AND status = 'completed' AND demo_mode = 0
                ORDER BY created_at DESC LIMIT 1
                """,
                (cache_key,),
            )
            row = await cursor.fetchone()
        return self._review_from_row(row) if row else None

    async def list(self, limit: int = 25, offset: int = 0) -> ReviewList:
        async with aiosqlite.connect(self.database_path) as connection:
            connection.row_factory = aiosqlite.Row
            cursor = await connection.execute(
                "SELECT * FROM review_runs ORDER BY created_at DESC LIMIT ? OFFSET ?",
                (limit, offset),
            )
            rows = await cursor.fetchall()
            count_cursor = await connection.execute("SELECT COUNT(*) FROM review_runs")
            total = (await count_cursor.fetchone())[0]
        return ReviewList(items=[self._review_from_row(row) for row in rows], total=total)

    async def create_document(
        self,
        document: KnowledgeDocument,
        content_hash: str,
        chunks: list[KnowledgeChunk],
    ) -> KnowledgeDocument:
        async with aiosqlite.connect(self.database_path) as connection:
            await connection.execute("PRAGMA foreign_keys=ON")
            await connection.execute(
                """
                INSERT INTO knowledge_documents (
                    id, name, content_hash, content_type, size_bytes, chunk_count,
                    embedding_model, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    document.id,
                    document.name,
                    content_hash,
                    document.content_type,
                    document.size_bytes,
                    document.chunk_count,
                    document.embedding_model,
                    document.created_at.isoformat(),
                ),
            )
            await connection.executemany(
                """
                INSERT INTO document_chunks (
                    id, document_id, position, heading, content, embedding_json
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        chunk.id,
                        chunk.document_id,
                        chunk.position,
                        chunk.heading,
                        chunk.content,
                        json.dumps(chunk.embedding),
                    )
                    for chunk in chunks
                ],
            )
            await connection.commit()
        return document

    async def find_document_by_hash(self, content_hash: str) -> KnowledgeDocument | None:
        async with aiosqlite.connect(self.database_path) as connection:
            connection.row_factory = aiosqlite.Row
            cursor = await connection.execute(
                "SELECT * FROM knowledge_documents WHERE content_hash = ?", (content_hash,)
            )
            row = await cursor.fetchone()
        return self._document_from_row(row) if row else None

    async def list_documents(self) -> KnowledgeDocumentList:
        async with aiosqlite.connect(self.database_path) as connection:
            connection.row_factory = aiosqlite.Row
            cursor = await connection.execute(
                "SELECT * FROM knowledge_documents ORDER BY created_at DESC"
            )
            rows = await cursor.fetchall()
        items = [self._document_from_row(row) for row in rows]
        return KnowledgeDocumentList(items=items, total=len(items))

    async def delete_document(self, document_id: str) -> bool:
        async with aiosqlite.connect(self.database_path) as connection:
            await connection.execute("PRAGMA foreign_keys=ON")
            cursor = await connection.execute(
                "DELETE FROM knowledge_documents WHERE id = ?", (document_id,)
            )
            await connection.commit()
        return cursor.rowcount > 0

    async def all_chunks(self) -> list[KnowledgeChunk]:
        async with aiosqlite.connect(self.database_path) as connection:
            connection.row_factory = aiosqlite.Row
            cursor = await connection.execute(
                """
                SELECT c.*, d.name AS document_name
                FROM document_chunks c
                JOIN knowledge_documents d ON d.id = c.document_id
                ORDER BY d.created_at DESC, c.position
                """
            )
            rows = await cursor.fetchall()
        return [
            KnowledgeChunk(
                id=row["id"],
                document_id=row["document_id"],
                document_name=row["document_name"],
                position=row["position"],
                heading=row["heading"],
                content=row["content"],
                embedding=json.loads(row["embedding_json"]),
            )
            for row in rows
        ]

    async def document_count(self) -> int:
        async with aiosqlite.connect(self.database_path) as connection:
            cursor = await connection.execute("SELECT COUNT(*) FROM knowledge_documents")
            return (await cursor.fetchone())[0]

    @staticmethod
    def _values(run: ReviewRun) -> tuple[object, ...]:
        return (
            run.id,
            run.repository,
            run.pr_number,
            run.pr_url,
            run.head_sha,
            run.title,
            run.author,
            run.status.value,
            int(run.dry_run),
            run.ticket_reference,
            run.result.model_dump_json() if run.result else None,
            run.issue_count,
            run.model,
            run.input_tokens,
            run.output_tokens,
            run.latency_ms,
            run.error_message,
            run.cache_key,
            int(run.cache_hit),
            run.cached_from_id,
            run.prompt_version,
            int(run.demo_mode),
            run.created_at.isoformat(),
            run.updated_at.isoformat(),
        )

    @staticmethod
    def _review_from_row(row: aiosqlite.Row) -> ReviewRun:
        result = ReviewRepository._parse_result(row["result_json"])
        keys = set(row.keys())
        return ReviewRun(
            id=row["id"],
            repository=row["repository"],
            pr_number=row["pr_number"],
            pr_url=row["pr_url"],
            head_sha=row["head_sha"],
            title=row["title"],
            author=row["author"],
            status=ReviewStatus(row["status"]),
            dry_run=bool(row["dry_run"]),
            ticket_reference=row["ticket_reference"],
            result=result,
            issue_count=row["issue_count"],
            model=row["model"],
            input_tokens=row["input_tokens"],
            output_tokens=row["output_tokens"],
            latency_ms=row["latency_ms"],
            error_message=row["error_message"],
            cache_key=row["cache_key"] if "cache_key" in keys else None,
            cache_hit=bool(row["cache_hit"]) if "cache_hit" in keys else False,
            cached_from_id=row["cached_from_id"] if "cached_from_id" in keys else None,
            prompt_version=row["prompt_version"] if "prompt_version" in keys else None,
            demo_mode=bool(row["demo_mode"]) if "demo_mode" in keys else False,
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
        )

    @staticmethod
    def _parse_result(value: str | None) -> ReviewResult | None:
        if not value:
            return None
        payload: dict[str, Any] = json.loads(value)
        for issue in payload.get("issues", []):
            issue.setdefault("agent", "code_reviewer")
            issue.setdefault("line_validated", False)
            issue.setdefault("diff_excerpt", None)
        payload.setdefault("agents_run", ["code_reviewer"])
        payload.setdefault("context_sources", [])
        payload.setdefault("rejected_issue_count", 0)
        return ReviewResult.model_validate(payload)

    @staticmethod
    def _document_from_row(row: aiosqlite.Row) -> KnowledgeDocument:
        return KnowledgeDocument(
            id=row["id"],
            name=row["name"],
            content_type=row["content_type"],
            size_bytes=row["size_bytes"],
            chunk_count=row["chunk_count"],
            embedding_model=row["embedding_model"],
            created_at=datetime.fromisoformat(row["created_at"]),
        )
