from datetime import UTC, datetime
from enum import StrEnum
from typing import Literal

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


class TriggerSource(StrEnum):
    manual = "manual"
    webhook = "webhook"
    demo = "demo"


class JobStatus(StrEnum):
    queued = "queued"
    running = "running"
    retrying = "retrying"
    completed = "completed"
    failed = "failed"
    superseded = "superseded"


class PublicationStatus(StrEnum):
    not_published = "not_published"
    publishing = "publishing"
    published = "published"
    failed = "failed"
    stale = "stale"


class SecurityReviewMode(StrEnum):
    disabled = "disabled"
    conditional = "conditional"
    always = "always"


class EvaluationCaseType(StrEnum):
    good = "good"
    bad = "bad"
    adversarial = "adversarial"


class EvaluationStatus(StrEnum):
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


class ReviewPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    require_ticket_reference: bool = False
    security_review: SecurityReviewMode = SecurityReviewMode.conditional
    testing_review: bool = True
    blocking_severities: list[Severity] = Field(
        default_factory=lambda: [Severity.critical, Severity.high]
    )
    blocking_categories: list[Category] = Field(
        default_factory=lambda: [Category.security, Category.correctness]
    )
    minimum_confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    max_inline_comments: int = Field(default=50, ge=0, le=100)
    publish_comments: bool = False


class RepositoryPolicySummary(BaseModel):
    allowlist_enabled: bool
    allowed_repository_count: int
    policy_file_configured: bool
    repository_policy_count: int
    default_policy: ReviewPolicy


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
    trigger_source: TriggerSource = TriggerSource.manual
    job_id: str | None = None
    publication_status: PublicationStatus = PublicationStatus.not_published
    github_review_id: int | None = None
    published_at: datetime | None = None
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


class ReviewJob(BaseModel):
    id: str
    idempotency_key: str
    delivery_id: str
    repository: str
    pr_number: int
    pr_url: str
    head_sha: str
    installation_id: int | None = None
    correlation_id: str | None = None
    status: JobStatus = JobStatus.queued
    attempts: int = 0
    max_attempts: int = 3
    available_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    locked_at: datetime | None = None
    error_message: str | None = None
    review_id: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class ReviewJobList(BaseModel):
    items: list[ReviewJob]
    total: int


class WebhookReceipt(BaseModel):
    delivery_id: str
    accepted: bool
    duplicate: bool = False
    job_id: str | None = None
    message: str


class PublicationComment(BaseModel):
    path: str
    line: int
    side: Literal["RIGHT"] = "RIGHT"
    body: str


class PublicationPreview(BaseModel):
    review_id: str
    commit_sha: str | None
    body: str
    comments: list[PublicationComment]
    can_publish: bool
    blocking_reasons: list[str]
    already_published: bool


class PublishReviewRequest(BaseModel):
    confirm: Literal[True]


class PublicationResult(BaseModel):
    review_id: str
    status: PublicationStatus
    github_review_id: int | None = None
    published_at: datetime | None = None
    message: str


class ExpectedFinding(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: str
    line: int
    category: Category


class EvaluationCase(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    name: str
    case_type: EvaluationCaseType
    description: str
    pull_request: PullRequestSnapshot
    expected_findings: list[ExpectedFinding]


class EvaluationDataset(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: str
    cases: list[EvaluationCase]


class EvaluationCaseSummary(BaseModel):
    id: str
    name: str
    case_type: EvaluationCaseType
    description: str
    expected_finding_count: int


class EvaluationDatasetSummary(BaseModel):
    version: str
    case_count: int
    good_cases: int
    bad_cases: int
    adversarial_cases: int
    expected_finding_count: int
    cases: list[EvaluationCaseSummary]


class EvaluationCaseResult(BaseModel):
    case_id: str
    case_name: str
    case_type: EvaluationCaseType
    true_positives: int
    false_positives: int
    false_negatives: int
    invalid_findings: int
    accepted_findings: int
    input_tokens: int
    output_tokens: int
    latency_ms: int
    estimated_cost_usd: float
    error_message: str | None = None


class EvaluationRun(BaseModel):
    id: str
    status: EvaluationStatus
    dataset_version: str
    model: str
    prompt_version: str
    case_count: int
    completed_cases: int = 0
    true_positives: int = 0
    false_positives: int = 0
    false_negatives: int = 0
    invalid_findings: int = 0
    accepted_findings: int = 0
    precision: float = 0.0
    recall: float = 0.0
    invalid_line_rate: float = 0.0
    input_tokens: int = 0
    output_tokens: int = 0
    latency_ms: int = 0
    estimated_cost_usd: float = 0.0
    results: list[EvaluationCaseResult] = Field(default_factory=list)
    error_message: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    completed_at: datetime | None = None


class EvaluationRunList(BaseModel):
    items: list[EvaluationRun]
    total: int


class RunEvaluationRequest(BaseModel):
    confirm_cost: Literal[True]


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
    github_app_configured: bool
    webhook_configured: bool
    worker_enabled: bool
    pending_jobs: int
    publishing_enabled: bool
    allowlist_enabled: bool
    policy_file_configured: bool
    evaluation_dataset_ready: bool
    evaluation_enabled: bool
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
    github_app_configured: bool
    webhook_configured: bool
    worker_enabled: bool
    publishing_enabled: bool
    allowlist_enabled: bool
    allowed_repository_count: int
    policy_file_configured: bool
    repository_policy_count: int
    evaluation_dataset_ready: bool
    evaluation_enabled: bool
    evaluation_case_count: int
    cost_estimation_configured: bool
    structured_logging: bool
    dry_run_only: bool
    demo_mode_allowed: bool
    prompt_version: str
