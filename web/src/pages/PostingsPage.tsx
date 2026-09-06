import { useEffect, useState } from "react";

import { ApiError, fetchPostings, type PostingSummary, type ReviewState } from "@/lib/api";

const PAGE_SIZE = 25;

const REVIEW_BADGE: Record<ReviewState, { label: string; className: string }> = {
  unreviewed: { label: "Unreviewed", className: "border-border-subtle text-muted" },
  flagged_for_advancement: { label: "Flagged", className: "border-ok text-ok" },
  dismissed: { label: "Dismissed", className: "border-danger text-danger" },
};

function ReviewBadge({ state }: { state: ReviewState }) {
  const badge = REVIEW_BADGE[state];
  return (
    <span
      className={`whitespace-nowrap rounded-card border px-2 py-0.5 text-xs font-medium ${badge.className}`}
    >
      {badge.label}
    </span>
  );
}

function formatDate(iso: string | null): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleDateString(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
  });
}

function PostingRow({ posting }: { posting: PostingSummary }) {
  const location =
    posting.location_city ?? (posting.location_country ? posting.location_country : "—");
  return (
    <tr className="border-b border-border-subtle last:border-b-0">
      <td className="py-3 pr-4">
        <a
          href={posting.source_url}
          target="_blank"
          rel="noreferrer"
          className="font-medium text-ink hover:text-accent hover:underline"
        >
          {posting.title}
        </a>
        <p className="text-xs text-muted">{posting.employer_name}</p>
      </td>
      <td className="py-3 pr-4 text-sm text-muted">{location}</td>
      <td className="py-3 pr-4 text-sm text-muted">{formatDate(posting.posted_date)}</td>
      <td className="py-3 pr-4 text-sm capitalize text-muted">{posting.status}</td>
      <td className="py-3">
        <ReviewBadge state={posting.review_state} />
      </td>
    </tr>
  );
}

export default function PostingsPage() {
  const [location, setLocation] = useState("");
  const [status, setStatus] = useState("");
  const [reviewState, setReviewState] = useState("");
  const [query, setQuery] = useState("");
  const [offset, setOffset] = useState(0);

  const [results, setResults] = useState<PostingSummary[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Any filter change resets pagination — staying on page 3 of a
  // now-different result set would silently show the wrong slice.
  useEffect(() => {
    setOffset(0);
  }, [location, status, reviewState, query]);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    fetchPostings({
      location: location || undefined,
      status: status || undefined,
      review_state: reviewState || undefined,
      query: query || undefined,
      limit: PAGE_SIZE,
      offset,
    })
      .then((res) => {
        if (cancelled) return;
        setResults(res.results);
        setTotal(res.total);
        setError(null);
      })
      .catch((err) => {
        if (cancelled) return;
        setError(err instanceof ApiError ? err.message : (err as Error).message);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [location, status, reviewState, query, offset]);

  const rangeStart = total === 0 ? 0 : offset + 1;
  const rangeEnd = Math.min(offset + PAGE_SIZE, total);

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-3 rounded-card border border-border-subtle bg-surface p-4">
        <select
          value={location}
          onChange={(e) => setLocation(e.target.value)}
          className="rounded-card border border-border-subtle bg-surface px-3 py-1.5 text-sm text-ink"
        >
          <option value="">Any location</option>
          <option value="london">London</option>
          <option value="dublin">Dublin</option>
          <option value="other">Other</option>
        </select>
        <select
          value={status}
          onChange={(e) => setStatus(e.target.value)}
          className="rounded-card border border-border-subtle bg-surface px-3 py-1.5 text-sm text-ink"
        >
          <option value="">Any status</option>
          <option value="open">Open</option>
          <option value="closed">Closed</option>
        </select>
        <select
          value={reviewState}
          onChange={(e) => setReviewState(e.target.value)}
          className="rounded-card border border-border-subtle bg-surface px-3 py-1.5 text-sm text-ink"
        >
          <option value="">Any review state</option>
          <option value="unreviewed">Unreviewed</option>
          <option value="flagged_for_advancement">Flagged</option>
          <option value="dismissed">Dismissed</option>
        </select>
        <input
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Search title, department, skills…"
          className="min-w-[220px] flex-1 rounded-card border border-border-subtle bg-surface px-3 py-1.5 text-sm text-ink placeholder:text-muted"
        />
      </div>

      <div className="rounded-card border border-border-subtle bg-surface p-4">
        {loading ? (
          <p className="py-6 text-center text-sm text-muted">Loading…</p>
        ) : error ? (
          <p className="py-6 text-center text-sm text-danger">{error}</p>
        ) : results.length === 0 ? (
          <p className="py-6 text-center text-sm text-muted">No postings match these filters.</p>
        ) : (
          <>
            <table className="w-full border-collapse text-left">
              <thead>
                <tr className="border-b border-border-subtle text-xs font-medium uppercase tracking-wide text-muted">
                  <th className="pb-2 pr-4 font-medium">Posting</th>
                  <th className="pb-2 pr-4 font-medium">Location</th>
                  <th className="pb-2 pr-4 font-medium">Posted</th>
                  <th className="pb-2 pr-4 font-medium">Status</th>
                  <th className="pb-2 font-medium">Review</th>
                </tr>
              </thead>
              <tbody>
                {results.map((p) => (
                  <PostingRow key={p.id} posting={p} />
                ))}
              </tbody>
            </table>
            <div className="mt-4 flex items-center justify-between text-sm text-muted">
              <span>
                {rangeStart}–{rangeEnd} of {total}
              </span>
              <div className="flex gap-2">
                <button
                  type="button"
                  disabled={offset === 0}
                  onClick={() => setOffset((o) => Math.max(0, o - PAGE_SIZE))}
                  className="rounded-card border border-border-subtle px-3 py-1 disabled:opacity-40"
                >
                  Previous
                </button>
                <button
                  type="button"
                  disabled={rangeEnd >= total}
                  onClick={() => setOffset((o) => o + PAGE_SIZE)}
                  className="rounded-card border border-border-subtle px-3 py-1 disabled:opacity-40"
                >
                  Next
                </button>
              </div>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
