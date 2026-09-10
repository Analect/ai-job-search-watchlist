import { useState } from "react";

import {
  ApiError,
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
  const watchlisted = companies.filter((c) => c.short_listed);
  const [similarFor, setSimilarFor] = useState<string | null>(null);
  const [similarResults, setSimilarResults] = useState<SimilarEmployer[]>([]);
  const [similarLoading, setSimilarLoading] = useState(false);
  const [message, setMessage] = useState<string | null>(null);

  const showSimilar = (slug: string) => {
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

  const removeCompany = (slug: string) => {
    removeFromWatchlist(slug)
      .then(() => {
        onCompaniesChange(companies.map((c) => (c.slug === slug ? { ...c, short_listed: false } : c)));
        if (similarFor === slug) setSimilarFor(null);
      })
      .catch((err) =>
        setMessage(err instanceof ApiError ? err.message : (err as Error).message),
      );
  };

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
            <>
              <tr key={c.slug} className="border-b border-border-subtle last:border-b-0">
                <td className="py-2 pr-4 font-medium text-ink">{c.name}</td>
                <td className="py-2 pr-4 text-muted">{c.industry ?? "—"}</td>
                <td className="py-2 pr-4 text-muted">{c.ats_types ?? "—"}</td>
                <td className="py-2">
                  <div className="flex gap-2">
                    <button
                      type="button"
                      onClick={() => showSimilar(c.slug)}
                      className="rounded-card border border-border-subtle px-2 py-1 text-xs text-muted"
                    >
                      Similar
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
              {similarFor === c.slug ? (
                <tr key={`${c.slug}-similar`} className="border-b border-border-subtle">
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
                            <span className="text-muted">{s.industry ?? "—"} · {s.distance.toFixed(2)}</span>
                          </li>
                        ))}
                      </ul>
                    )}
                  </td>
                </tr>
              ) : null}
            </>
          ))}
        </tbody>
      </table>
    </div>
  );
}
