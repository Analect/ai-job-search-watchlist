import { useEffect, useState } from "react";

import { ApiError, fetchPromotedJobs, type PostingSummary } from "@/lib/api";

function formatDate(iso: string | null): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleDateString(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
  });
}

export default function PromotedList() {
  const [results, setResults] = useState<PostingSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetchPromotedJobs()
      .then((res) => setResults(res.results))
      .catch((err) => setError(err instanceof ApiError ? err.message : (err as Error).message))
      .finally(() => setLoading(false));
  }, []);

  if (loading) return <p className="p-4 text-sm text-muted">Loading…</p>;
  if (error) return <p className="p-4 text-sm text-danger">{error}</p>;
  if (results.length === 0) {
    return (
      <p className="p-4 text-sm text-muted">
        No promoted jobs yet. Use the Promote action on a posting to add one here.
      </p>
    );
  }

  return (
    <div className="p-3">
      <table className="w-full border-collapse text-left text-sm">
        <thead>
          <tr className="border-b border-border-subtle text-xs font-medium uppercase tracking-wide text-muted">
            <th className="pb-2 pr-4 font-medium">Posting</th>
            <th className="pb-2 pr-4 font-medium">Location</th>
            <th className="pb-2 pr-4 font-medium">Posted</th>
            <th className="pb-2 font-medium">Status</th>
          </tr>
        </thead>
        <tbody>
          {results.map((p) => (
            <tr key={p.id} className="border-b border-border-subtle last:border-b-0">
              <td className="py-2 pr-4">
                <a
                  href={p.source_url}
                  target="_blank"
                  rel="noreferrer"
                  className="font-medium text-ink hover:text-accent hover:underline"
                >
                  {p.title}
                </a>
                <p className="text-xs text-muted">{p.employer_name}</p>
              </td>
              <td className="py-2 pr-4 text-muted">
                {p.location_city ?? (p.location_unknown ? "Unknown" : p.location_country ?? "—")}
              </td>
              <td className="py-2 pr-4 text-muted">{formatDate(p.posted_date)}</td>
              <td className="py-2 capitalize text-muted">{p.status}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
