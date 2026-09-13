// Thin fetch client for job-search-api. No auth header logic lives here —
// per job-search-api.contract.md, the API trusts whatever identity the
// platform gateway already established; this client is a plain fetch
// wrapper, not a token-attaching client.

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

// 017: new review-state vocabulary
export type ReviewState =
  | "unreviewed"
  | "reviewed"
  | "flagged"
  | "promoted"
  | "thumbs_up"
  | "thumbs_down";

export type ThumbsValue = "up" | "down" | null;

// 017: extended PostingSummary with independent review-state fields
export interface PostingSummary {
  id: string;
  employer_name: string;
  title: string;
  location_city: string | null;
  location_country: string | null;
  location_unknown: boolean;
  posted_date: string | null;
  status: "open" | "closed" | "unknown";
  reviewed: boolean;
  flagged: boolean;
  promoted: boolean;
  thumbs: ThumbsValue;
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
  review_state?: ReviewState | "";
  query?: string;
  company?: string;
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
  posting: PostingSummary & {
    comment: string | null;
    key_terms: string[];
    description?: string;
    [key: string]: unknown;
  };
  description: string | null;
  events: JobEvent[];
}

export function fetchPostingDetail(id: string): Promise<PostingDetail> {
  return request<PostingDetail>(`/postings/${id}`);
}

// 017: replaces markForAdvancement — generic event writer
export function postPostingEvent(
  id: string,
  event_type: string,
  note?: string,
): Promise<JobEvent> {
  return request<JobEvent>(`/postings/${id}/events`, {
    method: "POST",
    body: JSON.stringify({ event_type, note: note ?? null }),
  });
}

export function bulkMarkReviewed(posting_ids: string[]): Promise<{ updated: number }> {
  return request(`/postings/bulk-review`, {
    method: "POST",
    body: JSON.stringify({ posting_ids }),
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

// --- Employer map / watchlist ---

export interface MapCompany {
  slug: string;
  name: string;
  industry: string | null;
  x: number;
  y: number;
  short_listed: boolean;
  ats_types: string | null;
  description: string | null;
  same_as: string[] | null;
  wikidata_id: string | null;
  website: string | null;
  boards: { type: string; url: string }[] | null;
  ats_active: boolean;
}

export function fetchMapCoordinates(): Promise<{ companies: MapCompany[] }> {
  return request(`/map/coordinates`);
}

export function fetchDendrogram(): Promise<{ slugs: string[]; tree: unknown }> {
  return request(`/map/dendrogram`);
}

export function addToWatchlist(
  slug: string,
): Promise<{ slug: string; short_listed: true; collection_supported: boolean }> {
  return request(`/watchlist/${slug}`, { method: "POST" });
}

export function removeFromWatchlist(slug: string): Promise<{ slug: string; short_listed: false }> {
  return request(`/watchlist/${slug}`, { method: "DELETE" });
}

export interface SimilarEmployer {
  slug: string;
  name: string;
  industry: string | null;
  short_listed: boolean;
  distance: number;
}

export function fetchSimilarEmployers(
  slug: string,
  limit = 5,
): Promise<{ results: SimilarEmployer[] }> {
  return request(`/employers/${slug}/similar?limit=${limit}`);
}

// --- Job map ---

export interface MapJob {
  id: string;
  employer_name: string;
  title: string;
  x: number;
  y: number;
  promoted: boolean;
  reviewed: boolean;
  flagged: boolean;
  thumbs: ThumbsValue;
}

export function fetchJobMapCoordinates(): Promise<{ jobs: MapJob[] }> {
  return request(`/jobs/map/coordinates`);
}

export function fetchPromotedJobs(): Promise<PostingsResult> {
  return request(`/jobs/promoted`);
}

// --- Applications ---

export interface Application {
  id: string;
  job_posting_id: string;
  title: string;
  employer_name: string;
  status: "promoted" | "drafting" | "submitted" | "withdrawn";
  resume_draft_mr_url: string | null;
  draft_generated_at: string | null;
  application_notes: string | null;
  draft_model_id: string | null;
  draft_error: string | null;
}

export function fetchApplications(): Promise<{ results: Application[] }> {
  return request(`/applications`);
}

export function advanceApplicationStatus(
  job_posting_id: string,
  status: "drafting" | "submitted",
): Promise<Application> {
  return request(`/applications/${job_posting_id}/status`, {
    method: "POST",
    body: JSON.stringify({ status }),
  });
}

export interface DraftResult {
  status: "pending" | "complete" | "failed" | "idle";
  resume_draft_branch?: string;
  resume_draft_mr_url?: string;
  resume_draft_path?: string;
  cover_letter_draft_path?: string;
  draft_generated_at?: string;
  draft_model_id?: string | null;
  error?: string;
}

export function generateDrafts(job_posting_id: string): Promise<DraftResult> {
  return request(`/applications/${job_posting_id}/generate-drafts`, { method: "POST" });
}

export function getDraftStatus(job_posting_id: string): Promise<DraftResult> {
  return request(`/applications/${job_posting_id}/draft-status`);
}

export interface DraftFiles {
  resume: string;
  cover_letter: string;
}

export function getDraftFiles(job_posting_id: string): Promise<DraftFiles> {
  return request(`/applications/${job_posting_id}/draft-files`);
}

export function saveDraftFiles(
  job_posting_id: string,
  resume: string,
  cover_letter: string,
): Promise<{ committed_at: string }> {
  return request(`/applications/${job_posting_id}/draft-files`, {
    method: "PATCH",
    body: JSON.stringify({ resume, cover_letter }),
  });
}

export function mergeDraft(
  job_posting_id: string,
): Promise<{ status: string; final_url: string }> {
  return request(`/applications/${job_posting_id}/draft-merge`, { method: "POST" });
}

export function saveApplicationNotes(
  job_posting_id: string,
  notes: string,
): Promise<Application> {
  return request(`/applications/${job_posting_id}/notes`, {
    method: "PATCH",
    body: JSON.stringify({ notes }),
  });
}

export function fetchEmployerPostings(
  slug: string,
): Promise<{ results: { id: string; title: string; posted_date: string | null }[] }> {
  return request(`/employers/${slug}/postings`);
}
