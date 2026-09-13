import { useState } from "react";

import { ApiError, addToWatchlist, removeFromWatchlist, type MapCompany } from "@/lib/api";

interface CompanyDetailPaneProps {
  company: MapCompany;
  onCompaniesChange: (updater: (c: MapCompany) => MapCompany) => void;
}

function platformFromUrl(url: string): string {
  try {
    const host = new URL(url).hostname.replace(/^www\./, "");
    if (host.includes("linkedin")) return "LinkedIn";
    if (host.includes("github")) return "GitHub";
    if (host.includes("twitter") || host.includes("x.com")) return "Twitter/X";
    if (host.includes("crunchbase")) return "Crunchbase";
    if (host.includes("bloomberg")) return "Bloomberg";
    if (host.includes("facebook")) return "Facebook";
    return host;
  } catch {
    return url;
  }
}

export default function CompanyDetailPane({ company, onCompaniesChange }: CompanyDetailPaneProps) {
  const [expanded, setExpanded] = useState(false);
  const [acting, setActing] = useState(false);
  const [actionMsg, setActionMsg] = useState<string | null>(null);

  const toggleWatchlist = async () => {
    setActing(true);
    setActionMsg(null);
    try {
      if (company.short_listed) {
        await removeFromWatchlist(company.slug);
        onCompaniesChange((c) => ({ ...c, short_listed: false }));
        setActionMsg(`${company.name} removed from watchlist.`);
      } else {
        const res = await addToWatchlist(company.slug);
        onCompaniesChange((c) => ({ ...c, short_listed: true }));
        if (!res.collection_supported) {
          setActionMsg(`${company.name} added — no automated pipeline for this ATS yet.`);
        }
      }
    } catch (err) {
      setActionMsg(
        `Action failed: ${err instanceof ApiError ? err.message : (err as Error).message}`,
      );
    } finally {
      setActing(false);
    }
  };

  const DESCRIPTION_PREVIEW = 200;
  const desc = company.description ?? null;
  const descShort = desc && desc.length > DESCRIPTION_PREVIEW ? desc.slice(0, DESCRIPTION_PREVIEW) + "…" : desc;

  return (
    <div className="space-y-3 p-4">
      <div className="flex items-start justify-between gap-2">
        <div>
          <p className="font-semibold text-ink">{company.name}</p>
          <p className="text-sm text-muted">{company.industry ?? "—"}</p>
          {company.ats_types ? (
            <p className="text-xs text-muted">ATS: {company.ats_types}</p>
          ) : null}
        </div>
        <button
          type="button"
          disabled={acting}
          onClick={toggleWatchlist}
          className={`rounded-card border px-3 py-1 text-sm font-medium disabled:opacity-40 ${
            company.short_listed ? "border-danger text-danger" : "border-ok text-ok"
          }`}
        >
          {company.short_listed ? "Remove from watchlist" : "Add to watchlist"}
        </button>
      </div>

      {actionMsg ? <p className="text-sm text-ink">{actionMsg}</p> : null}

      {desc ? (
        <div>
          <p className="text-sm text-ink">
            {expanded ? desc : descShort}
          </p>
          {desc.length > DESCRIPTION_PREVIEW ? (
            <button
              type="button"
              onClick={() => setExpanded((e) => !e)}
              className="mt-1 text-xs text-accent underline"
            >
              {expanded ? "Show less" : "Read more"}
            </button>
          ) : null}
        </div>
      ) : null}

      {company.website ? (
        <a
          href={company.website}
          target="_blank"
          rel="noreferrer"
          className="block text-xs text-accent underline"
        >
          {company.website.replace(/^https?:\/\//, "").replace(/\/$/, "")}
        </a>
      ) : null}

      {company.same_as && company.same_as.length > 0 ? (
        <div className="flex flex-wrap gap-2">
          {company.same_as.map((url) => (
            <a
              key={url}
              href={url}
              target="_blank"
              rel="noreferrer"
              className="text-xs text-accent underline"
            >
              {platformFromUrl(url)}
            </a>
          ))}
        </div>
      ) : null}

      {company.wikidata_id ? (
        <a
          href={`https://www.wikidata.org/wiki/${company.wikidata_id}`}
          target="_blank"
          rel="noreferrer"
          className="block text-xs text-accent underline"
        >
          Wikidata
        </a>
      ) : null}
    </div>
  );
}
