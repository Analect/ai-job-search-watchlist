// Thin fetch client for job-search-api. No auth header logic lives here —
// per job-search-api.contract.md, the API trusts whatever identity the
// platform gateway already established; this client is a plain fetch
// wrapper, not a token-attaching client (contrast with
// insurance-support-agent/web/src/lib/api.ts's authHeaders()).

const API_BASE = (import.meta.env.VITE_API_URL ?? "http://localhost:8000").replace(/\/+$/, "");

export class ApiError extends Error {
  readonly status: number;
  constructor(status: number, message: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...init,
  });
  if (!res.ok) {
    const body = await res.text().catch(() => "");
    throw new ApiError(res.status, body || res.statusText);
  }
  return res.json() as Promise<T>;
}

export type ReviewState = "unreviewed" | "flagged_for_advancement" | "dismissed";

export interface PostingSummary {
  id: string;
  employer_name: string;
  title: string;
  location_city: string | null;
  location_country: string | null;
  posted_date: string | null;
  status: "open" | "closed" | "unknown";
  review_state: ReviewState;
  source_url: string;
}

export interface PostingsResult {
  results: PostingSummary[];
  total: number;
}

export interface PostingsFilter {
  location?: string;
  status?: string;
  review_state?: string;
  query?: string;
  limit?: number;
  offset?: number;
}

export function fetchPostings(filter: PostingsFilter = {}): Promise<PostingsResult> {
  const params = new URLSearchParams();
  Object.entries(filter).forEach(([k, v]) => {
    if (v !== undefined && v !== "") params.set(k, String(v));
  });
  const qs = params.toString();
  return request<PostingsResult>(`/postings${qs ? `?${qs}` : ""}`);
}

export interface JobEvent {
  event_type: string;
  source: "user" | "assistant";
  note: string | null;
  created_at: string;
}

export interface PostingDetail {
  posting: PostingSummary & Record<string, unknown>;
  description: string | null;
  events: JobEvent[];
}

export function fetchPostingDetail(id: string): Promise<PostingDetail> {
  return request<PostingDetail>(`/postings/${id}`);
}

export function markForAdvancement(id: string, note?: string): Promise<JobEvent> {
  return request<JobEvent>(`/postings/${id}/events`, {
    method: "POST",
    body: JSON.stringify({ event_type: "flagged_for_advancement", note }),
  });
}

export interface SimilarPosting {
  id: string;
  employer_name: string;
  title: string;
  similarity_score: number;
  source_url: string;
}

export interface SimilarResult {
  results: SimilarPosting[];
  message?: string;
}

export function fetchSimilar(id: string, limit = 5): Promise<SimilarResult> {
  return request<SimilarResult>(`/postings/${id}/similar?limit=${limit}`);
}

export interface MapCompany {
  slug: string;
  name: string;
  industry: string | null;
  x: number;
  y: number;
  short_listed: boolean;
  ats_types: string | null;
}

export function fetchMapCoordinates(): Promise<{ companies: MapCompany[] }> {
  return request(`/map/coordinates`);
}

export function addToWatchlist(
  slug: string,
): Promise<{ slug: string; short_listed: true; collection_supported: boolean }> {
  return request(`/watchlist/${slug}`, { method: "POST" });
}
