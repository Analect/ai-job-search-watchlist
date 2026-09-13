import { useCallback, useRef, useState } from "react";

export interface RectZoomRect {
  x1: number;
  y1: number;
  x2: number;
  y2: number;
}

export interface UseRectZoomOptions {
  viewWidth: number;
  viewHeight: number;
  maxZoom?: number;
}

export interface UseRectZoomResult {
  zoom: number;
  pan: { x: number; y: number };
  transform: string;
  /** The pending selection rectangle in SVG-element-local coordinates (null when no rect in progress). */
  selectionRect: RectZoomRect | null;
  /** True while a pointer drag is in progress — dot click handlers should check this. */
  isDragging: boolean;
  onWheel: (e: React.WheelEvent) => void;
  onPointerDown: (e: React.PointerEvent<Element>) => void;
  onPointerMove: (e: React.PointerEvent<Element>) => void;
  onPointerUp: (e: React.PointerEvent<Element>) => void;
  resetZoom: () => void;
  /** Pan the map so that the SVG-data-space point (x, y) appears at the viewport centre. */
  centreOn: (x: number, y: number) => void;
}

type Mode = "idle" | "panning" | "selecting";

interface PointerState {
  mode: Mode;
  // startX/Y are in SVG-element-local coordinates (clientX - svgRect.left)
  startX: number;
  startY: number;
  panX: number;
  panY: number;
}

/**
 * Provides scroll-zoom, drag-pan, and shift+drag rect-select-to-zoom for
 * an SVG canvas. The returned `transform` string goes directly on the inner
 * `<g>` element; `selectionRect` (screen coords) drives an overlay `<rect>`.
 *
 * Shift key while pressing selects instead of panning. On release the view
 * zooms to fill the drawn rectangle; a small rect (< 10px) is ignored and
 * treated as a click.
 */
