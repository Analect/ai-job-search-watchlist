import { useEffect, useState } from "react";

import {
  ApiError,
  addToWatchlist,
  fetchDendrogram,
  removeFromWatchlist,
  type MapCompany,
} from "@/lib/api";

interface UniverseTableProps {
  companies: MapCompany[];
  onCompaniesChange: (next: MapCompany[]) => void;
}

export default function UniverseTable({ companies, onCompaniesChange }: UniverseTableProps) {
  const [search, setSearch] = useState("");
  const [dendrogram, setDendrogram] = useState<{ slugs: string[]; tree: unknown } | null>(null);
  const [dendrogramError, setDendrogramError] = useState<string | null>(null);
  const [view, setView] = useState<"table" | "tree">("table");
  const [message, setMessage] = useState<string | null>(null);

  useEffect(() => {
    fetchDendrogram()
      .then(setDendrogram)
      .catch((err) =>
        setDendrogramError(err instanceof ApiError ? err.message : (err as Error).message),
      );
  }, []);

  const filtered = companies.filter(
    (c) =>
      !search ||
      c.name.toLowerCase().includes(search.toLowerCase()) ||
      (c.industry ?? "").toLowerCase().includes(search.toLowerCase()),
  );

  const toggleWatchlist = (company: MapCompany) => {
    const fn = company.short_listed ? removeFromWatchlist : addToWatchlist;
    fn(company.slug)
      .then(() => {
        onCompaniesChange(
          companies.map((c) =>
            c.slug === company.slug ? { ...c, short_listed: !company.short_listed } : c,
          ),
        );
      })
      .catch((err) =>
        setMessage(err instanceof ApiError ? err.message : (err as Error).message),
      );
  };

  return (
    <div className="space-y-3 p-3">
      <div className="flex items-center gap-3">
        <input
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="Search companies…"
          className="flex-1 rounded-card border border-border-subtle bg-surface px-3 py-1.5 text-sm text-ink placeholder:text-muted"
        />
        <div className="flex gap-1">
          <button
            type="button"
            onClick={() => setView("table")}
            className={`rounded-card border px-3 py-1 text-xs ${view === "table" ? "border-accent text-accent" : "border-border-subtle text-muted"}`}
          >
            Table
          </button>
          <button
            type="button"
            onClick={() => setView("tree")}
            className={`rounded-card border px-3 py-1 text-xs ${view === "tree" ? "border-accent text-accent" : "border-border-subtle text-muted"}`}
          >
            Tree
          </button>
        </div>
      </div>

      {message ? <p className="text-sm text-danger">{message}</p> : null}

      {view === "table" ? (
        <div className="overflow-x-auto">
          <table className="w-full border-collapse text-left text-sm">
            <thead>
              <tr className="border-b border-border-subtle text-xs font-medium uppercase tracking-wide text-muted">
                <th className="pb-2 pr-4 font-medium">Company</th>
                <th className="pb-2 pr-4 font-medium">Industry</th>
                <th className="pb-2 pr-4 font-medium">ATS</th>
                <th className="pb-2 font-medium">Watchlist</th>
              </tr>
            </thead>
            <tbody>
              {filtered.slice(0, 200).map((c) => (
                <tr key={c.slug} className="border-b border-border-subtle last:border-b-0">
                  <td className="py-2 pr-4 text-ink">{c.name}</td>
                  <td className="py-2 pr-4 text-muted">{c.industry ?? "—"}</td>
                  <td className="py-2 pr-4 text-muted">{c.ats_types ?? "—"}</td>
                  <td className="py-2">
                    <button
                      type="button"
                      onClick={() => toggleWatchlist(c)}
                      className={`rounded-card border px-2 py-1 text-xs ${
                        c.short_listed
                          ? "border-danger text-danger"
                          : "border-ok text-ok"
                      }`}
                    >
                      {c.short_listed ? "Remove" : "Add"}
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {filtered.length > 200 ? (
            <p className="mt-2 text-xs text-muted">
              Showing 200 of {filtered.length} — search to narrow.
            </p>
          ) : null}
        </div>
      ) : (
        <div className="rounded-card border border-border-subtle bg-surface p-3">
          {dendrogramError ? (
            <p className="text-sm text-danger">{dendrogramError}</p>
          ) : dendrogram === null ? (
            <p className="text-sm text-muted">Loading dendrogram…</p>
          ) : (
            <p className="text-sm text-muted">
              Hierarchical clustering over {dendrogram.slugs.length} companies computed.
              Visual dendrogram rendering is a planned enhancement — raw tree data
              available at <code>/map/dendrogram</code>.
            </p>
          )}
        </div>
      )}
    </div>
  );
}
