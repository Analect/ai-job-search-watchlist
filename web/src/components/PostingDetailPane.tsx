import { useEffect, useRef, useState } from "react";

import {
  ApiError,
  postPostingEvent,
  type PostingDetail,
  type ThumbsValue,
} from "@/lib/api";

interface PostingDetailPaneProps {
  detail: PostingDetail | null;
  loading: boolean;
  notFound?: boolean;
  onClose?: () => void;
  onStateChange?: (id: string, patch: Record<string, unknown>) => void;
}

export default function PostingDetailPane({
  detail,
  loading,
  notFound,
  onClose,
  onStateChange,
}: PostingDetailPaneProps) {
  const [savingEvent, setSavingEvent] = useState<string | null>(null);
  const [editingComment, setEditingComment] = useState(false);
  const [commentDraft, setCommentDraft] = useState("");
  const [savingComment, setSavingComment] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // T006: Reset note editor when the selected posting changes so draft text
  // from posting A cannot bleed into posting B.
  const postingId = detail?.posting.id as string | undefined;
  useEffect(() => {
    setEditingComment(false);
    setCommentDraft("");
  }, [postingId]);

  // T007: Track the posting id that was active when a save started so we can
  // bail if the selection changes before the response arrives.
  const saveForId = useRef<string | undefined>(undefined);

  if (loading) {
    return <p className="p-4 text-sm text-muted">Loading…</p>;
  }
  if (notFound) {
    return <p className="p-4 text-sm text-danger">Posting not found — it may have been removed.</p>;
  }
  if (!detail) {
    return (
      <p className="p-4 text-sm text-muted">
        Select a posting above to review it.
      </p>
    );
  }

  const { posting, description } = detail;

  const fire = async (eventType: string, note?: string) => {
    setSavingEvent(eventType);
    setError(null);
    try {
      await postPostingEvent(posting.id as string, eventType, note);
      const patch: Record<string, unknown> = {};
      if (eventType === "reviewed") patch.reviewed = true;
      else if (eventType === "flag_on") patch.flagged = true;
      else if (eventType === "flag_off") patch.flagged = false;
      else if (eventType === "promoted") patch.promoted = true;
      else if (eventType === "withdrawn") patch.promoted = false;
      else if (eventType === "thumbs_up") patch.thumbs = "up";
      else if (eventType === "thumbs_down") patch.thumbs = "down";
      else if (eventType === "thumbs_cleared") patch.thumbs = null;
      onStateChange?.(posting.id as string, patch);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : (err as Error).message);
    } finally {
      setSavingEvent(null);
    }
  };

  const startEditComment = () => {
    setCommentDraft((posting.comment as string) ?? "");
    setEditingComment(true);
  };

  const saveComment = async () => {
    const id = posting.id as string;
    saveForId.current = id;
    setSavingComment(true);
    setError(null);
    try {
      await postPostingEvent(id, "comment_updated", commentDraft.trim() || undefined);
      // T007: discard result if the user has navigated to a different posting
      if (saveForId.current !== id) return;
      onStateChange?.(id, { comment: commentDraft.trim() || null });
      setEditingComment(false);
    } catch (err) {
      if (saveForId.current === id) {
        setError(err instanceof ApiError ? err.message : (err as Error).message);
      }
    } finally {
      if (saveForId.current === id) setSavingComment(false);
    }
  };

  const thumbs = posting.thumbs as ThumbsValue;

  const highlightedDescription = (() => {
    if (!description) return null;
    const rawTerms: string[] = (posting.key_terms as string[] | null) ?? [];
    let terms = rawTerms.filter(Boolean);

    if (terms.length === 0) {
      // Fallback: client-side stopword-filtered term frequency top-N
      const STOPWORDS = new Set([
        "the","a","an","and","or","in","on","of","to","for","with","at","by",
        "from","is","are","was","were","be","been","have","has","had","it","its",
        "this","that","these","those","we","you","they","their","our","your",
        "will","can","may","should","would","could","must","not","no","as",
        "if","but","so","than","then","when","where","who","which","how","all",
        "more","also","other","into","about","up","out","any","each",
      ]);
      const text = description.replace(/<[^>]+>/g, " ").toLowerCase();
      const freq: Record<string, number> = {};
      for (const w of text.split(/\W+/)) {
        if (w.length > 3 && !STOPWORDS.has(w)) freq[w] = (freq[w] ?? 0) + 1;
      }
      terms = Object.entries(freq)
        .sort((a, b) => b[1] - a[1])
        .slice(0, 8)
        .map(([w]) => w);
    }

    if (terms.length === 0) return description;

    const escaped = terms.map((t) => t.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"));
    const pattern = new RegExp(`\\b(${escaped.join("|")})\\b`, "gi");
    return description.replace(pattern, '<mark class="term-highlight">$1</mark>');
  })();
  const flagged = posting.flagged as boolean;
  const promoted = posting.promoted as boolean;

  return (
    <div className="space-y-4 p-4">
      {error ? <p className="text-sm text-danger">{error}</p> : null}

      {/* Header — T044: close button collapses back to full-width list */}
      <div className="flex items-start justify-between gap-2">
        <div>
          <a
            href={posting.source_url as string}
            target="_blank"
            rel="noreferrer"
            className="text-base font-semibold text-ink hover:text-accent hover:underline"
          >
            {posting.title as string}
          </a>
          <p className="text-sm text-muted">{posting.employer_name as string}</p>
        </div>
        {onClose ? (
          <button
            type="button"
            onClick={onClose}
            title="Close detail pane"
            aria-label="Close detail pane"
            className="rounded-card border border-border-subtle px-2 py-1 text-xs text-muted hover:text-ink"
          >
            ✕
          </button>
        ) : null}
      </div>

      {/* Action bar */}
      <div className="flex flex-wrap gap-2">
        <button
          type="button"
          disabled={!!savingEvent}
          onClick={() => fire(flagged ? "flag_off" : "flag_on")}
          className={`rounded-card border px-2 py-1 text-xs font-medium disabled:opacity-40 ${
            flagged
              ? "border-ok bg-ok/10 text-ok"
              : "border-border-subtle text-muted"
          }`}
        >
          {flagged ? "Unflag" : "Flag"}
        </button>

        <button
          type="button"
          disabled={!!savingEvent || promoted}
          onClick={() => fire("promoted")}
          className={`rounded-card border px-2 py-1 text-xs font-medium disabled:opacity-40 ${
            promoted
              ? "border-accent bg-accent/10 text-accent"
              : "border-border-subtle text-muted"
          }`}
        >
          {promoted ? "Promoted" : "Promote"}
        </button>

        {promoted ? (
          <button
            type="button"
            disabled={!!savingEvent}
            onClick={() => fire("withdrawn")}
            className="rounded-card border border-danger px-2 py-1 text-xs font-medium text-danger disabled:opacity-40"
          >
            Withdraw
          </button>
        ) : null}

        <button
          type="button"
          disabled={!!savingEvent}
          onClick={() => fire(thumbs === "up" ? "thumbs_cleared" : "thumbs_up")}
          className={`rounded-card border px-2 py-1 text-xs font-medium disabled:opacity-40 ${
            thumbs === "up" ? "border-ok bg-ok/10 text-ok" : "border-border-subtle text-muted"
          }`}
        >
          👍
        </button>

        <button
          type="button"
          disabled={!!savingEvent}
          onClick={() => fire(thumbs === "down" ? "thumbs_cleared" : "thumbs_down")}
          className={`rounded-card border px-2 py-1 text-xs font-medium disabled:opacity-40 ${
            thumbs === "down"
              ? "border-danger bg-danger/10 text-danger"
              : "border-border-subtle text-muted"
          }`}
        >
          👎
        </button>
      </div>

      {/* Comment */}
      <div>
        {editingComment ? (
          <div className="flex gap-2">
            <textarea
              autoFocus
              value={commentDraft}
              onChange={(e) => setCommentDraft(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); saveComment(); }
                if (e.key === "Escape") setEditingComment(false);
              }}
              rows={3}
              className="min-w-0 flex-1 rounded-card border border-border-subtle bg-surface px-3 py-1.5 text-sm text-ink"
            />
            <div className="flex flex-col gap-1">
              <button
                type="button"
                disabled={savingComment}
                onClick={saveComment}
                className="rounded-card border border-border-subtle px-3 py-1 text-sm disabled:opacity-40"
              >
                Save
              </button>
              <button
                type="button"
                onClick={() => setEditingComment(false)}
                className="rounded-card border border-border-subtle px-3 py-1 text-sm text-muted"
              >
                Cancel
              </button>
            </div>
          </div>
        ) : (
          <div className="flex items-start gap-2">
            <p className="flex-1 text-sm text-ink">
              {posting.comment ? (posting.comment as string) : <span className="text-muted">No comment yet.</span>}
            </p>
            <button
              type="button"
              onClick={startEditComment}
              className="rounded-card border border-border-subtle px-2 py-1 text-xs text-muted"
              title="Edit comment"
            >
              ✏️
            </button>
          </div>
        )}
      </div>

      {/* Description */}
      <div className="rounded-card border border-border-subtle bg-surface p-3">
        {description ? (
          <div
            className="prose prose-sm max-w-none text-ink"
            dangerouslySetInnerHTML={{ __html: highlightedDescription ?? description }}
          />
        ) : (
          <p className="text-sm text-muted">
            Description unavailable.{" "}
            <a
              href={posting.source_url as string}
              target="_blank"
              rel="noreferrer"
              className="text-accent underline"
            >
              View on source site
            </a>
          </p>
        )}
      </div>
    </div>
  );
}
