import { useEffect, useMemo, useRef, useState } from "react";

import { ApiError, addToWatchlist, fetchMapCoordinates, type MapCompany } from "@/lib/api";

const WIDTH = 900;
const HEIGHT = 600;
const PADDING = 40;

// Plain SVG rather than a charting library — 2,747 points is well
// within what a hand-rolled scatter + wheel-zoom/drag-pan handles fine,
// and avoids pulling in a full charting dependency for this project's
// one map view.
export default function MapPage() {
  const [companies, setCompanies] = useState<MapCompany[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [hovered, setHovered] = useState<MapCompany | null>(null);
  const [addingSlug, setAddingSlug] = useState<string | null>(null);
  const [addMessage, setAddMessage] = useState<string | null>(null);

  const [zoom, setZoom] = useState(1);
  const [pan, setPan] = useState({ x: 0, y: 0 });
  const dragState = useRef<{ startX: number; startY: number; panX: number; panY: number } | null>(
    null,
  );

  useEffect(() => {
    fetchMapCoordinates()
      .then((res) => {
        setCompanies(res.companies);
        setError(null);
      })
      .catch((err) => {
        setError(err instanceof ApiError ? err.message : (err as Error).message);
      })
      .finally(() => setLoading(false));
  }, []);

  const scale = useMemo(() => {
    if (companies.length === 0) return null;
    const xs = companies.map((c) => c.x);
    const ys = companies.map((c) => c.y);
    const xMin = Math.min(...xs);
    const xMax = Math.max(...xs);
    const yMin = Math.min(...ys);
    const yMax = Math.max(...ys);
    const sx = (WIDTH - 2 * PADDING) / (xMax - xMin || 1);
    const sy = (HEIGHT - 2 * PADDING) / (yMax - yMin || 1);
    return (x: number, y: number) => ({
      cx: PADDING + (x - xMin) * sx,
      cy: HEIGHT - PADDING - (y - yMin) * sy, // flip y — screen space grows downward
    });
  }, [companies]);

  const handleWheel = (e: React.WheelEvent) => {
    e.preventDefault();
    const next = zoom * (e.deltaY < 0 ? 1.1 : 0.9);
    setZoom(Math.min(20, Math.max(1, next)));
  };

  const handlePointerDown = (e: React.PointerEvent) => {
    dragState.current = { startX: e.clientX, startY: e.clientY, panX: pan.x, panY: pan.y };
    (e.target as Element).setPointerCapture(e.pointerId);
  };

  const handlePointerMove = (e: React.PointerEvent) => {
    if (!dragState.current) return;
    const dx = e.clientX - dragState.current.startX;
    const dy = e.clientY - dragState.current.startY;
    setPan({ x: dragState.current.panX + dx, y: dragState.current.panY + dy });
  };

  const handlePointerUp = () => {
    dragState.current = null;
  };

  const handleClick = (company: MapCompany) => {
    if (company.short_listed || addingSlug) return;
    setAddingSlug(company.slug);
    setAddMessage(null);
    addToWatchlist(company.slug)
      .then((res) => {
        setCompanies((prev) =>
          prev.map((c) => (c.slug === company.slug ? { ...c, short_listed: true } : c)),
        );
        if (!res.collection_supported) {
          setAddMessage(
            `${company.name} added — its careers page isn't yet actively collected (no automated pipeline for this ATS yet), but it stays on your watchlist.`,
          );
        }
      })
      .catch((err) => {
        setAddMessage(
          `Couldn't add ${company.name}: ${err instanceof ApiError ? err.message : (err as Error).message}`,
        );
      })
      .finally(() => setAddingSlug(null));
  };

  if (loading) return <p className="py-6 text-center text-sm text-muted">Loading map…</p>;
  if (error) return <p className="py-6 text-center text-sm text-danger">{error}</p>;

  return (
    <div className="space-y-3">
      <p className="text-sm text-muted">
        {companies.length} companies · gold ring = on your watchlist · scroll to zoom, drag to pan
        · click an unmarked company to add it
      </p>
      {addMessage ? (
        <p className="rounded-card border border-border-subtle bg-surface p-3 text-sm text-ink">
          {addMessage}
        </p>
      ) : null}
      <div className="relative overflow-hidden rounded-card border border-border-subtle bg-surface">
        <svg
          viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
          className="h-[600px] w-full cursor-grab active:cursor-grabbing"
          onWheel={handleWheel}
          onPointerDown={handlePointerDown}
          onPointerMove={handlePointerMove}
          onPointerUp={handlePointerUp}
          onPointerLeave={handlePointerUp}
        >
          <g transform={`translate(${pan.x} ${pan.y}) scale(${zoom})`}>
            {scale
              ? companies.map((c) => {
                  const { cx, cy } = scale(c.x, c.y);
                  return (
                    <circle
                      key={c.slug}
                      cx={cx}
                      cy={cy}
                      r={c.short_listed ? 5 / Math.sqrt(zoom) : 3 / Math.sqrt(zoom)}
                      fill={c.short_listed ? "var(--accent)" : "var(--muted)"}
                      stroke={c.short_listed ? "gold" : "none"}
                      strokeWidth={c.short_listed ? 2 / Math.sqrt(zoom) : 0}
                      opacity={hovered && hovered.slug !== c.slug ? 0.35 : 0.85}
                      onMouseEnter={() => setHovered(c)}
                      onMouseLeave={() => setHovered((h) => (h?.slug === c.slug ? null : h))}
                      onClick={() => handleClick(c)}
                      style={{ cursor: c.short_listed ? "default" : "pointer" }}
                    />
                  );
                })
              : null}
          </g>
        </svg>
        {hovered ? (
          <div className="pointer-events-none absolute left-3 top-3 rounded-card border border-border-subtle bg-surface px-3 py-2 text-xs shadow">
            <p className="font-medium text-ink">{hovered.name}</p>
            <p className="text-muted">{hovered.industry ?? "—"}</p>
            {hovered.short_listed ? (
              <p className="text-ok">On watchlist</p>
            ) : (
              <p className="text-muted">Click to add</p>
            )}
          </div>
        ) : null}
      </div>
    </div>
  );
}
