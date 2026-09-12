import { useMemo, useState } from "react";

import PostingDetailPane from "@/components/PostingDetailPane";
import SplitPane from "@/components/SplitPane";
import { useRectZoom } from "@/hooks/useRectZoom";
import {
  fetchPostingDetail,
  postPostingEvent,
  type MapJob,
  type PostingDetail,
} from "@/lib/api";

const WIDTH = 900;
const HEIGHT = 500;
const PADDING = 40;

interface JobWatchMapProps {
  jobs: MapJob[];
  onJobsChange: (next: MapJob[]) => void;
}

function jobColor(j: MapJob): string {
  if (j.promoted) return "var(--accent)";
  if (j.flagged)  return "var(--ok)";
  // thumbs_up/thumbs_down come through as review_state on the MapJob type;
  // fall through to muted for all other states.
  return "var(--muted)";
}

export default function JobWatchMap({ jobs, onJobsChange }: JobWatchMapProps) {
  const [hovered, setHovered] = useState<MapJob | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [detail, setDetail] = useState<PostingDetail | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);

  const { zoom, transform, selectionRect, onWheel, onPointerDown, onPointerMove, onPointerUp, resetZoom } =
    useRectZoom({ viewWidth: WIDTH, viewHeight: HEIGHT });

  const scale = useMemo(() => {
    if (jobs.length === 0) return null;
    const xs = jobs.map((j) => j.x);
    const ys = jobs.map((j) => j.y);
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
  }, [jobs]);

  const selectJob = (job: MapJob) => {
    setSelectedId(job.id);
    setDetail(null);
    setDetailLoading(true);
    fetchPostingDetail(job.id)
      .then((d) => {
        setDetail(d);
        if (!d.posting.reviewed) {
          postPostingEvent(job.id, "reviewed").catch(() => null);
        }
      })
      .catch(() => null)
      .finally(() => setDetailLoading(false));
  };

  const handleStateChange = (id: string, patch: Record<string, unknown>) => {
    onJobsChange(
      jobs.map((j) => (j.id === id ? { ...j, ...patch } as MapJob : j)),
    );
    if (detail && detail.posting.id === id) {
      setDetail((d) => d ? { ...d, posting: { ...d.posting, ...patch } } : d);
    }
  };

  return (
    <SplitPane
      top={
        <div className="space-y-2 p-2">
          <div className="flex items-center gap-3">
            <p className="text-xs text-muted">
              {jobs.length} postings · purple=promoted · green=flagged · scroll/shift+drag to zoom, drag to pan
            </p>
            <button
              type="button"
              onClick={resetZoom}
              className="rounded-card border border-border-subtle px-2 py-0.5 text-xs text-muted"
            >
              Reset
            </button>
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
                  ? jobs.map((j) => {
                      const { cx, cy } = scale(j.x, j.y);
                      const isSelected = j.id === selectedId;
                      return (
                        <circle
                          key={j.id}
                          cx={cx}
                          cy={cy}
                          r={isSelected ? 6 / Math.sqrt(zoom) : 3 / Math.sqrt(zoom)}
                          fill={jobColor(j)}
                          stroke={isSelected ? "white" : "none"}
                          strokeWidth={isSelected ? 2 / Math.sqrt(zoom) : 0}
                          opacity={hovered && hovered.id !== j.id && !isSelected ? 0.35 : 0.85}
                          onMouseEnter={() => setHovered(j)}
                          onMouseLeave={() => setHovered((h) => (h?.id === j.id ? null : h))}
                          onClick={() => selectJob(j)}
                          style={{ cursor: "pointer" }}
                        />
                      );
                    })
                  : null}
              </g>
              {/* Rect-zoom selection overlay — rendered outside the zoomable <g> */}
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
              <div className="pointer-events-none absolute left-3 top-3 max-w-xs rounded-card border border-border-subtle bg-surface px-3 py-2 text-xs shadow">
                <p className="font-medium text-ink">{hovered.title}</p>
                <p className="text-muted">{hovered.employer_name}</p>
              </div>
            ) : null}
          </div>
        </div>
      }
      bottom={
        <PostingDetailPane
          detail={detail}
          loading={detailLoading}
          onStateChange={handleStateChange}
        />
      }
      defaultTopPercent={65}
    />
  );
}
