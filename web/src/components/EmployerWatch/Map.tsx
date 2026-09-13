import { useMemo, useState } from "react";

import CompanyDetailPane from "@/components/EmployerWatch/CompanyDetailPane";
import SplitPane from "@/components/SplitPane";
import { useRectZoom } from "@/hooks/useRectZoom";
import { type MapCompany } from "@/lib/api";

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
  const [mapSearch, setMapSearch] = useState("");

  const { zoom, transform, selectionRect, isDragging, onWheel, onPointerDown, onPointerMove, onPointerUp, resetZoom } =
    useRectZoom({ viewWidth: WIDTH, viewHeight: HEIGHT });

  const watchlistedCount = useMemo(() => companies.filter((c) => c.short_listed).length, [companies]);

  const searchMatches = useMemo(() => {
    const q = mapSearch.trim().toLowerCase();
    if (!q) return null;
    return new Set(
      companies
        .filter((c) => c.name.toLowerCase().includes(q))
        .map((c) => c.slug),
    );
  }, [companies, mapSearch]);

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

  const handleSearchChange = (q: string) => {
    setMapSearch(q);
    if (!q.trim()) return;
    const firstMatch = companies.find((c) =>
      c.name.toLowerCase().includes(q.trim().toLowerCase()),
    );
    if (firstMatch) {
      setSelected(firstMatch);
    }
  };

  const detailPane = selected ? (
    <CompanyDetailPane
      company={selected}
      onCompaniesChange={(updater) => {
        const updated = updater(selected);
        setSelected(updated);
        onCompaniesChange(companies.map((c) => (c.slug === updated.slug ? updated : c)));
      }}
    />
  ) : (
    <p className="p-4 text-sm text-muted">Click a company dot to see its details.</p>
  );

  return (
    <SplitPane
      top={
        <div className="space-y-2 p-2">
          {/* Header: counts + search */}
          <div className="flex flex-wrap items-center gap-3">
            <p className="text-xs text-muted">
              {companies.length} companies · {watchlistedCount} on watchlist · scroll/shift+drag to zoom, drag to pan
            </p>
            <button
              type="button"
              onClick={resetZoom}
              className="rounded-card border border-border-subtle px-2 py-0.5 text-xs text-muted"
            >
              Reset
            </button>
            <input
              value={mapSearch}
              onChange={(e) => handleSearchChange(e.target.value)}
              placeholder="Search company name…"
              className="rounded-card border border-border-subtle bg-surface px-2 py-1 text-xs text-ink placeholder:text-muted"
              style={{ minWidth: 180 }}
            />
            {mapSearch && searchMatches && searchMatches.size === 0 ? (
              <span className="text-xs text-danger">No matches</span>
            ) : null}
          </div>
          <div className="relative overflow-hidden rounded-card border border-border-subtle bg-surface">
            <svg
              viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
              className="h-[500px] w-full cursor-grab active:cursor-grabbing"
              onWheel={onWheel}
              onPointerDown={onPointerDown}
              onPointerMove={onPointerMove}
              onPointerUp={onPointerUp}
              onPointerLeave={onPointerUp}
            >
              <g transform={transform}>
                {scale
                  ? companies.map((c) => {
                      const { cx, cy } = scale(c.x, c.y);
                      const isSelected = selected?.slug === c.slug;
                      const isMatch = searchMatches ? searchMatches.has(c.slug) : false;
                      return (
                        <circle
                          key={c.slug}
                          cx={cx}
                          cy={cy}
                          r={isSelected ? 6 / Math.sqrt(zoom) : c.short_listed ? 5 / Math.sqrt(zoom) : 3 / Math.sqrt(zoom)}
                          fill={c.short_listed ? "var(--accent)" : isMatch ? "var(--ok)" : "var(--muted)"}
                          stroke={isSelected ? "white" : isMatch ? "var(--ok)" : c.short_listed ? "gold" : "none"}
                          strokeWidth={isSelected ? 2 / Math.sqrt(zoom) : isMatch ? 1.5 / Math.sqrt(zoom) : c.short_listed ? 1.5 / Math.sqrt(zoom) : 0}
                          opacity={hovered && hovered.slug !== c.slug && !isSelected ? 0.35 : 0.85}
                          onMouseEnter={() => setHovered(c)}
                          onMouseLeave={() => setHovered((h) => (h?.slug === c.slug ? null : h))}
                          onClick={() => { if (!isDragging) setSelected(c); }}
                          style={{ cursor: "pointer" }}
                        />
                      );
                    })
                  : null}
              </g>
              {selectionRect ? (
                <rect
                  x={Math.min(selectionRect.x1, selectionRect.x2)}
                  y={Math.min(selectionRect.y1, selectionRect.y2)}
                  width={Math.abs(selectionRect.x2 - selectionRect.x1)}
                  height={Math.abs(selectionRect.y2 - selectionRect.y1)}
                  fill="var(--accent)"
                  fillOpacity={0.1}
                  stroke="var(--accent)"
                  strokeWidth={1}
                  strokeDasharray="4 2"
                  pointerEvents="none"
                />
              ) : null}
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
