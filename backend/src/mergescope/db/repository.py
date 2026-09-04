import json
from datetime import UTC, datetime
from pathlib import Path

import aiosqlite

from mergescope.domain.models import ReviewList, ReviewResult, ReviewRun, ReviewStatus

SCHEMA = """
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
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_review_runs_created_at
    ON review_runs(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_review_runs_pull_request
    ON review_runs(repository, pr_number, head_sha);
CREATE INDEX IF NOT EXISTS idx_review_runs_status
    ON review_runs(status);
"""


class ReviewRepository:
    def __init__(self, database_path: Path) -> None:
        self.database_path = database_path

    async def initialize(self) -> None:
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        async with aiosqlite.connect(self.database_path) as connection:
            await connection.executescript(SCHEMA)
            await connection.execute("PRAGMA journal_mode=WAL")
            await connection.execute("PRAGMA foreign_keys=ON")
            await connection.execute("PRAGMA optimize")
            await connection.commit()

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
                    input_tokens, output_tokens, latency_ms, error_message,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                    output_tokens = ?, latency_ms = ?, error_message = ?, updated_at = ?
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
        return self._from_row(row) if row else None

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
        return ReviewList(items=[self._from_row(row) for row in rows], total=total)

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
            run.created_at.isoformat(),
            run.updated_at.isoformat(),
        )

    @staticmethod
    def _from_row(row: aiosqlite.Row) -> ReviewRun:
        result = (
            ReviewResult.model_validate(json.loads(row["result_json"]))
            if row["result_json"]
            else None
        )
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
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
        )
