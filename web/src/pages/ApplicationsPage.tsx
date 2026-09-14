import React, { useEffect, useRef, useState } from "react";

import {
  ApiError,
  advanceApplicationStatus,
  fetchApplications,
  fetchPostingDetail,
  generateDrafts,
  getApplicationTrace,
  getDraftFiles,
  getDraftStatus,
  mergeDraft,
  redraft,
  postPostingEvent,
  saveApplicationNotes,
  saveDraftFiles,
  type Application,
  type DraftFiles,
  type DraftResult,
  type TraceSpan,
} from "@/lib/api";
import { TraceDrawer } from "@/components/TraceDrawer";

function formatDate(iso: string | null | undefined): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleDateString(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
  });
}

const STATUS_LABEL: Record<Application["status"], string> = {
  promoted: "Promoted",
  drafting: "Drafting",
  submitted: "Submitted",
  withdrawn: "Withdrawn",
};

const STATUS_CLASS: Record<Application["status"], string> = {
  promoted: "text-accent",
  drafting: "text-ok",
  submitted: "text-ink font-medium",
  withdrawn: "text-muted line-through",
};

export default function ApplicationsPage() {
  const [applications, setApplications] = useState<Application[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [draftingId, setDraftingId] = useState<string | null>(null);
  const pollIntervalRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // T046/T047: row selection + description fetch
  const [selectedPostingId, setSelectedPostingId] = useState<string | null>(null);
  const [descLoading, setDescLoading] = useState(false);
  const [descText, setDescText] = useState<string | null>(null);

  // T048/T049/T050: expand-to-edit notes
  const [editingNotes, setEditingNotes] = useState(false);
  const [notesDraft, setNotesDraft] = useState("");
  const [savingNotes, setSavingNotes] = useState(false);
  const [notesError, setNotesError] = useState<string | null>(null);
  const saveNotesForId = useRef<string | null>(null);

  // Trace panel
  const [traceAppId, setTraceAppId] = useState<string | null>(null);
  const [traceId, setTraceId] = useState<string | null>(null);
  const [traceSpans, setTraceSpans] = useState<TraceSpan[] | null>(null);
  const [traceLoading, setTraceLoading] = useState(false);
  const [traceError, setTraceError] = useState<string | null>(null);

  // T058-T060: in-app draft viewer/editor
  const [draftPanelId, setDraftPanelId] = useState<string | null>(null);
  const [draftFiles, setDraftFiles] = useState<DraftFiles | null>(null);
  const [draftLoading, setDraftLoading] = useState(false);
  const [draftSaving, setDraftSaving] = useState(false);
  const [draftMerging, setDraftMerging] = useState(false);
  const [draftError, setDraftError] = useState<string | null>(null);
  const [draftFinalUrl, setDraftFinalUrl] = useState<string | null>(null);

  useEffect(() => {
    setDescLoading(false);
    setDescText(null);
    setEditingNotes(false);
    setNotesDraft("");
    setNotesError(null);
    if (!selectedPostingId) return;
    setDescLoading(true);
    fetchPostingDetail(selectedPostingId)
      .then((detail) => setDescText(detail.description ?? null))
      .catch(() => setDescText(null))
      .finally(() => setDescLoading(false));
  }, [selectedPostingId]);

  useEffect(() => {
    fetchApplications()
      .then((res) => setApplications(res.results))
      .catch((err) => setError(err instanceof ApiError ? err.message : (err as Error).message))
      .finally(() => setLoading(false));
    return () => {
      if (pollIntervalRef.current) clearInterval(pollIntervalRef.current);
    };
  }, []);

  const advanceStatus = (app: Application, status: "drafting" | "submitted") => {
    setActionError(null);
    advanceApplicationStatus(app.job_posting_id, status)
      .then(() => {
        setApplications((prev) =>
          prev.map((a) => (a.id === app.id ? { ...a, status } : a)),
        );
      })
      .catch((err) =>
        setActionError(err instanceof ApiError ? err.message : (err as Error).message),
      );
  };

  const withdraw = (app: Application) => {
    setActionError(null);
    postPostingEvent(app.job_posting_id, "withdrawn")
      .then(() => {
        setApplications((prev) =>
          prev.map((a) => (a.id === app.id ? { ...a, status: "withdrawn" } : a)),
        );
      })
      .catch((err) =>
        setActionError(err instanceof ApiError ? err.message : (err as Error).message),
      );
  };

  const applyCompletedDraft = (appId: string, draft: DraftResult) => {
    setApplications((prev) =>
      prev.map((a) =>
        a.id === appId
          ? {
              ...a,
              status: "drafting",
              resume_draft_mr_url: draft.resume_draft_mr_url ?? null,
              draft_generated_at: draft.draft_generated_at ?? null,
              draft_model_id: draft.draft_model_id ?? null,
              draft_error: null,
            }
          : a,
      ),
    );
    setDraftingId(null);
  };

  const startPolling = (appId: string, jobPostingId: string) => {
    if (pollIntervalRef.current) clearInterval(pollIntervalRef.current);
    pollIntervalRef.current = setInterval(() => {
      getDraftStatus(jobPostingId)
        .then((result: DraftResult) => {
          if (result.status === "complete") {
            clearInterval(pollIntervalRef.current!);
            pollIntervalRef.current = null;
            applyCompletedDraft(appId, result);
          } else if (result.status === "failed") {
            clearInterval(pollIntervalRef.current!);
            pollIntervalRef.current = null;
            setActionError(result.error ?? "Draft generation failed");
            setApplications((prev) =>
              prev.map((a) =>
                a.job_posting_id === jobPostingId
                  ? { ...a, draft_error: result.error ?? "Draft generation failed" }
                  : a,
              ),
            );
            setDraftingId(null);
          }
        })
        .catch((err) => {
          clearInterval(pollIntervalRef.current!);
          pollIntervalRef.current = null;
          setActionError(err instanceof ApiError ? err.message : (err as Error).message);
          setDraftingId(null);
        });
    }, 3000);
  };

  const generateDraft = (app: Application) => {
    setDraftingId(app.job_posting_id);
    setActionError(null);
    generateDrafts(app.job_posting_id)
      .then((result: DraftResult) => {
        if (result.status === "complete") {
          applyCompletedDraft(app.id, result);
        } else if (result.status === "pending") {
          startPolling(app.id, app.job_posting_id);
        } else if (result.status === "failed") {
          setActionError(result.error ?? "Draft generation failed");
          setDraftingId(null);
        }
      })
      .catch((err) => {
        setActionError(err instanceof ApiError ? err.message : (err as Error).message);
        setDraftingId(null);
      });
  };

  const redraftApp = (app: Application) => {
    setDraftingId(app.job_posting_id);
    setActionError(null);
    setApplications((prev) =>
      prev.map((a) => (a.id === app.id ? { ...a, resume_draft_mr_url: null } : a)),
    );
    redraft(app.job_posting_id)
      .then((result: DraftResult) => {
        if (result.status === "complete") {
          applyCompletedDraft(app.id, result);
        } else if (result.status === "pending") {
          startPolling(app.id, app.job_posting_id);
        } else if (result.status === "failed") {
          setActionError(result.error ?? "Re-draft failed");
          setDraftingId(null);
        }
      })
      .catch((err) => {
        setActionError(err instanceof ApiError ? err.message : (err as Error).message);
        setDraftingId(null);
      });
  };

  const selectApp = (postingId: string) => {
    setSelectedPostingId((prev) => (prev === postingId ? null : postingId));
  };

  const startEditNotes = (app: Application, e: React.MouseEvent) => {
    e.stopPropagation();
    setSelectedPostingId(app.job_posting_id);
    setNotesDraft(app.application_notes ?? "");
    setEditingNotes(true);
  };

  const saveNotes = async (app: Application) => {
    const id = app.job_posting_id;
    saveNotesForId.current = id;
    setSavingNotes(true);
    setNotesError(null);
    try {
      await saveApplicationNotes(id, notesDraft.trim() || null);
      if (saveNotesForId.current !== id) return;
      setApplications((prev) =>
        prev.map((a) =>
          a.job_posting_id === id ? { ...a, application_notes: notesDraft.trim() || null } : a,
        ),
      );
      setEditingNotes(false);
    } catch (err) {
      if (saveNotesForId.current === id) {
        setNotesError(err instanceof ApiError ? err.message : (err as Error).message);
      }
    } finally {
      if (saveNotesForId.current === id) setSavingNotes(false);
    }
  };

  const openDraftPanel = (app: Application, e: React.MouseEvent) => {
    e.stopPropagation();
    setSelectedPostingId(app.job_posting_id);
    setDraftPanelId(app.job_posting_id);
    setDraftFiles(null);
    setDraftError(null);
    setDraftFinalUrl(null);
    setDraftLoading(true);
    getDraftFiles(app.job_posting_id)
      .then((files) => { setDraftFiles(files); })
      .catch((err) => {
        setDraftError(err instanceof ApiError ? err.message : (err as Error).message);
      })
      .finally(() => setDraftLoading(false));
  };

  const closeDraftPanel = () => {
    setDraftPanelId(null);
    setDraftFiles(null);
    setDraftError(null);
    setDraftFinalUrl(null);
  };

  const openTrace = (app: Application, e: React.MouseEvent) => {
    e.stopPropagation();
    if (traceAppId === app.job_posting_id) {
      setTraceAppId(null);
      return;
    }
    setTraceAppId(app.job_posting_id);
    setTraceId(app.draft_trace_id);
    setTraceSpans(null);
    setTraceError(null);
    setTraceLoading(true);
    getApplicationTrace(app.job_posting_id)
      .then((result) => {
        setTraceSpans(result.spans);
        setTraceId(result.trace_id);
      })
      .catch((err) => {
        setTraceError(err instanceof ApiError ? err.message : (err as Error).message);
      })
      .finally(() => setTraceLoading(false));
  };

  const closeTrace = () => {
    setTraceAppId(null);
    setTraceSpans(null);
    setTraceError(null);
  };

  const saveDraft = async (app: Application) => {
    if (!draftFiles) return;
    setDraftSaving(true);
    setDraftError(null);
    try {
      await saveDraftFiles(app.job_posting_id, draftFiles.resume, draftFiles.cover_letter);
    } catch (err) {
      setDraftError(err instanceof ApiError ? err.message : (err as Error).message);
    } finally {
      setDraftSaving(false);
    }
  };

  const doMergeDraft = async (app: Application) => {
    setDraftMerging(true);
    setDraftError(null);
    try {
      const result = await mergeDraft(app.job_posting_id);
      setDraftFinalUrl(result.final_url);
      setApplications((prev) =>
        prev.map((a) => (a.job_posting_id === app.job_posting_id ? { ...a, status: "submitted" } : a)),
      );
    } catch (err) {
      const msg = err instanceof ApiError ? err.message : (err as Error).message;
      setDraftError(err instanceof ApiError && err.status === 409 ? `Already merged: ${msg}` : msg);
    } finally {
      setDraftMerging(false);
    }
  };

  if (loading) return <p className="py-6 text-center text-sm text-muted">Loading…</p>;
  if (error) return <p className="py-6 text-center text-sm text-danger">{error}</p>;

  if (applications.length === 0) {
    return (
      <p className="py-6 text-center text-sm text-muted">
        No applications yet. Promote a job posting to start tracking it here.
      </p>
    );
  }

  return (
    <div className="flex min-h-0 gap-4">
      <div className="min-w-0 flex-1 space-y-3">
      {actionError ? <p className="text-sm text-danger">{actionError}</p> : null}

      <div className="overflow-x-auto rounded-card border border-border-subtle bg-surface">
        <table className="w-full border-collapse text-left text-sm">
          <thead>
            <tr className="border-b border-border-subtle text-xs font-medium uppercase tracking-wide text-muted">
              <th className="pb-2 px-3 font-medium">Job</th>
              <th className="pb-2 px-3 font-medium">Status</th>
              <th className="pb-2 px-3 font-medium">Notes</th>
              <th className="pb-2 px-3 font-medium">Drafted</th>
              <th className="pb-2 px-3 font-medium">Actions</th>
            </tr>
          </thead>
          <tbody>
            {applications.map((app) => {
              const isSelected = selectedPostingId === app.job_posting_id;
              return (
                <>
                  <tr
                    key={app.id}
                    className={`border-b border-border-subtle cursor-pointer hover:bg-surface-raised ${isSelected ? "bg-surface-raised" : ""}`}
                    onClick={() => selectApp(app.job_posting_id)}
                  >
                    <td className="py-3 px-3">
                      <p className="font-medium text-ink">{app.title}</p>
                      <p className="text-xs text-muted">{app.employer_name}</p>
                    </td>
                    <td className={`py-3 px-3 ${STATUS_CLASS[app.status]}`}>
                      {STATUS_LABEL[app.status]}
                    </td>
                    <td className="py-3 px-3">
                      <div className="flex items-center gap-1">
                        <p className="flex-1 truncate text-xs text-ink" style={{ maxWidth: 160 }}>
                          {app.application_notes ?? <span className="text-muted">—</span>}
                        </p>
                        <button
                          type="button"
                          title="Edit guidance notes"
                          onClick={(e) => startEditNotes(app, e)}
                          className="shrink-0 rounded px-1 text-muted hover:text-ink"
                        >
                          ✏️
                        </button>
                      </div>
                    </td>
                    <td className="py-3 px-3 text-muted">
                      {app.resume_draft_mr_url ? (
                        <div>
                          <a
                            href={app.resume_draft_mr_url}
                            target="_blank"
                            rel="noreferrer"
                            className="text-accent underline"
                            onClick={(e) => e.stopPropagation()}
                          >
                            View MR
                          </a>
                          {app.draft_model_id ? (
                            <p className="mt-0.5 text-xs text-muted">Model: {app.draft_model_id}</p>
                          ) : null}
                        </div>
                      ) : app.draft_error ? (
                        <p className="text-xs text-danger">{app.draft_error}</p>
                      ) : (
                        formatDate(app.draft_generated_at)
                      )}
                    </td>
                    <td className="py-3 px-3">
                      <div className="flex flex-wrap gap-2" onClick={(e) => e.stopPropagation()}>
                        {app.status === "promoted" && !app.resume_draft_mr_url ? (
                          <button
                            type="button"
                            disabled={draftingId === app.job_posting_id}
                            onClick={() => generateDraft(app)}
                            className="rounded-card border border-border-subtle px-2 py-1 text-xs disabled:opacity-40"
                          >
                            {draftingId === app.job_posting_id ? "Generating…" : "Generate Drafts"}
                          </button>
                        ) : null}

                        {app.status === "promoted" ? (
                          <button
                            type="button"
                            onClick={() => advanceStatus(app, "drafting")}
                            className="rounded-card border border-ok px-2 py-1 text-xs text-ok"
                          >
                            → Drafting
                          </button>
                        ) : null}

                        {app.status === "drafting" && app.resume_draft_mr_url ? (
                          <button
                            type="button"
                            onClick={(e) => openDraftPanel(app, e)}
                            className="rounded-card border border-ok px-2 py-1 text-xs text-ok"
                          >
                            See Draft
                          </button>
                        ) : null}

                        {app.status === "drafting" ? (
                          <button
                            type="button"
                            disabled={draftingId === app.job_posting_id}
                            onClick={() => redraftApp(app)}
                            className="rounded-card border border-border-subtle px-2 py-1 text-xs disabled:opacity-40"
                          >
                            {draftingId === app.job_posting_id ? "Generating…" : "Re-draft"}
                          </button>
                        ) : null}

                        {app.draft_trace_id ? (
                          <button
                            type="button"
                            onClick={(e) => openTrace(app, e)}
                            className={`rounded-card border px-2 py-1 text-xs ${traceAppId === app.job_posting_id ? "border-accent text-accent" : "border-border-subtle text-muted"}`}
                          >
                            {traceLoading && traceAppId === app.job_posting_id ? "Loading…" : "View Trace"}
                          </button>
                        ) : null}

                        {app.status === "drafting" ? (
                          <button
                            type="button"
                            onClick={() => advanceStatus(app, "submitted")}
                            className="rounded-card border border-accent px-2 py-1 text-xs text-accent"
                          >
                            Mark Submitted
                          </button>
                        ) : null}

                        {app.status !== "withdrawn" ? (
                          <button
                            type="button"
                            onClick={() => withdraw(app)}
                            className="rounded-card border border-danger px-2 py-1 text-xs text-danger"
                          >
                            Withdraw
                          </button>
                        ) : null}
                      </div>
                    </td>
                  </tr>
                  {isSelected ? (
                    <tr key={`${app.id}-detail`} className="border-b border-border-subtle bg-surface-raised">
                      <td colSpan={5} className="px-3 pb-4 pt-2">
                        <div className="grid gap-4 md:grid-cols-2">
                          {/* T047: description read-only */}
                          <div>
                            <p className="mb-1 text-xs font-medium uppercase tracking-wide text-muted">
                              Job Description
                            </p>
                            {descLoading ? (
                              <p className="text-sm text-muted">Loading…</p>
                            ) : descText ? (
                              <div
                                className="prose prose-sm max-w-none overflow-y-auto rounded-card border border-border-subtle bg-surface p-3 text-ink"
                                style={{ maxHeight: 260 }}
                                dangerouslySetInnerHTML={{ __html: descText }}
                              />
                            ) : (
                              <p className="text-sm text-muted">Description unavailable.</p>
                            )}
                          </div>
                          {/* T058-T060: in-app draft viewer/editor */}
                          {draftPanelId === app.job_posting_id ? (
                            <div className="md:col-span-2">
                              <div className="mb-1 flex items-center gap-2">
                                <p className="text-xs font-medium uppercase tracking-wide text-muted">
                                  Draft Documents
                                </p>
                                <button
                                  type="button"
                                  onClick={closeDraftPanel}
                                  className="ml-auto text-xs text-muted hover:text-ink"
                                >
                                  ✕ Close
                                </button>
                              </div>
                              {draftLoading ? (
                                <p className="text-sm text-muted">Loading drafts…</p>
                              ) : draftError ? (
                                <p className="text-sm text-danger">{draftError}</p>
                              ) : draftFinalUrl ? (
                                <p className="text-sm text-ok">
                                  Submitted.{" "}
                                  <a href={draftFinalUrl} target="_blank" rel="noreferrer" className="underline">
                                    View final documents
                                  </a>
                                </p>
                              ) : draftFiles ? (
                                <div className="flex flex-col gap-3">
                                  <div>
                                    <p className="mb-1 text-xs text-muted">Resume</p>
                                    <textarea
                                      value={draftFiles.resume}
                                      onChange={(e) => setDraftFiles({ ...draftFiles, resume: e.target.value })}
                                      rows={10}
                                      className="w-full rounded-card border border-border-subtle bg-surface px-3 py-1.5 font-mono text-xs text-ink"
                                    />
                                  </div>
                                  <div>
                                    <p className="mb-1 text-xs text-muted">Cover Letter</p>
                                    <textarea
                                      value={draftFiles.cover_letter}
                                      onChange={(e) => setDraftFiles({ ...draftFiles, cover_letter: e.target.value })}
                                      rows={10}
                                      className="w-full rounded-card border border-border-subtle bg-surface px-3 py-1.5 font-mono text-xs text-ink"
                                    />
                                  </div>
                                  {draftError ? (
                                    <p className="text-xs text-danger">{draftError}</p>
                                  ) : null}
                                  <div className="flex gap-2">
                                    <button
                                      type="button"
                                      disabled={draftSaving}
                                      onClick={() => saveDraft(app)}
                                      className="rounded-card border border-border-subtle px-3 py-1 text-sm disabled:opacity-40"
                                    >
                                      {draftSaving ? "Saving…" : "Save"}
                                    </button>
                                    <button
                                      type="button"
                                      disabled={draftMerging}
                                      onClick={() => doMergeDraft(app)}
                                      className="rounded-card border border-accent px-3 py-1 text-sm text-accent disabled:opacity-40"
                                    >
                                      {draftMerging ? "Merging…" : "Merge & Submit"}
                                    </button>
                                  </div>
                                </div>
                              ) : null}
                            </div>
                          ) : null}

                          {/* T048/T049/T050: expand-to-edit notes */}
                          <div>
                            <p className="mb-1 text-xs font-medium uppercase tracking-wide text-muted">
                              Guidance Notes
                            </p>
                            {editingNotes ? (
                              <div className="flex flex-col gap-2">
                                {notesError ? (
                                  <p className="text-xs text-danger">{notesError}</p>
                                ) : null}
                                <textarea
                                  autoFocus
                                  value={notesDraft}
                                  onChange={(e) => setNotesDraft(e.target.value)}
                                  onKeyDown={(e) => {
                                    if (e.key === "Escape") setEditingNotes(false);
                                  }}
                                  rows={6}
                                  className="w-full rounded-card border border-border-subtle bg-surface px-3 py-1.5 text-sm text-ink"
                                />
                                <div className="flex gap-2">
                                  <button
                                    type="button"
                                    disabled={savingNotes}
                                    onClick={() => saveNotes(app)}
                                    className="rounded-card border border-border-subtle px-3 py-1 text-sm disabled:opacity-40"
                                  >
                                    Save
                                  </button>
                                  <button
                                    type="button"
                                    onClick={() => setEditingNotes(false)}
                                    className="rounded-card border border-border-subtle px-3 py-1 text-sm text-muted"
                                  >
                                    Cancel
                                  </button>
                                </div>
                              </div>
                            ) : (
                              <div className="flex items-start gap-2 rounded-card border border-border-subtle bg-surface p-3">
                                <p className="flex-1 text-sm text-ink">
                                  {app.application_notes ? (
                                    app.application_notes
                                  ) : (
                                    <span className="text-muted">No guidance notes yet.</span>
                                  )}
                                </p>
                                <button
                                  type="button"
                                  title="Edit guidance notes"
                                  onClick={(e) => startEditNotes(app, e)}
                                  className="shrink-0 rounded-card border border-border-subtle px-2 py-1 text-xs text-muted"
                                >
                                  ✏️
                                </button>
                              </div>
                            )}
                          </div>
                        </div>
                      </td>
                    </tr>
                  ) : null}
                </>
              );
            })}
          </tbody>
        </table>
      </div>
      </div>

      {traceAppId ? (
        <TraceDrawer
          traceId={traceId}
          spans={traceSpans}
          loading={traceLoading}
          error={traceError}
          onClose={closeTrace}
        />
      ) : null}
    </div>
  );
}
