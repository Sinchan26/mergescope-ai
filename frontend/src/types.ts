export type ReviewStatus = "queued" | "running" | "completed" | "failed";
export type Approval = "approve" | "comment" | "request_changes";
export type Severity = "critical" | "high" | "medium" | "low";

export interface Health {
  status: string;
  database: string;
  openai_configured: boolean;
  github_configured: boolean;
  dry_run_only: boolean;
}

export interface PublicConfig {
  app_name: string;
  environment: string;
  openai_model: string;
  openai_configured: boolean;
  github_configured: boolean;
  dry_run_only: boolean;
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
}

export interface ReviewResult {
  summary: string;
  approval: Approval;
  confidence: number;
  issues: ReviewIssue[];
  positive_notes: string[];
  reviewed_files: string[];
  skipped_files: string[];
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
  created_at: string;
  updated_at: string;
}

export interface ReviewList {
  items: ReviewRun[];
  total: number;
}
