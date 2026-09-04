from datetime import UTC, datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, HttpUrl


class Severity(StrEnum):
    critical = "critical"
    high = "high"
    medium = "medium"
    low = "low"


class Category(StrEnum):
    security = "security"
    correctness = "correctness"
    performance = "performance"
    maintainability = "maintainability"
    testing = "testing"
    documentation = "documentation"


class Approval(StrEnum):
    approve = "approve"
    comment = "comment"
    request_changes = "request_changes"


class ReviewStatus(StrEnum):
    queued = "queued"
    running = "running"
    completed = "completed"
    failed = "failed"


class ReviewIssue(BaseModel):
    model_config = ConfigDict(extra="forbid")

    file_path: str
    line_number: int | None = None
    severity: Severity
    category: Category
    title: str
    message: str
    evidence: str
    suggestion: str


class ReviewResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    summary: str
    approval: Approval
    confidence: float
    issues: list[ReviewIssue]
    positive_notes: list[str]
    reviewed_files: list[str]
    skipped_files: list[str]


class PullRequestFile(BaseModel):
    filename: str
    status: str
    additions: int
    deletions: int
    changes: int
    patch: str | None = None


class PullRequestSnapshot(BaseModel):
    repository: str
    number: int
    url: str
    title: str
    author: str
    base_ref: str
    head_ref: str
    head_sha: str
    body: str | None = None
    files: list[PullRequestFile]

    @property
    def additions(self) -> int:
        return sum(file.additions for file in self.files)

    @property
    def deletions(self) -> int:
        return sum(file.deletions for file in self.files)


class ManualReviewRequest(BaseModel):
    pr_url: HttpUrl
    ticket_reference: str | None = Field(default=None, max_length=100)
    dry_run: bool = True


class ReviewRun(BaseModel):
    id: str
    repository: str | None = None
    pr_number: int | None = None
    pr_url: str
    head_sha: str | None = None
    title: str | None = None
    author: str | None = None
    status: ReviewStatus
    dry_run: bool
    ticket_reference: str | None = None
    result: ReviewResult | None = None
    issue_count: int = 0
    model: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    latency_ms: int | None = None
    error_message: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class ReviewList(BaseModel):
    items: list[ReviewRun]
    total: int


class HealthResponse(BaseModel):
    status: str
    database: str
    openai_configured: bool
    github_configured: bool
    dry_run_only: bool


class PublicConfig(BaseModel):
    app_name: str
    environment: str
    openai_model: str
    openai_configured: bool
    github_configured: bool
    dry_run_only: bool
