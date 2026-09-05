from datetime import UTC, datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, model_validator


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


class AgentRole(StrEnum):
    code = "code_reviewer"
    security = "security_reviewer"
    testing = "testing_reviewer"
    synthesizer = "review_synthesizer"


class ContextSource(BaseModel):
    source_id: str
    name: str
    source_type: str
    excerpt: str
    relevance_score: float | None = None


class AgentReviewIssue(BaseModel):
    model_config = ConfigDict(extra="forbid")

    file_path: str
    line_number: int | None = None
    severity: Severity
    category: Category
    title: str
    message: str
    evidence: str
    suggestion: str


class AgentReview(BaseModel):
    model_config = ConfigDict(extra="forbid")

    summary: str
    issues: list[AgentReviewIssue]
    positive_notes: list[str]


class SynthesizedReview(BaseModel):
    model_config = ConfigDict(extra="forbid")

    summary: str
    approval: Approval
    confidence: float
    positive_notes: list[str]
    reviewed_files: list[str]
    skipped_files: list[str]


class ReviewIssue(AgentReviewIssue):
    agent: AgentRole
    line_validated: bool
    diff_excerpt: str | None


class ReviewResult(BaseModel):
    summary: str
    approval: Approval
    confidence: float
    issues: list[ReviewIssue]
    positive_notes: list[str]
    reviewed_files: list[str]
    skipped_files: list[str]
    agents_run: list[AgentRole] = Field(default_factory=list)
    context_sources: list[ContextSource] = Field(default_factory=list)
    rejected_issue_count: int = 0


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
    pr_url: HttpUrl | None = None
    ticket_reference: str | None = Field(default=None, max_length=100)
    dry_run: bool = True
    force_rereview: bool = False
    demo_mode: bool = False

    @model_validator(mode="after")
    def require_pull_request_outside_demo(self) -> "ManualReviewRequest":
        if not self.demo_mode and self.pr_url is None:
            raise ValueError("A GitHub pull request URL is required.")
        return self


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
    cache_key: str | None = None
    cache_hit: bool = False
    cached_from_id: str | None = None
    prompt_version: str | None = None
    demo_mode: bool = False
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class ReviewList(BaseModel):
    items: list[ReviewRun]
    total: int


class KnowledgeDocument(BaseModel):
    id: str
    name: str
    content_type: str
    size_bytes: int
    chunk_count: int
    embedding_model: str
    created_at: datetime


class KnowledgeDocumentList(BaseModel):
    items: list[KnowledgeDocument]
    total: int


class KnowledgeChunk(BaseModel):
    id: str
    document_id: str
    document_name: str
    position: int
    heading: str | None
    content: str
    embedding: list[float]


class HealthResponse(BaseModel):
    status: str
    database: str
    openai_configured: bool
    github_configured: bool
    knowledge_documents: int
    dry_run_only: bool
    demo_mode_allowed: bool


class PublicConfig(BaseModel):
    app_name: str
    environment: str
    openai_model: str
    embedding_model: str
    openai_configured: bool
    github_configured: bool
    dry_run_only: bool
    demo_mode_allowed: bool
    prompt_version: str
