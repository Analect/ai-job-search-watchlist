import type { TraceSpan } from "@/lib/api";

function formatNanoseconds(ns: string | number | undefined): string | null {
  if (ns == null) return null;
  const ms = Number(ns) / 1_000_000;
  if (Number.isNaN(ms) || ms < 0) return null;
  return ms < 1000 ? `${Math.round(ms)}ms` : `${(ms / 1000).toFixed(1)}s`;
}

const EVENT_LABELS: Record<string, string> = {
  "gen_ai.user.message": "Prompt",
  "gen_ai.assistant.message": "Response",
};

function SpanEventBlock({ name, content }: { name: string; content: string }) {
  const label = EVENT_LABELS[name] ?? name;
  return (
    <details className="mt-2">
      <summary className="cursor-pointer select-none text-xs font-medium text-muted hover:text-ink">
        {label} ({content.length.toLocaleString()} chars)
      </summary>
      <pre className="mt-1 max-h-64 overflow-y-auto whitespace-pre-wrap break-words rounded border border-border-subtle bg-bubble p-2 text-[10px] text-ink">
        {content}
      </pre>
    </details>
  );
}

function SpanDetails({ span }: { span: TraceSpan }) {
  const attrs = span.attributes ?? {};
  const rows: Array<[string, string]> = [];

  const system = attrs["gen_ai.system"];
  if (system) rows.push(["System", String(system)]);

  const model = attrs["gen_ai.request.model"];
  if (model) rows.push(["Model", String(model)]);

  // Bedrock SDK OTel uses input_tokens/output_tokens (not prompt/completion)
  const inputTokens = attrs["gen_ai.usage.input_tokens"] ?? attrs["gen_ai.usage.prompt_tokens"];
  const outputTokens = attrs["gen_ai.usage.output_tokens"] ?? attrs["gen_ai.usage.completion_tokens"];
  if (inputTokens != null || outputTokens != null) {
    rows.push(["Tokens", `${inputTokens ?? "?"} in / ${outputTokens ?? "?"} out`]);
  }

  const duration = formatNanoseconds(span.durationNano);

  const events: Array<{ name: string; content: string }> = [];
  const rawEvents = (span as Record<string, unknown>)["events"];
  if (Array.isArray(rawEvents)) {
    for (const ev of rawEvents) {
      const evName = typeof ev?.name === "string" ? ev.name : "";
      const content = ev?.attributes?.content;
      if (evName && typeof content === "string" && content.length > 0) {
        events.push({ name: evName, content });
      }
    }
  }

  return (
    <div className="space-y-2">
      <div className="flex items-start justify-between gap-2">
        <span className="text-sm font-medium text-ink">{span.name ?? "(unnamed span)"}</span>
        {duration ? <span className="flex-shrink-0 text-xs text-muted">{duration}</span> : null}
      </div>
      {rows.length > 0 ? (
        <dl className="space-y-1 text-xs">
          {rows.map(([label, value]) => (
            <div key={label} className="flex gap-2">
              <dt className="w-20 flex-shrink-0 font-medium text-muted">{label}:</dt>
              <dd className="min-w-0 break-words text-ink">{value}</dd>
            </div>
          ))}
        </dl>
      ) : null}
      {events.map((ev) => (
        <SpanEventBlock key={ev.name} name={ev.name} content={ev.content} />
      ))}
    </div>
  );
}

function SpanNode({
  span,
  depth,
  childrenOf,
}: {
  span: TraceSpan;
  depth: number;
  childrenOf: Map<string, TraceSpan[]>;
}) {
  const children = span.spanId ? (childrenOf.get(span.spanId) ?? []) : [];
  return (
    <li style={{ marginLeft: depth * 16 }}>
      <div className="rounded-card border border-border-subtle bg-bubble px-3 py-2">
        <SpanDetails span={span} />
      </div>
      {children.length > 0 ? (
        <ul className="mt-2 space-y-2">
          {children.map((child) => (
            <SpanNode
              key={child.spanId ?? child.name}
              span={child}
              depth={depth + 1}
              childrenOf={childrenOf}
            />
          ))}
        </ul>
      ) : null}
    </li>
  );
}

export function TraceDrawer({
  traceId,
  spans,
  loading,
  error,
  onClose,
}: {
  traceId: string | null;
  spans: TraceSpan[] | null;
  loading: boolean;
  error: string | null;
  onClose: () => void;
}) {
  const roots: TraceSpan[] = [];
  const childrenOf = new Map<string, TraceSpan[]>();
  if (spans) {
    const knownIds = new Set(spans.map((s) => s.spanId).filter(Boolean));
    for (const span of spans) {
      const parentId = span.parentSpanId as string | undefined;
      if (parentId && knownIds.has(parentId)) {
        const list = childrenOf.get(parentId) ?? [];
        list.push(span);
        childrenOf.set(parentId, list);
      } else {
        roots.push(span);
      }
    }
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4"
      onClick={onClose}
    >
      <div
        className="flex h-[80vh] w-full max-w-3xl flex-col rounded-card border border-border-subtle bg-surface shadow-xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between border-b border-border-subtle px-4 py-3">
          <div className="min-w-0">
            <span className="text-xs font-medium uppercase tracking-wide text-muted">LLM Trace</span>
            {traceId ? (
              <p className="mt-0.5 break-all font-mono text-[10px] text-muted">{traceId}</p>
            ) : null}
          </div>
          <button
            type="button"
            onClick={onClose}
            className="ml-4 flex-shrink-0 rounded p-1 text-muted hover:bg-brand-soft"
            aria-label="Close trace panel"
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
        <div className="flex-1 overflow-y-auto p-4">
          {loading ? (
            <p className="text-sm text-muted">Loading trace…</p>
          ) : error ? (
            <p className="text-sm text-danger">{error}</p>
          ) : roots.length === 0 ? (
            <p className="text-sm text-muted">No spans found.</p>
          ) : (
            <ul className="space-y-2">
              {roots.map((span) => (
                <SpanNode
                  key={span.spanId ?? span.name}
                  span={span}
                  depth={0}
                  childrenOf={childrenOf}
                />
              ))}
            </ul>
          )}
        </div>
      </div>
    </div>
  );
}
