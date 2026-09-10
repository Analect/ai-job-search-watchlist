import { useMemo, useRef, useState } from "react";

import SplitPane from "@/components/SplitPane";
import {
  ApiError,
  addToWatchlist,
  removeFromWatchlist,
  type MapCompany,
} from "@/lib/api";

const WIDTH = 900;
const HEIGHT = 500;
const PADDING = 40;

interface EmployerMapProps {
  companies: MapCompany[];
  onCompaniesChange: (next: MapCompany[]) => void;
}

export default function EmployerMap({ companies, onCompaniesChange }: EmployerMapProps) {
  const [hovered, setHovered] = useState<MapCompany | null>(null);
  const [selected, setSelected] = useState<MapCompany | null>(null);
  const [actionMsg, setActionMsg] = useState<string | null>(null);
  const [acting, setActing] = useState(false);

  const [zoom, setZoom] = useState(1);
  const [pan, setPan] = useState({ x: 0, y: 0 });
  const dragState = useRef<{ startX: number; startY: number; panX: number; panY: number } | null>(null);

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
      cy: HEIGHT - PADDING - (y - yMin) * sy,
    });
  }, [companies]);

  const handleWheel = (e: React.WheelEvent) => {
    e.preventDefault();
    setZoom((z) => Math.min(20, Math.max(1, z * (e.deltaY < 0 ? 1.1 : 0.9))));
  };

  const handlePointerDown = (e: React.PointerEvent) => {
    dragState.current = { startX: e.clientX, startY: e.clientY, panX: pan.x, panY: pan.y };
    (e.target as Element).setPointerCapture(e.pointerId);
  };

  const handlePointerMove = (e: React.PointerEvent) => {
    if (!dragState.current) return;
    setPan({
      x: dragState.current.panX + (e.clientX - dragState.current.startX),
      y: dragState.current.panY + (e.clientY - dragState.current.startY),
    });
  };

  const handlePointerUp = () => {
    dragState.current = null;
  };

  const toggleWatchlist = async (company: MapCompany) => {
    setActing(true);
    setActionMsg(null);
    try {
      if (company.short_listed) {
        await removeFromWatchlist(company.slug);
        onCompaniesChange(companies.map((c) => (c.slug === company.slug ? { ...c, short_listed: false } : c)));
        setSelected((s) => s?.slug === company.slug ? { ...s, short_listed: false } : s);
        setActionMsg(`${company.name} removed from watchlist.`);
      } else {
        const res = await addToWatchlist(company.slug);
        onCompaniesChange(companies.map((c) => (c.slug === company.slug ? { ...c, short_listed: true } : c)));
        setSelected((s) => s?.slug === company.slug ? { ...s, short_listed: true } : s);
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

  const detailPane = selected ? (
    <div className="space-y-3 p-4">
      <div className="flex items-start justify-between gap-2">
        <div>
          <p className="font-semibold text-ink">{selected.name}</p>
          <p className="text-sm text-muted">{selected.industry ?? "—"}</p>
          {selected.ats_types ? (
            <p className="text-xs text-muted">ATS: {selected.ats_types}</p>
          ) : null}
        </div>
        <button
          type="button"
          disabled={acting}
          onClick={() => toggleWatchlist(selected)}
          className={`rounded-card border px-3 py-1 text-sm font-medium disabled:opacity-40 ${
            selected.short_listed
              ? "border-danger text-danger"
              : "border-ok text-ok"
          }`}
        >
          {selected.short_listed ? "Remove from watchlist" : "Add to watchlist"}
        </button>
      </div>
      {actionMsg ? <p className="text-sm text-ink">{actionMsg}</p> : null}
    </div>
  ) : (
    <p className="p-4 text-sm text-muted">Click a company dot to see its details.</p>
  );

  return (
    <SplitPane
      top={
        <div className="space-y-2 p-2">
          <p className="text-xs text-muted">
            {companies.length} companies · gold = on watchlist · scroll to zoom, drag to pan
          </p>
          <div className="relative overflow-hidden rounded-card border border-border-subtle bg-surface">
            <svg
              viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
              className="h-[500px] w-full cursor-grab active:cursor-grabbing"
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
                      const isSelected = selected?.slug === c.slug;
                      return (
                        <circle
                          key={c.slug}
                          cx={cx}
                          cy={cy}
                          r={isSelected ? 6 / Math.sqrt(zoom) : c.short_listed ? 5 / Math.sqrt(zoom) : 3 / Math.sqrt(zoom)}
                          fill={c.short_listed ? "var(--accent)" : "var(--muted)"}
                          stroke={isSelected ? "white" : c.short_listed ? "gold" : "none"}
                          strokeWidth={isSelected ? 2 / Math.sqrt(zoom) : c.short_listed ? 1.5 / Math.sqrt(zoom) : 0}
                          opacity={hovered && hovered.slug !== c.slug && !isSelected ? 0.35 : 0.85}
                          onMouseEnter={() => setHovered(c)}
                          onMouseLeave={() => setHovered((h) => (h?.slug === c.slug ? null : h))}
                          onClick={() => setSelected(c)}
                          style={{ cursor: "pointer" }}
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
                <p className={hovered.short_listed ? "text-ok" : "text-muted"}>
                  {hovered.short_listed ? "On watchlist" : "Click to select"}
                </p>
              </div>
            ) : null}
          </div>
        </div>
      }
      bottom={detailPane}
      defaultTopPercent={70}
    />
  );
}
