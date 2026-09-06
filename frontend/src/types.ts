export type ReviewStatus = "queued" | "running" | "completed" | "failed";
export type TriggerSource = "manual" | "webhook" | "demo";
export type JobStatus =
  | "queued"
  | "running"
  | "retrying"
  | "completed"
  | "failed"
  | "superseded";
export type PublicationStatus =
  | "not_published"
  | "publishing"
  | "published"
  | "failed"
  | "stale";
export type Approval = "approve" | "comment" | "request_changes";
export type Severity = "critical" | "high" | "medium" | "low";
export type AgentRole =
  | "code_reviewer"
  | "security_reviewer"
  | "testing_reviewer"
  | "review_synthesizer";

export interface Health {
  status: string;
  database: string;
  openai_configured: boolean;
  github_configured: boolean;
  github_app_configured: boolean;
  webhook_configured: boolean;
  worker_enabled: boolean;
  pending_jobs: number;
  publishing_enabled: boolean;
  knowledge_documents: number;
  dry_run_only: boolean;
  demo_mode_allowed: boolean;
}

export interface PublicConfig {
  app_name: string;
  environment: string;
  openai_model: string;
  embedding_model: string;
  openai_configured: boolean;
  github_configured: boolean;
  github_app_configured: boolean;
  webhook_configured: boolean;
  worker_enabled: boolean;
  publishing_enabled: boolean;
  dry_run_only: boolean;
  demo_mode_allowed: boolean;
  prompt_version: string;
}

export interface ContextSource {
  source_id: string;
  name: string;
  source_type: string;
  excerpt: string;
  relevance_score: number | null;
}

export interface ReviewIssue {
  file_path: string;
  line_number: number | null;
  severity: Severity;
  category: string;
  title: string;
  message: string;
  evidence: string;
  suggestion: string;
  agent: AgentRole;
  line_validated: boolean;
  diff_excerpt: string | null;
}

export interface ReviewResult {
  summary: string;
  approval: Approval;
  confidence: number;
  issues: ReviewIssue[];
  positive_notes: string[];
  reviewed_files: string[];
  skipped_files: string[];
  agents_run: AgentRole[];
  context_sources: ContextSource[];
  rejected_issue_count: number;
}

export interface ReviewRun {
  id: string;
  repository: string | null;
  pr_number: number | null;
  pr_url: string;
  head_sha: string | null;
  title: string | null;
  author: string | null;
  status: ReviewStatus;
  dry_run: boolean;
  ticket_reference: string | null;
  result: ReviewResult | null;
  issue_count: number;
  model: string | null;
  input_tokens: number | null;
  output_tokens: number | null;
  latency_ms: number | null;
  error_message: string | null;
  cache_key: string | null;
  cache_hit: boolean;
  cached_from_id: string | null;
  prompt_version: string | null;
  demo_mode: boolean;
  trigger_source: TriggerSource;
  job_id: string | null;
  publication_status: PublicationStatus;
  github_review_id: number | null;
  published_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface ReviewList {
  items: ReviewRun[];
  total: number;
}

export interface KnowledgeDocument {
  id: string;
  name: string;
  content_type: string;
  size_bytes: number;
  chunk_count: number;
  embedding_model: string;
  created_at: string;
}

export interface KnowledgeDocumentList {
  items: KnowledgeDocument[];
  total: number;
}

export interface ReviewJob {
  id: string;
  idempotency_key: string;
  delivery_id: string;
  repository: string;
  pr_number: number;
  pr_url: string;
  head_sha: string;
  installation_id: number | null;
  status: JobStatus;
  attempts: number;
  max_attempts: number;
  available_at: string;
  locked_at: string | null;
  error_message: string | null;
  review_id: string | null;
  created_at: string;
  updated_at: string;
}

export interface ReviewJobList {
  items: ReviewJob[];
  total: number;
}

export interface PublicationComment {
  path: string;
  line: number;
  side: "RIGHT";
  body: string;
}

export interface PublicationPreview {
  review_id: string;
  commit_sha: string | null;
  body: string;
  comments: PublicationComment[];
  can_publish: boolean;
  blocking_reasons: string[];
  already_published: boolean;
}

export interface PublicationResult {
  review_id: string;
  status: PublicationStatus;
  github_review_id: number | null;
  published_at: string | null;
  message: string;
}
