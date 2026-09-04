import type { Health, PublicConfig, ReviewList, ReviewRun } from "./types";

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      ...options?.headers,
    },
  });
  if (!response.ok) {
    const payload = (await response.json().catch(() => null)) as { detail?: string } | null;
    throw new Error(payload?.detail ?? `Request failed with status ${response.status}`);
  }
  return response.json() as Promise<T>;
}

export const api = {
  health: () => request<Health>("/api/health"),
  config: () => request<PublicConfig>("/api/config"),
  reviews: () => request<ReviewList>("/api/reviews?limit=50"),
  createReview: (prUrl: string, ticketReference: string) =>
    request<ReviewRun>("/api/reviews/manual", {
      method: "POST",
      body: JSON.stringify({
        pr_url: prUrl,
        ticket_reference: ticketReference.trim() || null,
        dry_run: true,
      }),
  }),
};
