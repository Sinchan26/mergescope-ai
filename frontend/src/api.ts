import type {
  Health,
  EvaluationDatasetSummary,
  EvaluationRun,
  EvaluationRunList,
  KnowledgeDocument,
  KnowledgeDocumentList,
  PublicConfig,
  PublicationPreview,
  PublicationResult,
  ReviewJobList,
  ReviewList,
  ReviewRun,
} from "./types";

let csrfToken = "";
export const setCsrfToken = (value: string) => { csrfToken = value; };
export interface SessionInfo { user: { id: number; login: string }; csrf_token: string }
export interface AccessibleRepository { id: number; full_name: string; private: boolean }
export class ApiError extends Error {
  constructor(message: string, public status: number) { super(message); }
}

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const isFormData = options?.body instanceof FormData;
  const response = await fetch(path, {
    ...options,
    credentials: "same-origin",
    cache: "no-store",
    headers: {
      ...(!isFormData ? { "Content-Type": "application/json" } : {}),
      ...(options?.method && options.method !== "GET" ? { "X-MergeScope-CSRF": csrfToken } : {}),
      ...options?.headers,
    },
  });
  if (!response.ok) {
    const payload = (await response.json().catch(() => null)) as { detail?: string } | null;
    if (response.status === 401 && path !== "/api/auth/me") window.dispatchEvent(new Event("mergescope:expired"));
    throw new ApiError(payload?.detail ?? `Request failed with status ${response.status}`, response.status);
  }
  if (response.status === 204) return undefined as T;
  return response.json() as Promise<T>;
}

export const api = {
  authStatus: () => request<{ configured: boolean; install_url: string | null }>("/api/auth/status"),
  me: () => request<SessionInfo>("/api/auth/me"),
  repositories: () => request<{ items: AccessibleRepository[] }>("/api/auth/repositories"),
  logout: () => request<void>("/api/auth/logout", { method: "POST" }),
  health: () => request<Health>("/api/readiness"),
  config: () => request<PublicConfig>("/api/config"),
  reviews: () => request<ReviewList>("/api/reviews?limit=50"),
  jobs: () => request<ReviewJobList>("/api/jobs?limit=50"),
  evaluationDataset: () =>
    request<EvaluationDatasetSummary>("/api/evaluations/dataset"),
  evaluationRuns: () => request<EvaluationRunList>("/api/evaluations/runs?limit=20"),
  runEvaluation: (evaluationToken: string) =>
    request<EvaluationRun>("/api/evaluations/runs", {
      method: "POST",
      headers: { "X-MergeScope-Evaluation-Token": evaluationToken },
      body: JSON.stringify({ confirm_cost: true }),
    }),
  documents: () => request<KnowledgeDocumentList>("/api/knowledge/documents"),
  createReview: ({
    prUrl,
    ticketReference,
    forceRereview,
    demoMode,
  }: {
    prUrl: string;
    ticketReference: string;
    forceRereview: boolean;
    demoMode: boolean;
  }) =>
    request<ReviewRun>("/api/reviews/manual", {
      method: "POST",
      body: JSON.stringify({
        pr_url: demoMode ? null : prUrl,
        ticket_reference: ticketReference.trim() || null,
        dry_run: true,
        force_rereview: forceRereview,
        demo_mode: demoMode,
      }),
    }),
  uploadDocument: (file: File) => {
    const body = new FormData();
    body.append("file", file);
    return request<KnowledgeDocument>("/api/knowledge/documents", { method: "POST", body });
  },
  deleteDocument: (documentId: string) =>
    request<void>(`/api/knowledge/documents/${documentId}`, { method: "DELETE" }),
  publicationPreview: (reviewId: string) =>
    request<PublicationPreview>(`/api/reviews/${reviewId}/publication-preview`),
  publishReview: (reviewId: string) =>
    request<PublicationResult>(`/api/reviews/${reviewId}/publish`, {
      method: "POST",
      body: JSON.stringify({ confirm: true }),
    }),
};
