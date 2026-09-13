import React, { useState } from "react";
import { useNavigate } from "react-router-dom";

import {
  ApiError,
  addToWatchlist,
  fetchEmployerPostings,
  fetchSimilarEmployers,
  removeFromWatchlist,
  type MapCompany,
  type SimilarEmployer,
} from "@/lib/api";

interface WatchlistTableProps {
  companies: MapCompany[];
  onCompaniesChange: (next: MapCompany[]) => void;
}

export default function WatchlistTable({ companies, onCompaniesChange }: WatchlistTableProps) {
  const navigate = useNavigate();
  const watchlisted = companies.filter((c) => c.short_listed);
  const [similarFor, setSimilarFor] = useState<string | null>(null);
  const [similarResults, setSimilarResults] = useState<SimilarEmployer[]>([]);
  const [similarLoading, setSimilarLoading] = useState(false);
  const [postingsFor, setPostingsFor] = useState<string | null>(null);
  const [postingsResults, setPostingsResults] = useState<{ id: string; title: string; posted_date: string | null }[]>([]);
  const [postingsLoading, setPostingsLoading] = useState(false);
  const [message, setMessage] = useState<string | null>(null);

  const showSimilar = (slug: string) => {
    if (similarFor === slug) {
      setSimilarFor(null);
      setSimilarResults([]);
      return;
    }
    setPostingsFor(null);
    setSimilarFor(slug);
    setSimilarLoading(true);
    setSimilarResults([]);
    fetchSimilarEmployers(slug)
      .then((res) => setSimilarResults(res.results))
      .catch((err) => {
        setMessage(err instanceof ApiError ? err.message : (err as Error).message);
      })
      .finally(() => setSimilarLoading(false));
  };

  const showPostings = (slug: string) => {
    if (postingsFor === slug) {
      setPostingsFor(null);
      setPostingsResults([]);
      return;
    }
    setSimilarFor(null);
    setPostingsFor(slug);
    setPostingsLoading(true);
    setPostingsResults([]);
    fetchEmployerPostings(slug)
      .then((res) => setPostingsResults(res.results))
      .catch((err) => {
        setMessage(err instanceof ApiError ? err.message : (err as Error).message);
      })
      .finally(() => setPostingsLoading(false));
  };

  const removeCompany = (slug: string) => {
    removeFromWatchlist(slug)
      .then(() => {
        onCompaniesChange(companies.map((c) => (c.slug === slug ? { ...c, short_listed: false } : c)));
        if (similarFor === slug) setSimilarFor(null);
        if (postingsFor === slug) setPostingsFor(null);
      })
      .catch((err) =>
        setMessage(err instanceof ApiError ? err.message : (err as Error).message),
      );
  };

  const addCompany = (slug: string) => {
    addToWatchlist(slug)
      .then(() => {
        onCompaniesChange(companies.map((c) => (c.slug === slug ? { ...c, short_listed: true } : c)));
      })
      .catch((err) =>
        setMessage(err instanceof ApiError ? err.message : (err as Error).message),
      );
  };

  const watchlistedSlugs = new Set(watchlisted.map((c) => c.slug));

  if (watchlisted.length === 0) {
    return (
      <p className="p-4 text-sm text-muted">
        No companies on your watchlist yet. Add them from the Map tab.
      </p>
    );
  }

  return (
    <div className="space-y-3 p-3">
      {message ? <p className="text-sm text-danger">{message}</p> : null}
      <p className="text-xs text-muted">{watchlisted.length} {watchlisted.length === 1 ? "company" : "companies"} on watchlist</p>
      <table className="w-full border-collapse text-left text-sm">
        <thead>
          <tr className="border-b border-border-subtle text-xs font-medium uppercase tracking-wide text-muted">
            <th className="pb-2 pr-4 font-medium">Company</th>
            <th className="pb-2 pr-4 font-medium">Industry</th>
            <th className="pb-2 pr-4 font-medium">ATS</th>
            <th className="pb-2 font-medium">Actions</th>
          </tr>
        </thead>
        <tbody>
          {watchlisted.map((c) => (
            <React.Fragment key={c.slug}>
              <tr className="border-b border-border-subtle last:border-b-0">
                <td className="py-2 pr-4 font-medium text-ink">{c.name}</td>
                <td className="py-2 pr-4 text-muted">{c.industry ?? "—"}</td>
                <td className="py-2 pr-4">
                  {c.ats_active ? (
                    <span className="text-xs text-ok">● Active</span>
                  ) : (
                    <span className="text-xs text-muted">○ {c.ats_types ?? "—"}</span>
                  )}
                  {c.boards && c.boards.length > 0 ? (
                    <div className="mt-0.5 flex flex-wrap gap-1">
                      {c.boards.slice(0, 3).map((b) => (
                        <a
                          key={b.url}
                          href={b.url}
                          target="_blank"
                          rel="noreferrer"
                          className="text-xs text-accent underline"
                        >
                          {b.type}
                        </a>
                      ))}
                    </div>
                  ) : null}
                </td>
                <td className="py-2">
                  <div className="flex flex-wrap gap-2">
                    <button
                      type="button"
                      onClick={() => showSimilar(c.slug)}
                      className="rounded-card border border-border-subtle px-2 py-1 text-xs text-muted"
                    >
                      {similarFor === c.slug ? "Hide" : "Similar"}
                    </button>
                    <button
                      type="button"
                      onClick={() => showPostings(c.slug)}
                      className="rounded-card border border-border-subtle px-2 py-1 text-xs text-muted"
                    >
                      {postingsFor === c.slug ? "Hide" : "Postings"}
                    </button>
                    <button
                      type="button"
                      onClick={() => removeCompany(c.slug)}
                      className="rounded-card border border-danger px-2 py-1 text-xs text-danger"
                    >
                      Remove
                    </button>
                  </div>
                </td>
              </tr>
              {postingsFor === c.slug ? (
                <tr className="border-b border-border-subtle">
                  <td colSpan={4} className="bg-surface/50 px-4 py-3">
                    {postingsLoading ? (
                      <p className="text-xs text-muted">Loading postings…</p>
                    ) : postingsResults.length === 0 ? (
                      <p className="text-xs text-muted">No unreviewed postings.</p>
                    ) : (
                      <ul className="space-y-1">
                        {postingsResults.map((p) => (
                          <li key={p.id} className="flex items-center justify-between text-xs">
                            <button
                              type="button"
                              onClick={() => navigate(`../postings?selected=${p.id}`)}
                              className="text-accent underline"
                            >
                              {p.title}
                            </button>
                            <span className="text-muted">
                              {p.posted_date ? new Date(p.posted_date).toLocaleDateString() : "—"}
                            </span>
                          </li>
                        ))}
                      </ul>
                    )}
                  </td>
                </tr>
              ) : null}
              {similarFor === c.slug ? (
                <tr className="border-b border-border-subtle">
                  <td colSpan={4} className="bg-surface/50 px-4 py-3">
                    {similarLoading ? (
                      <p className="text-xs text-muted">Finding similar companies…</p>
                    ) : similarResults.length === 0 ? (
                      <p className="text-xs text-muted">No similar companies found.</p>
                    ) : (
                      <ul className="space-y-1">
                        {similarResults.map((s) => (
                          <li key={s.slug} className="flex items-center justify-between text-xs">
                            <span className="text-ink">{s.name}</span>
                            <div className="flex items-center gap-2">
                              <span className="text-muted">{s.industry ?? "—"} · {s.distance.toFixed(2)}</span>
                              {watchlistedSlugs.has(s.slug) ? (
                                <span className="text-xs text-ok">Watchlisted</span>
                              ) : (
                                <button
                                  type="button"
                                  onClick={() => addCompany(s.slug)}
                                  className="rounded-card border border-ok px-1.5 py-0.5 text-xs text-ok"
                                >
                                  Add
                                </button>
                              )}
                            </div>
                          </li>
                        ))}
                      </ul>
                    )}
                  </td>
                </tr>
              ) : null}
            </React.Fragment>
          ))}
        </tbody>
      </table>
    </div>
  );
}
