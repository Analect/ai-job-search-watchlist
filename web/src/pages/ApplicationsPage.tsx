import { useEffect, useState } from "react";

import {
  ApiError,
  advanceApplicationStatus,
  fetchApplications,
  generateDrafts,
  postPostingEvent,
  type Application,
  type DraftResult,
} from "@/lib/api";

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

  useEffect(() => {
    fetchApplications()
      .then((res) => setApplications(res.results))
      .catch((err) => setError(err instanceof ApiError ? err.message : (err as Error).message))
      .finally(() => setLoading(false));
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

  const generateDraft = (app: Application) => {
    setDraftingId(app.job_posting_id);
    setActionError(null);
    generateDrafts(app.job_posting_id)
      .then((draft: DraftResult) => {
        setApplications((prev) =>
          prev.map((a) =>
            a.id === app.id
              ? {
                  ...a,
                  status: "drafting",
                  resume_draft_mr_url: draft.resume_draft_mr_url,
                  draft_generated_at: draft.draft_generated_at,
                }
              : a,
          ),
        );
      })
      .catch((err) =>
        setActionError(err instanceof ApiError ? err.message : (err as Error).message),
      )
      .finally(() => setDraftingId(null));
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
    <div className="space-y-3">
      {actionError ? <p className="text-sm text-danger">{actionError}</p> : null}

      <div className="overflow-x-auto rounded-card border border-border-subtle bg-surface">
        <table className="w-full border-collapse text-left text-sm">
          <thead>
            <tr className="border-b border-border-subtle text-xs font-medium uppercase tracking-wide text-muted">
              <th className="pb-2 px-3 font-medium">Job</th>
              <th className="pb-2 px-3 font-medium">Status</th>
              <th className="pb-2 px-3 font-medium">Drafted</th>
              <th className="pb-2 px-3 font-medium">Actions</th>
            </tr>
          </thead>
          <tbody>
            {applications.map((app) => (
              <tr key={app.id} className="border-b border-border-subtle last:border-b-0">
                <td className="py-3 px-3">
                  <p className="font-medium text-ink">{app.title}</p>
                  <p className="text-xs text-muted">{app.employer_name}</p>
                </td>
                <td className={`py-3 px-3 ${STATUS_CLASS[app.status]}`}>
                  {STATUS_LABEL[app.status]}
                </td>
                <td className="py-3 px-3 text-muted">
                  {app.resume_draft_mr_url ? (
                    <a
                      href={app.resume_draft_mr_url}
                      target="_blank"
                      rel="noreferrer"
                      className="text-accent underline"
                    >
                      View MR
                    </a>
                  ) : (
                    formatDate(app.draft_generated_at)
                  )}
                </td>
                <td className="py-3 px-3">
                  <div className="flex flex-wrap gap-2">
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
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
