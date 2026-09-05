import type {
  Health,
  KnowledgeDocument,
  KnowledgeDocumentList,
  PublicConfig,
  ReviewList,
  ReviewRun,
} from "./types";

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const isFormData = options?.body instanceof FormData;
  const response = await fetch(path, {
    ...options,
    headers: isFormData
      ? options?.headers
      : {
          "Content-Type": "application/json",
          ...options?.headers,
        },
  });
  if (!response.ok) {
    const payload = (await response.json().catch(() => null)) as { detail?: string } | null;
    throw new Error(payload?.detail ?? `Request failed with status ${response.status}`);
  }
  if (response.status === 204) return undefined as T;
  return response.json() as Promise<T>;
}

export const api = {
  health: () => request<Health>("/api/health"),
  config: () => request<PublicConfig>("/api/config"),
  reviews: () => request<ReviewList>("/api/reviews?limit=50"),
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
};
