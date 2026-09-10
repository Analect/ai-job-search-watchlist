import { useState } from "react";

import {
  ApiError,
  postPostingEvent,
  type PostingDetail,
  type ThumbsValue,
} from "@/lib/api";

interface PostingDetailPaneProps {
  detail: PostingDetail | null;
  loading: boolean;
  onStateChange?: (id: string, patch: Record<string, unknown>) => void;
}

export default function PostingDetailPane({
  detail,
  loading,
  onStateChange,
}: PostingDetailPaneProps) {
  const [savingEvent, setSavingEvent] = useState<string | null>(null);
  const [comment, setComment] = useState("");
  const [savingComment, setSavingComment] = useState(false);
  const [error, setError] = useState<string | null>(null);

  if (loading) {
    return <p className="p-4 text-sm text-muted">Loading…</p>;
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

  const saveComment = async () => {
    if (!comment.trim()) return;
    setSavingComment(true);
    setError(null);
    try {
      await postPostingEvent(posting.id as string, "comment_updated", comment.trim());
      onStateChange?.(posting.id as string, { comment: comment.trim() });
      setComment("");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : (err as Error).message);
    } finally {
      setSavingComment(false);
    }
  };

  const thumbs = posting.thumbs as ThumbsValue;
  const flagged = posting.flagged as boolean;
  const promoted = posting.promoted as boolean;

  return (
    <div className="space-y-4 p-4">
      {error ? <p className="text-sm text-danger">{error}</p> : null}

      {/* Header */}
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
      <div className="flex gap-2">
        <input
          value={comment}
          onChange={(e) => setComment(e.target.value)}
          placeholder={posting.comment ? (posting.comment as string) : "Add a comment…"}
          className="min-w-0 flex-1 rounded-card border border-border-subtle bg-surface px-3 py-1.5 text-sm text-ink placeholder:text-muted"
        />
        <button
          type="button"
          disabled={savingComment || !comment.trim()}
          onClick={saveComment}
          className="rounded-card border border-border-subtle px-3 py-1.5 text-sm disabled:opacity-40"
        >
          Save
        </button>
      </div>

      {/* Description */}
      <div className="rounded-card border border-border-subtle bg-surface p-3">
        {description ? (
          <div
            className="prose prose-sm max-w-none text-ink"
            dangerouslySetInnerHTML={{ __html: description }}
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
