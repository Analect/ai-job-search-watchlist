import { useMemo, useRef, useState } from "react";

import PostingDetailPane from "@/components/PostingDetailPane";
import SplitPane from "@/components/SplitPane";
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

export default function JobWatchMap({ jobs, onJobsChange }: JobWatchMapProps) {
  const [hovered, setHovered] = useState<MapJob | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [detail, setDetail] = useState<PostingDetail | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);

  const [zoom, setZoom] = useState(1);
  const [pan, setPan] = useState({ x: 0, y: 0 });
  const dragState = useRef<{ startX: number; startY: number; panX: number; panY: number } | null>(null);

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
          <p className="text-xs text-muted">
            {jobs.length} postings · purple = promoted · scroll to zoom, drag to pan
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
                  ? jobs.map((j) => {
                      const { cx, cy } = scale(j.x, j.y);
                      const isSelected = j.id === selectedId;
                      const color = j.promoted
                        ? "var(--accent)"
                        : j.flagged
                        ? "var(--ok)"
                        : "var(--muted)";
                      return (
                        <circle
                          key={j.id}
                          cx={cx}
                          cy={cy}
                          r={isSelected ? 6 / Math.sqrt(zoom) : 3 / Math.sqrt(zoom)}
                          fill={color}
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
