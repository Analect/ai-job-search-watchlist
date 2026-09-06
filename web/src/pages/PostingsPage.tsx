import { useEffect, useState } from "react";

import {
  ApiError,
  fetchPostings,
  fetchSimilar,
  markForAdvancement,
  type PostingSummary,
  type ReviewState,
  type SimilarPosting,
} from "@/lib/api";

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

function SimilarPanel({ postingId }: { postingId: string }) {
  const [results, setResults] = useState<SimilarPosting[] | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    fetchSimilar(postingId)
      .then((res) => {
        if (cancelled) return;
        setResults(res.results);
        setMessage(res.message ?? null);
      })
      .catch((err) => {
        if (cancelled) return;
        setError(err instanceof ApiError ? err.message : (err as Error).message);
      });
    return () => {
      cancelled = true;
    };
  }, [postingId]);

  if (error) return <p className="text-sm text-danger">{error}</p>;
  if (results === null) return <p className="text-sm text-muted">Finding similar postings…</p>;
  if (results.length === 0) {
    return (
      <p className="text-sm text-muted">{message ?? "No similar postings found yet."}</p>
    );
  }
  return (
    <ul className="space-y-2">
      {results.map((s) => (
        <li key={s.id} className="flex items-center justify-between gap-3 text-sm">
          <a
            href={s.source_url}
            target="_blank"
            rel="noreferrer"
            className="text-ink hover:text-accent hover:underline"
          >
            {s.title} <span className="text-muted">— {s.employer_name}</span>
          </a>
          <span className="whitespace-nowrap text-xs text-muted">
            {(s.similarity_score * 100).toFixed(0)}% match
          </span>
        </li>
      ))}
    </ul>
  );
}

function PostingRow({
  posting,
  expanded,
  flagging,
  onToggleSimilar,
  onFlag,
}: {
  posting: PostingSummary;
  expanded: boolean;
  flagging: boolean;
  onToggleSimilar: () => void;
  onFlag: () => void;
}) {
  const location =
    posting.location_city ?? (posting.location_country ? posting.location_country : "—");
  return (
    <>
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
        <td className="py-3 pr-4">
          <ReviewBadge state={posting.review_state} />
        </td>
        <td className="py-3">
          <div className="flex gap-2">
            <button
              type="button"
              onClick={onFlag}
              disabled={flagging || posting.review_state === "flagged_for_advancement"}
              className="rounded-card border border-ok px-2 py-1 text-xs font-medium text-ok disabled:opacity-40"
            >
              {posting.review_state === "flagged_for_advancement" ? "Flagged" : "Flag"}
            </button>
            <button
              type="button"
              onClick={onToggleSimilar}
              className="rounded-card border border-border-subtle px-2 py-1 text-xs font-medium text-muted"
            >
              {expanded ? "Hide similar" : "Similar"}
            </button>
          </div>
        </td>
      </tr>
      {expanded ? (
        <tr className="border-b border-border-subtle last:border-b-0">
          <td colSpan={6} className="px-4 py-3" style={{ background: "var(--bg)" }}>
            <SimilarPanel postingId={posting.id} />
          </td>
        </tr>
      ) : null}
    </>
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

  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [flaggingId, setFlaggingId] = useState<string | null>(null);
  const [flagError, setFlagError] = useState<string | null>(null);

  const flagPosting = (id: string) => {
    setFlaggingId(id);
    setFlagError(null);
    markForAdvancement(id)
      .then(() => {
        // Optimistic, matching HistorySidebar's rename pattern elsewhere
        // in this codebase — the badge should update immediately, not
        // wait for a full refetch of the current page.
        setResults((prev) =>
          prev.map((p) => (p.id === id ? { ...p, review_state: "flagged_for_advancement" } : p)),
        );
        setExpandedId(id); // surface "similar" postings right after flagging
      })
      .catch((err) => {
        setFlagError(err instanceof ApiError ? err.message : (err as Error).message);
      })
      .finally(() => setFlaggingId(null));
  };

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
            {flagError ? (
              <p className="mb-3 text-sm text-danger">Flag failed: {flagError}</p>
            ) : null}
            <table className="w-full border-collapse text-left">
              <thead>
                <tr className="border-b border-border-subtle text-xs font-medium uppercase tracking-wide text-muted">
                  <th className="pb-2 pr-4 font-medium">Posting</th>
                  <th className="pb-2 pr-4 font-medium">Location</th>
                  <th className="pb-2 pr-4 font-medium">Posted</th>
                  <th className="pb-2 pr-4 font-medium">Status</th>
                  <th className="pb-2 pr-4 font-medium">Review</th>
                  <th className="pb-2 font-medium">Actions</th>
                </tr>
              </thead>
              <tbody>
                {results.map((p) => (
                  <PostingRow
                    key={p.id}
                    posting={p}
                    expanded={expandedId === p.id}
                    flagging={flaggingId === p.id}
                    onToggleSimilar={() => setExpandedId((cur) => (cur === p.id ? null : p.id))}
                    onFlag={() => flagPosting(p.id)}
                  />
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