export function useRectZoom({
  viewWidth,
  viewHeight,
  maxZoom = 20,
}: UseRectZoomOptions): UseRectZoomResult {
  const [zoom, setZoom] = useState(1);
  const [pan, setPan] = useState({ x: 0, y: 0 });
  const [selectionRect, setSelectionRect] = useState<RectZoomRect | null>(null);
  // isDragging: true while a pan/select drag has moved more than a few pixels.
  // Dot onClick handlers check this to distinguish a click from a drag.
  const [isDragging, setIsDragging] = useState(false);

  const ptrState = useRef<PointerState | null>(null);
  // Snapshot of current zoom/pan captured at pointer-down so we don't close
  // over stale state inside the move/up handlers.
  const snapshot = useRef<{ zoom: number; pan: { x: number; y: number } }>({
    zoom: 1,
    pan: { x: 0, y: 0 },
  });

  const onWheel = useCallback(
    (e: React.WheelEvent) => {
      e.preventDefault();
      setZoom((z) => {
        const next = Math.min(maxZoom, Math.max(1, z * (e.deltaY < 0 ? 1.1 : 0.9)));
        snapshot.current.zoom = next;
        return next;
      });
    },
    [maxZoom],
  );

  const onPointerDown = useCallback((e: React.PointerEvent<Element>) => {
    (e.currentTarget as Element).setPointerCapture(e.pointerId);
    const mode: Mode = e.shiftKey ? "selecting" : "panning";
    // T019/T020: convert client coords to SVG-element-local coords at pointer-down.
    // This makes the selection rect and zoom computation share the same reference
    // frame, so the rectangle origin matches the actual pointer-down position even
    // after the map has been panned or scaled.
    const svgRect = (e.currentTarget as Element).getBoundingClientRect();
    const lx = e.clientX - svgRect.left;
    const ly = e.clientY - svgRect.top;
    // T020: clamp — ignore a drag-start outside the SVG's own bounds
    if (lx < 0 || ly < 0 || lx > svgRect.width || ly > svgRect.height) return;
    ptrState.current = {
      mode,
      startX: lx,
      startY: ly,
      panX: snapshot.current.pan.x,
      panY: snapshot.current.pan.y,
    };
    if (mode === "selecting") {
      setSelectionRect({ x1: lx, y1: ly, x2: lx, y2: ly });
    }
  }, []);

  const onPointerMove = useCallback((e: React.PointerEvent<Element>) => {
    const s = ptrState.current;
    if (!s) return;
    const svgRect = (e.currentTarget as Element).getBoundingClientRect();
    const lx = e.clientX - svgRect.left;
    const ly = e.clientY - svgRect.top;
    if (s.mode === "panning") {
      const dx = lx - s.startX;
      const dy = ly - s.startY;
      if (!isDragging && (Math.abs(dx) > 4 || Math.abs(dy) > 4)) setIsDragging(true);
      const px = s.panX + dx;
      const py = s.panY + dy;
      setPan({ x: px, y: py });
      snapshot.current.pan = { x: px, y: py };
    } else if (s.mode === "selecting") {
      if (!isDragging) setIsDragging(true);
      setSelectionRect({ x1: s.startX, y1: s.startY, x2: lx, y2: ly });
    }
  }, [isDragging]);

  const onPointerUp = useCallback(
    (e: React.PointerEvent<Element>) => {
      const s = ptrState.current;
      ptrState.current = null;
      setIsDragging(false);
      if (!s) return;

      if (s.mode === "selecting") {
        setSelectionRect(null);
        const svgRect = (e.currentTarget as SVGElement).getBoundingClientRect();
        const lx = e.clientX - svgRect.left;
        const ly = e.clientY - svgRect.top;
        const rectW = Math.abs(lx - s.startX);
        const rectH = Math.abs(ly - s.startY);
        // Ignore tiny rects (clicks)
        if (rectW < 10 || rectH < 10) return;

        // s.startX/Y are already SVG-element-local (set in onPointerDown).
        // Convert element-local coords to SVG-viewBox coords via current transform.
        const curZoom = snapshot.current.zoom;
        const curPan = snapshot.current.pan;
        const rx1 = (Math.min(s.startX, lx) - curPan.x) / curZoom;
        const rx2 = (Math.max(s.startX, lx) - curPan.x) / curZoom;
        const ry1 = (Math.min(s.startY, ly) - curPan.y) / curZoom;
        const ry2 = (Math.max(s.startY, ly) - curPan.y) / curZoom;

        const newZoom = Math.min(
          maxZoom,
          Math.min(viewWidth / (rx2 - rx1 || 1), viewHeight / (ry2 - ry1 || 1)),
        );
        const newPanX = viewWidth / 2 - ((rx1 + rx2) / 2) * newZoom;
        const newPanY = viewHeight / 2 - ((ry1 + ry2) / 2) * newZoom;
        setZoom(newZoom);
        setPan({ x: newPanX, y: newPanY });
        snapshot.current = { zoom: newZoom, pan: { x: newPanX, y: newPanY } };
      }
    },
    [viewWidth, viewHeight, maxZoom],
  );

  const resetZoom = useCallback(() => {
    setZoom(1);
    setPan({ x: 0, y: 0 });
    snapshot.current = { zoom: 1, pan: { x: 0, y: 0 } };
  }, []);

  const centreOn = useCallback((x: number, y: number) => {
    const z = snapshot.current.zoom;
    const newPan = { x: viewWidth / 2 - x * z, y: viewHeight / 2 - y * z };
    setPan(newPan);
    snapshot.current.pan = newPan;
  }, [viewWidth, viewHeight]);

  return {
    zoom,
    pan,
    transform: `translate(${pan.x} ${pan.y}) scale(${zoom})`,
    selectionRect,
    isDragging,
    onWheel,
    onPointerDown,
    onPointerMove,
    onPointerUp,
    resetZoom,
    centreOn,
  };
}
