export interface JobMetadata {
  key_terms: string[];
  responsibilities: string[];
  requirements: string[];
}

export function MetadataDrawer({
  title,
  metadata,
  loading,
  error,
  onClose,
}: {
  title: string | null;
  metadata: JobMetadata | null;
  loading: boolean;
  error: string | null;
  onClose: () => void;
}) {
  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4"
      onClick={onClose}
    >
      <div
        className="flex h-[80vh] w-full max-w-2xl flex-col rounded-card border border-border-subtle bg-surface shadow-xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between border-b border-border-subtle px-4 py-3">
          <div className="min-w-0">
            <span className="text-xs font-medium uppercase tracking-wide text-muted">Job Intelligence</span>
            {title ? (
              <p className="mt-0.5 truncate text-sm font-medium text-ink">{title}</p>
            ) : null}
          </div>
          <button
            type="button"
            onClick={onClose}
            className="ml-4 flex-shrink-0 rounded p-1 text-muted hover:bg-brand-soft"
            aria-label="Close metadata panel"
          >
            <svg
              viewBox="0 0 24 24"
              className="h-4 w-4"
              fill="none"
              stroke="currentColor"
              strokeWidth={2}
              aria-hidden="true"
            >
              <path d="M6 6l12 12M6 18L18 6" strokeLinecap="round" />
            </svg>
          </button>
        </div>

        <div className="flex-1 overflow-y-auto p-4 space-y-5">
          {loading ? (
            <p className="text-sm text-muted">Loading…</p>
          ) : error ? (
            <p className="text-sm text-danger">{error}</p>
          ) : !metadata ? (
            <p className="text-sm text-muted">
              Enrichment not yet available. It runs automatically in the background after
              promotion — try again in a few seconds.
            </p>
          ) : (
            <>
              {metadata.key_terms.length > 0 ? (
                <section>
                  <h3 className="mb-2 text-xs font-medium uppercase tracking-wide text-muted">
                    Key Terms
                  </h3>
                  <div className="flex flex-wrap gap-1.5">
                    {metadata.key_terms.map((term) => (
                      <span
                        key={term}
                        className="rounded-full border border-border-subtle bg-surface-raised px-2 py-0.5 text-xs text-ink"
                      >
                        {term}
                      </span>
                    ))}
                  </div>
                </section>
              ) : null}

              {metadata.responsibilities.length > 0 ? (
                <section>
                  <h3 className="mb-2 text-xs font-medium uppercase tracking-wide text-muted">
                    Key Responsibilities
                  </h3>
                  <ul className="space-y-1.5">
                    {metadata.responsibilities.map((r, i) => (
                      <li key={i} className="flex gap-2 text-sm text-ink">
                        <span className="mt-0.5 flex-shrink-0 text-muted">•</span>
                        <span>{r}</span>
                      </li>
                    ))}
                  </ul>
                </section>
              ) : null}

              {metadata.requirements.length > 0 ? (
                <section>
                  <h3 className="mb-2 text-xs font-medium uppercase tracking-wide text-muted">
                    Key Requirements
                  </h3>
                  <ul className="space-y-1.5">
                    {metadata.requirements.map((r, i) => (
                      <li key={i} className="flex gap-2 text-sm text-ink">
                        <span className="mt-0.5 flex-shrink-0 text-muted">•</span>
                        <span>{r}</span>
                      </li>
                    ))}
                  </ul>
                </section>
              ) : null}

              {metadata.key_terms.length === 0 &&
               metadata.responsibilities.length === 0 &&
               metadata.requirements.length === 0 ? (
                <p className="text-sm text-muted">No enrichment data available.</p>
              ) : null}
            </>
          )}
        </div>
      </div>
    </div>
  );
}
