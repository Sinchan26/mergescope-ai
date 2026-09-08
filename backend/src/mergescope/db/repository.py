from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import aiosqlite

from mergescope.domain.models import (
    EvaluationRun,
    EvaluationRunList,
    EvaluationStatus,
    JobStatus,
    KnowledgeChunk,
    KnowledgeDocument,
    KnowledgeDocumentList,
    PublicationStatus,
    ReviewJob,
    ReviewJobList,
    ReviewList,
    ReviewResult,
    ReviewRun,
    ReviewStatus,
    TriggerSource,
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
    trigger_source TEXT NOT NULL DEFAULT 'manual',
    job_id TEXT,
    publication_status TEXT NOT NULL DEFAULT 'not_published',
    github_review_id INTEGER,
    published_at TEXT,
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
CREATE TABLE IF NOT EXISTS review_jobs (
    id TEXT PRIMARY KEY,
    idempotency_key TEXT NOT NULL UNIQUE,
    delivery_id TEXT NOT NULL,
    repository TEXT NOT NULL,
    pr_number INTEGER NOT NULL,
    pr_url TEXT NOT NULL,
    head_sha TEXT NOT NULL,
    installation_id INTEGER,
    correlation_id TEXT,
    status TEXT NOT NULL,
    attempts INTEGER NOT NULL DEFAULT 0,
    max_attempts INTEGER NOT NULL DEFAULT 3,
    available_at TEXT NOT NULL,
    locked_at TEXT,
    error_message TEXT,
    review_id TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS webhook_deliveries (
    delivery_id TEXT PRIMARY KEY,
    event_name TEXT NOT NULL,
    action TEXT,
    repository TEXT,
    pr_number INTEGER,
    head_sha TEXT,
    job_id TEXT,
    received_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS evaluation_runs (
    id TEXT PRIMARY KEY,
    status TEXT NOT NULL,
    dataset_version TEXT NOT NULL,
    model TEXT NOT NULL,
    prompt_version TEXT NOT NULL,
    case_count INTEGER NOT NULL,
    completed_cases INTEGER NOT NULL DEFAULT 0,
    true_positives INTEGER NOT NULL DEFAULT 0,
    false_positives INTEGER NOT NULL DEFAULT 0,
    false_negatives INTEGER NOT NULL DEFAULT 0,
    invalid_findings INTEGER NOT NULL DEFAULT 0,
    accepted_findings INTEGER NOT NULL DEFAULT 0,
    precision REAL NOT NULL DEFAULT 0,
    recall REAL NOT NULL DEFAULT 0,
    invalid_line_rate REAL NOT NULL DEFAULT 0,
    input_tokens INTEGER NOT NULL DEFAULT 0,
    output_tokens INTEGER NOT NULL DEFAULT 0,
    latency_ms INTEGER NOT NULL DEFAULT 0,
    estimated_cost_usd REAL NOT NULL DEFAULT 0,
    results_json TEXT NOT NULL DEFAULT '[]',
    error_message TEXT,
    created_at TEXT NOT NULL,
    completed_at TEXT
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
CREATE INDEX IF NOT EXISTS idx_review_jobs_available
    ON review_jobs(status, available_at, created_at);
CREATE INDEX IF NOT EXISTS idx_review_jobs_pull_request
    ON review_jobs(repository, pr_number, head_sha);
CREATE INDEX IF NOT EXISTS idx_evaluation_runs_created_at
    ON evaluation_runs(created_at DESC);
"""

REVIEW_COLUMN_MIGRATIONS = {
    "cache_key": "TEXT",
    "cache_hit": "INTEGER NOT NULL DEFAULT 0",
    "cached_from_id": "TEXT",
    "prompt_version": "TEXT",
    "demo_mode": "INTEGER NOT NULL DEFAULT 0",
    "trigger_source": "TEXT NOT NULL DEFAULT 'manual'",
    "job_id": "TEXT",
    "publication_status": "TEXT NOT NULL DEFAULT 'not_published'",
    "github_review_id": "INTEGER",
    "published_at": "TEXT",
}

JOB_COLUMN_MIGRATIONS = {
    "correlation_id": "TEXT",
}


class ReviewRepository:
    def __init__(self, database_path: Path) -> None:
        self.database_path = database_path

    async def initialize(self) -> None:
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        async with aiosqlite.connect(self.database_path) as connection:
            await connection.execute("PRAGMA foreign_keys=ON")
            await connection.execute("PRAGMA busy_timeout=30000")
            await connection.executescript(BASE_SCHEMA)
            await self._migrate_review_columns(connection)
            await self._migrate_job_columns(connection)
            await connection.executescript(INDEX_SCHEMA)
            await connection.execute("PRAGMA journal_mode=WAL")
            now = datetime.now(UTC).isoformat()
            await connection.execute(
                """
                UPDATE evaluation_runs
                SET status = 'failed', error_message = 'Evaluation interrupted by process restart.',
                    completed_at = ?
                WHERE status = 'running'
                """,
                (now,),
            )
            await connection.execute("PRAGMA optimize")
            await connection.commit()

    async def _migrate_review_columns(self, connection: aiosqlite.Connection) -> None:
        cursor = await connection.execute("PRAGMA table_info(review_runs)")
        existing = {row[1] for row in await cursor.fetchall()}
        for name, definition in REVIEW_COLUMN_MIGRATIONS.items():
            if name not in existing:
                await connection.execute(f"ALTER TABLE review_runs ADD COLUMN {name} {definition}")

    async def _migrate_job_columns(self, connection: aiosqlite.Connection) -> None:
        cursor = await connection.execute("PRAGMA table_info(review_jobs)")
        existing = {row[1] for row in await cursor.fetchall()}
        for name, definition in JOB_COLUMN_MIGRATIONS.items():
            if name not in existing:
                await connection.execute(f"ALTER TABLE review_jobs ADD COLUMN {name} {definition}")

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
                    cache_hit, cached_from_id, prompt_version, demo_mode, trigger_source, job_id,
                    publication_status, github_review_id, published_at, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                          ?, ?, ?, ?, ?)
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
                    trigger_source = ?, job_id = ?, publication_status = ?, github_review_id = ?,
                    published_at = ?,
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
                    run.trigger_source.value,
                    run.job_id,
                    run.publication_status.value,
                    run.github_review_id,
                    run.published_at.isoformat() if run.published_at else None,
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

    async def begin_publication(self, review_id: str, lease_seconds: int = 300) -> ReviewRun | None:
        now = datetime.now(UTC)
        expired = now - timedelta(seconds=lease_seconds)
        async with aiosqlite.connect(self.database_path) as connection:
            connection.row_factory = aiosqlite.Row
            await connection.execute("PRAGMA busy_timeout=30000")
            await connection.execute("BEGIN IMMEDIATE")
            cursor = await connection.execute(
                """
                UPDATE review_runs
                SET publication_status = 'publishing', updated_at = ?
                WHERE id = ? AND (
                    publication_status IN ('not_published', 'failed')
                    OR (publication_status = 'publishing' AND updated_at < ?)
                )
                """,
                (now.isoformat(), review_id, expired.isoformat()),
            )
            if cursor.rowcount == 0:
                await connection.rollback()
                return None
            row_cursor = await connection.execute(
                "SELECT * FROM review_runs WHERE id = ?", (review_id,)
            )
            row = await row_cursor.fetchone()
            await connection.commit()
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

    async def enqueue_webhook_job(
        self,
        job: ReviewJob,
        event_name: str,
        action: str | None,
    ) -> tuple[ReviewJob, bool]:
        async with aiosqlite.connect(self.database_path) as connection:
            connection.row_factory = aiosqlite.Row
            await connection.execute("PRAGMA busy_timeout=30000")
            await connection.execute("BEGIN IMMEDIATE")
            delivery_cursor = await connection.execute(
                "SELECT job_id FROM webhook_deliveries WHERE delivery_id = ?",
                (job.delivery_id,),
            )
            delivery = await delivery_cursor.fetchone()
            if delivery:
                existing = await self._job_by_id(connection, delivery["job_id"])
                await connection.rollback()
                return existing or job, True

            key_cursor = await connection.execute(
                "SELECT * FROM review_jobs WHERE idempotency_key = ?",
                (job.idempotency_key,),
            )
            existing_row = await key_cursor.fetchone()
            duplicate = existing_row is not None
            if existing_row:
                stored_job = self._job_from_row(existing_row)
            else:
                await connection.execute(
                    """
                    INSERT INTO review_jobs (
                        id, idempotency_key, delivery_id, repository, pr_number, pr_url, head_sha,
                        installation_id, correlation_id, status, attempts, max_attempts,
                        available_at,
                        locked_at, error_message, review_id, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    self._job_values(job),
                )
                stored_job = job
            await connection.execute(
                """
                INSERT INTO webhook_deliveries (
                    delivery_id, event_name, action, repository, pr_number, head_sha, job_id,
                    received_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    job.delivery_id,
                    event_name,
                    action,
                    job.repository,
                    job.pr_number,
                    job.head_sha,
                    stored_job.id,
                    datetime.now(UTC).isoformat(),
                ),
            )
            await connection.commit()
        return stored_job, duplicate

    async def claim_next_job(self, lease_seconds: int) -> ReviewJob | None:
        now = datetime.now(UTC)
        expired = now - timedelta(seconds=lease_seconds)
        async with aiosqlite.connect(self.database_path) as connection:
            connection.row_factory = aiosqlite.Row
            await connection.execute("PRAGMA busy_timeout=30000")
            await connection.execute("BEGIN IMMEDIATE")
            await connection.execute(
                """
                UPDATE review_jobs
                SET status = 'retrying', locked_at = NULL, available_at = ?,
                    error_message = 'Worker lease expired; retrying.', updated_at = ?
                WHERE status = 'running' AND locked_at < ? AND attempts < max_attempts
                """,
                (now.isoformat(), now.isoformat(), expired.isoformat()),
            )
            await connection.execute(
                """
                UPDATE review_jobs
                SET status = 'failed', locked_at = NULL,
                    error_message = 'Worker lease expired after maximum attempts.', updated_at = ?
                WHERE status = 'running' AND locked_at < ? AND attempts >= max_attempts
                """,
                (now.isoformat(), expired.isoformat()),
            )
            cursor = await connection.execute(
                """
                SELECT * FROM review_jobs
                WHERE status IN ('queued', 'retrying') AND available_at <= ?
                    AND attempts < max_attempts
                ORDER BY available_at, created_at
                LIMIT 1
                """,
                (now.isoformat(),),
            )
            row = await cursor.fetchone()
            if row is None:
                await connection.commit()
                return None
            await connection.execute(
                """
                UPDATE review_jobs
                SET status = 'running', attempts = attempts + 1, locked_at = ?, updated_at = ?
                WHERE id = ?
                """,
                (now.isoformat(), now.isoformat(), row["id"]),
            )
            updated = await self._job_by_id(connection, row["id"])
            await connection.commit()
        return updated

    async def complete_job(self, job_id: str, review_id: str) -> None:
        await self._update_job(
            job_id,
            status=JobStatus.completed,
            review_id=review_id,
            error_message=None,
        )

    async def supersede_job(self, job_id: str, message: str) -> None:
        await self._update_job(
            job_id,
            status=JobStatus.superseded,
            review_id=None,
            error_message=message,
        )

    async def fail_job(self, job: ReviewJob, message: str, *, retryable: bool = True) -> JobStatus:
        retrying = retryable and job.attempts < job.max_attempts
        status = JobStatus.retrying if retrying else JobStatus.failed
        delay_seconds = min(60, 2 ** max(job.attempts - 1, 0)) if retrying else 0
        await self._update_job(
            job.id,
            status=status,
            review_id=None,
            error_message=message[:2_000],
            available_at=datetime.now(UTC) + timedelta(seconds=delay_seconds),
        )
        return status

    async def list_jobs(self, limit: int = 25) -> ReviewJobList:
        async with aiosqlite.connect(self.database_path) as connection:
            connection.row_factory = aiosqlite.Row
            cursor = await connection.execute(
                "SELECT * FROM review_jobs ORDER BY created_at DESC LIMIT ?", (limit,)
            )
            rows = await cursor.fetchall()
            count_cursor = await connection.execute("SELECT COUNT(*) FROM review_jobs")
            total = (await count_cursor.fetchone())[0]
        return ReviewJobList(items=[self._job_from_row(row) for row in rows], total=total)

    async def pending_job_count(self) -> int:
        async with aiosqlite.connect(self.database_path) as connection:
            cursor = await connection.execute(
                """
                SELECT COUNT(*) FROM review_jobs
                WHERE status IN ('queued', 'retrying', 'running')
                """
            )
            return (await cursor.fetchone())[0]

    async def create_evaluation_run(self, run: EvaluationRun) -> EvaluationRun:
        async with aiosqlite.connect(self.database_path) as connection:
            await connection.execute(
                """
                INSERT INTO evaluation_runs (
                    id, status, dataset_version, model, prompt_version, case_count,
                    completed_cases, true_positives, false_positives, false_negatives,
                    invalid_findings, accepted_findings, precision, recall, invalid_line_rate,
                    input_tokens, output_tokens, latency_ms, estimated_cost_usd, results_json,
                    error_message, created_at, completed_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                self._evaluation_values(run),
            )
            await connection.commit()
        return run

    async def save_evaluation_run(self, run: EvaluationRun) -> EvaluationRun:
        async with aiosqlite.connect(self.database_path) as connection:
            await connection.execute(
                """
                UPDATE evaluation_runs SET
                    status = ?, dataset_version = ?, model = ?, prompt_version = ?,
                    case_count = ?, completed_cases = ?, true_positives = ?,
                    false_positives = ?, false_negatives = ?, invalid_findings = ?,
                    accepted_findings = ?, precision = ?, recall = ?, invalid_line_rate = ?,
                    input_tokens = ?, output_tokens = ?, latency_ms = ?, estimated_cost_usd = ?,
                    results_json = ?, error_message = ?, completed_at = ?
                WHERE id = ?
                """,
                (
                    *self._evaluation_values(run)[1:-2],
                    run.completed_at.isoformat() if run.completed_at else None,
                    run.id,
                ),
            )
            await connection.commit()
        return run

    async def list_evaluation_runs(self, limit: int = 20) -> EvaluationRunList:
        async with aiosqlite.connect(self.database_path) as connection:
            connection.row_factory = aiosqlite.Row
            cursor = await connection.execute(
                "SELECT * FROM evaluation_runs ORDER BY created_at DESC LIMIT ?", (limit,)
            )
            rows = await cursor.fetchall()
            count_cursor = await connection.execute("SELECT COUNT(*) FROM evaluation_runs")
            total = (await count_cursor.fetchone())[0]
        return EvaluationRunList(
            items=[self._evaluation_from_row(row) for row in rows], total=total
        )

    async def _update_job(
        self,
        job_id: str,
        *,
        status: JobStatus,
        review_id: str | None,
        error_message: str | None,
        available_at: datetime | None = None,
    ) -> None:
        now = datetime.now(UTC)
        async with aiosqlite.connect(self.database_path) as connection:
            await connection.execute(
                """
                UPDATE review_jobs
                SET status = ?, review_id = ?, error_message = ?, available_at = ?,
                    locked_at = NULL, updated_at = ?
                WHERE id = ?
                """,
                (
                    status.value,
                    review_id,
                    error_message,
                    (available_at or now).isoformat(),
                    now.isoformat(),
                    job_id,
                ),
            )
            await connection.commit()

    @staticmethod
    async def _job_by_id(connection: aiosqlite.Connection, job_id: str | None) -> ReviewJob | None:
        if not job_id:
            return None
        cursor = await connection.execute("SELECT * FROM review_jobs WHERE id = ?", (job_id,))
        row = await cursor.fetchone()
        return ReviewRepository._job_from_row(row) if row else None

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
            run.trigger_source.value,
            run.job_id,
            run.publication_status.value,
            run.github_review_id,
            run.published_at.isoformat() if run.published_at else None,
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
            trigger_source=(
                TriggerSource(row["trigger_source"])
                if "trigger_source" in keys
                else TriggerSource.manual
            ),
            job_id=row["job_id"] if "job_id" in keys else None,
            publication_status=(
                PublicationStatus(row["publication_status"])
                if "publication_status" in keys
                else PublicationStatus.not_published
            ),
            github_review_id=(row["github_review_id"] if "github_review_id" in keys else None),
            published_at=(
                datetime.fromisoformat(row["published_at"])
                if "published_at" in keys and row["published_at"]
                else None
            ),
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

    @staticmethod
    def _job_values(job: ReviewJob) -> tuple[object, ...]:
        return (
            job.id,
            job.idempotency_key,
            job.delivery_id,
            job.repository,
            job.pr_number,
            job.pr_url,
            job.head_sha,
            job.installation_id,
            job.correlation_id,
            job.status.value,
            job.attempts,
            job.max_attempts,
            job.available_at.isoformat(),
            job.locked_at.isoformat() if job.locked_at else None,
            job.error_message,
            job.review_id,
            job.created_at.isoformat(),
            job.updated_at.isoformat(),
        )

    @staticmethod
    def _job_from_row(row: aiosqlite.Row) -> ReviewJob:
        return ReviewJob(
            id=row["id"],
            idempotency_key=row["idempotency_key"],
            delivery_id=row["delivery_id"],
            repository=row["repository"],
            pr_number=row["pr_number"],
            pr_url=row["pr_url"],
            head_sha=row["head_sha"],
            installation_id=row["installation_id"],
            correlation_id=(row["correlation_id"] if "correlation_id" in set(row.keys()) else None),
            status=JobStatus(row["status"]),
            attempts=row["attempts"],
            max_attempts=row["max_attempts"],
            available_at=datetime.fromisoformat(row["available_at"]),
            locked_at=datetime.fromisoformat(row["locked_at"]) if row["locked_at"] else None,
            error_message=row["error_message"],
            review_id=row["review_id"],
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
        )

    @staticmethod
    def _evaluation_values(run: EvaluationRun) -> tuple[object, ...]:
        return (
            run.id,
            run.status.value,
            run.dataset_version,
            run.model,
            run.prompt_version,
            run.case_count,
            run.completed_cases,
            run.true_positives,
            run.false_positives,
            run.false_negatives,
            run.invalid_findings,
            run.accepted_findings,
            run.precision,
            run.recall,
            run.invalid_line_rate,
            run.input_tokens,
            run.output_tokens,
            run.latency_ms,
            run.estimated_cost_usd,
            json.dumps([result.model_dump(mode="json") for result in run.results]),
            run.error_message,
            run.created_at.isoformat(),
            run.completed_at.isoformat() if run.completed_at else None,
        )

    @staticmethod
    def _evaluation_from_row(row: aiosqlite.Row) -> EvaluationRun:
        return EvaluationRun(
            id=row["id"],
            status=EvaluationStatus(row["status"]),
            dataset_version=row["dataset_version"],
            model=row["model"],
            prompt_version=row["prompt_version"],
            case_count=row["case_count"],
            completed_cases=row["completed_cases"],
            true_positives=row["true_positives"],
            false_positives=row["false_positives"],
            false_negatives=row["false_negatives"],
            invalid_findings=row["invalid_findings"],
            accepted_findings=row["accepted_findings"],
            precision=row["precision"],
            recall=row["recall"],
            invalid_line_rate=row["invalid_line_rate"],
            input_tokens=row["input_tokens"],
            output_tokens=row["output_tokens"],
            latency_ms=row["latency_ms"],
            estimated_cost_usd=row["estimated_cost_usd"],
            results=json.loads(row["results_json"]),
            error_message=row["error_message"],
            created_at=datetime.fromisoformat(row["created_at"]),
            completed_at=(
                datetime.fromisoformat(row["completed_at"]) if row["completed_at"] else None
            ),
        )
