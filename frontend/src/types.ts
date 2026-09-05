export type ReviewStatus = "queued" | "running" | "completed" | "failed";
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
