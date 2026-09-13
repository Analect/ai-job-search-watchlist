import { useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";

import PostingDetailPane from "@/components/PostingDetailPane";
import SplitPane from "@/components/SplitPane";
import {
  ApiError,
  bulkMarkReviewed,
  fetchMapCoordinates,
  fetchPostingDetail,
  fetchPostings,
  postPostingEvent,
  type MapCompany,
  type PostingDetail,
  type PostingSummary,
  type ReviewState,
} from "@/lib/api";

const PAGE_SIZE = 25;

const REVIEW_BADGE: Record<ReviewState, { label: string; className: string }> = {
  unreviewed: { label: "Unreviewed", className: "border-border-subtle text-muted" },
  reviewed: { label: "Reviewed", className: "border-border-subtle text-ink" },
  flagged: { label: "Flagged", className: "border-ok text-ok" },
  promoted: { label: "Promoted", className: "border-accent text-accent" },
  thumbs_up: { label: "👍", className: "border-ok text-ok" },
  thumbs_down: { label: "👎", className: "border-danger text-danger" },
};

function ReviewBadge({ state }: { state: ReviewState }) {
  const badge = REVIEW_BADGE[state] ?? REVIEW_BADGE.unreviewed;
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

function PostingRow({
  posting,
  selected,
  checked,
  onSelect,
  onCheck,
}: {
  posting: PostingSummary;
  selected: boolean;
  checked: boolean;
  onSelect: () => void;
  onCheck: (checked: boolean) => void;
}) {
  const location =
    posting.location_city ??
    (posting.location_unknown
      ? "Unknown"
      : posting.location_country ?? "—");

  return (
    <tr
      className={`cursor-pointer border-b border-border-subtle last:border-b-0 ${
        selected ? "bg-accent/5" : "hover:bg-surface/50"
      }`}
      onClick={onSelect}
    >
      <td className="py-2 pr-2" onClick={(e) => e.stopPropagation()}>
        <input
          type="checkbox"
          checked={checked}
          onChange={(e) => onCheck(e.target.checked)}
          className="rounded"
        />
      </td>
      <td className="py-3 pr-4">
        <a
          href={posting.source_url}
          target="_blank"
          rel="noreferrer"
          onClick={(e) => e.stopPropagation()}
          className="font-medium text-ink hover:text-accent hover:underline"
        >
          {posting.title}
        </a>
        <p className="text-xs text-muted">{posting.employer_name}</p>
      </td>
      <td className="py-3 pr-4 text-sm text-muted">
        {location}
        {posting.location_unknown ? (
          <span className="ml-1 text-xs text-muted/60">(unknown)</span>
        ) : null}
      </td>
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
  const [company, setCompany] = useState("");
  const [offset, setOffset] = useState(0);

  const [watchlistCompanies, setWatchlistCompanies] = useState<MapCompany[]>([]);
  useEffect(() => {
    fetchMapCoordinates()
      .then((res) => setWatchlistCompanies(res.companies.filter((c) => c.short_listed)))
      .catch(() => null);
  }, []);

  const [results, setResults] = useState<PostingSummary[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [searchParams, setSearchParams] = useSearchParams();

  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [splitActive, setSplitActive] = useState(false);
  const [detail, setDetail] = useState<PostingDetail | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [detailNotFound, setDetailNotFound] = useState(false);

  const [refreshKey, setRefreshKey] = useState(0);

  // T011: Pre-select posting from ?selected=<id> query param on initial mount.
  useEffect(() => {
    const id = searchParams.get("selected");
    if (id) selectPosting(id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const [checkedIds, setCheckedIds] = useState<Set<string>>(new Set());
  const [bulkReviewing, setBulkReviewing] = useState(false);
  const [bulkMessage, setBulkMessage] = useState<string | null>(null);

  // Filter changes reset pagination
  useEffect(() => {
    setOffset(0);
  }, [location, status, reviewState, query, company]);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    fetchPostings({
      location: location || undefined,
      status: status || undefined,
      review_state: (reviewState as ReviewState) || undefined,
      query: query || undefined,
      company: company || undefined,
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
  }, [location, status, reviewState, query, company, offset, refreshKey]);

  const selectPosting = (id: string) => {
    setSelectedId(id);
    setSplitActive(true);
    setDetailLoading(true);
    setDetail(null);
    setDetailNotFound(false);
    // T010: write ?selected=<id> so the URL reflects the selection
    setSearchParams((prev) => { prev.set("selected", id); return prev; });
    fetchPostingDetail(id)
      .then((d) => {
        setDetail(d);
        // Auto-mark reviewed on first open (FR-003)
        if (!d.posting.reviewed) {
          postPostingEvent(id, "reviewed").catch(() => null);
          setResults((prev) =>
            prev.map((p) => (p.id === id ? { ...p, reviewed: true, review_state: p.review_state === "unreviewed" ? "reviewed" : p.review_state } : p)),
          );
        }
      })
      .catch((err) => {
        // T012: surface a clear "not found" state rather than a blank pane
        if (err instanceof ApiError && err.status === 404) setDetailNotFound(true);
      })
      .finally(() => setDetailLoading(false));
  };

  const handleStateChange = (id: string, patch: Record<string, unknown>) => {
    setResults((prev) =>
      prev.map((p) => {
        if (p.id !== id) return p;
        const updated = { ...p, ...patch } as PostingSummary;
        // Recompute derived review_state label
        if (updated.promoted) updated.review_state = "promoted";
        else if (updated.flagged) updated.review_state = "flagged";
        else if (updated.thumbs === "up") updated.review_state = "thumbs_up";
        else if (updated.thumbs === "down") updated.review_state = "thumbs_down";
        else if (updated.reviewed) updated.review_state = "reviewed";
        else updated.review_state = "unreviewed";
        return updated;
      }),
    );
    // Merge patch into current detail too
    if (detail && detail.posting.id === id) {
      setDetail((d) => d ? { ...d, posting: { ...d.posting, ...patch } } : d);
    }
  };

  const toggleCheck = (id: string, checked: boolean) => {
    setCheckedIds((prev) => {
      const next = new Set(prev);
      if (checked) next.add(id);
      else next.delete(id);
      return next;
    });
  };

  const bulkReview = () => {
    if (checkedIds.size === 0) return;
    setBulkReviewing(true);
    setBulkMessage(null);
    bulkMarkReviewed([...checkedIds])
      .then((res) => {
        setBulkMessage(`Marked ${res.updated} posting${res.updated !== 1 ? "s" : ""} as reviewed.`);
        setResults((prev) =>
          prev.map((p) =>
            checkedIds.has(p.id) && !p.reviewed
              ? {
                  ...p,
                  reviewed: true,
                  review_state: p.review_state === "unreviewed" ? "reviewed" : p.review_state,
                }
              : p,
          ),
        );
        setCheckedIds(new Set());
      })
      .catch((err) => {
        setBulkMessage(
          `Bulk review failed: ${err instanceof ApiError ? err.message : (err as Error).message}`,
        );
      })
      .finally(() => setBulkReviewing(false));
  };

  const rangeStart = total === 0 ? 0 : offset + 1;
  const rangeEnd = Math.min(offset + PAGE_SIZE, total);

  const postingsList = (
    <div className="space-y-3 p-3">
      {/* Filter bar */}
      <div className="flex flex-wrap items-center gap-3 rounded-card border border-border-subtle bg-surface p-3">
        <select
          value={location}
          onChange={(e) => setLocation(e.target.value)}
          className="rounded-card border border-border-subtle bg-surface px-3 py-1.5 text-sm text-ink"
        >
          <option value="">Any location</option>
          <option value="london">London</option>
          <option value="dublin">Dublin</option>
          <option value="other">Other / Unknown</option>
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
          <option value="reviewed">Reviewed</option>
          <option value="flagged">Flagged</option>
          <option value="promoted">Promoted</option>
          <option value="thumbs_up">👍 Thumbs up</option>
          <option value="thumbs_down">👎 Thumbs down</option>
        </select>
        {watchlistCompanies.length > 0 ? (
          <select
            value={company}
            onChange={(e) => setCompany(e.target.value)}
            className="max-w-[200px] rounded-card border border-border-subtle bg-surface px-3 py-1.5 text-sm text-ink"
          >
            <option value="">Any company</option>
            {watchlistCompanies.map((c) => (
              <option key={c.slug} value={c.slug}>
                {c.name}
              </option>
            ))}
          </select>
        ) : null}
        <input
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Search title, description, skills…"
          className="min-w-[220px] flex-1 rounded-card border border-border-subtle bg-surface px-3 py-1.5 text-sm text-ink placeholder:text-muted"
        />
        {/* T014: icon-only refresh with tooltip to keep the toolbar single-row */}
        <button
          type="button"
          disabled={loading}
          onClick={() => setRefreshKey((k) => k + 1)}
          title="Refresh"
          aria-label="Refresh"
          className="rounded-card border border-border-subtle px-2.5 py-1.5 text-base text-muted disabled:opacity-40"
        >
          ↻
        </button>
      </div>

      {/* Bulk action bar */}
      {checkedIds.size > 0 ? (
        <div className="flex items-center gap-3 rounded-card border border-border-subtle bg-surface px-3 py-2">
          <span className="text-sm text-muted">{checkedIds.size} selected</span>
          <button
            type="button"
            disabled={bulkReviewing}
            onClick={bulkReview}
            className="rounded-card border border-border-subtle px-3 py-1 text-sm disabled:opacity-40"
          >
            Mark Reviewed
          </button>
          <button
            type="button"
            onClick={() => setCheckedIds(new Set())}
            className="text-sm text-muted hover:text-ink"
          >
            Clear
          </button>
        </div>
      ) : null}

      {bulkMessage ? (
        <p className="text-sm text-ink">{bulkMessage}</p>
      ) : null}

      {/* Table */}
      <div className="rounded-card border border-border-subtle bg-surface">
        {loading ? (
          <p className="py-6 text-center text-sm text-muted">Loading…</p>
        ) : error ? (
          <p className="py-6 text-center text-sm text-danger">{error}</p>
        ) : results.length === 0 ? (
          <p className="py-6 text-center text-sm text-muted">No postings match these filters.</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full border-collapse text-left">
              <thead>
                <tr className="border-b border-border-subtle text-xs font-medium uppercase tracking-wide text-muted">
                  <th className="pb-2 pr-2 font-medium" />
                  <th className="pb-2 pr-4 font-medium">Posting</th>
                  <th className="pb-2 pr-4 font-medium">Location</th>
                  <th className="pb-2 pr-4 font-medium">Posted</th>
                  <th className="pb-2 pr-4 font-medium">Status</th>
                  <th className="pb-2 font-medium">Review</th>
                </tr>
              </thead>
              <tbody>
                {results.map((p) => (
                  <PostingRow
                    key={p.id}
                    posting={p}
                    selected={selectedId === p.id}
                    checked={checkedIds.has(p.id)}
                    onSelect={() => selectPosting(p.id)}
                    onCheck={(c) => toggleCheck(p.id, c)}
                  />
                ))}
              </tbody>
            </table>
          </div>
        )}

        {/* Pagination */}
        {!loading && !error && total > 0 ? (
          <div className="flex items-center justify-between p-3 text-sm text-muted">
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
        ) : null}
      </div>
    </div>
  );

  if (!splitActive) {
    return <div className="h-full overflow-auto">{postingsList}</div>;
  }

  return (
    <div style={{ height: "calc(100vh - 100px)" }}>
      <SplitPane
        top={postingsList}
        bottom={
          <PostingDetailPane
            detail={detail}
            loading={detailLoading}
            notFound={detailNotFound}
            onClose={() => {
              // T045: collapse detail pane and clear ?selected from URL
              setSplitActive(false);
              setSelectedId(null);
              setDetail(null);
              setDetailNotFound(false);
              setSearchParams((prev) => { prev.delete("selected"); return prev; });
            }}
            onStateChange={handleStateChange}
          />
        }
        defaultTopPercent={55}
      />
    </div>
  );
}
