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
  /** The pending selection rectangle in screen coordinates (null when no rect in progress). */
  selectionRect: RectZoomRect | null;
  onWheel: (e: React.WheelEvent) => void;
  onPointerDown: (e: React.PointerEvent<Element>) => void;
  onPointerMove: (e: React.PointerEvent<Element>) => void;
  onPointerUp: (e: React.PointerEvent<Element>) => void;
  resetZoom: () => void;
}

type Mode = "idle" | "panning" | "selecting";

interface PointerState {
  mode: Mode;
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
    ptrState.current = {
      mode,
      startX: e.clientX,
      startY: e.clientY,
      panX: snapshot.current.pan.x,
      panY: snapshot.current.pan.y,
    };
    if (mode === "selecting") {
      setSelectionRect({ x1: e.clientX, y1: e.clientY, x2: e.clientX, y2: e.clientY });
    }
  }, []);

  const onPointerMove = useCallback((e: React.PointerEvent<Element>) => {
    const s = ptrState.current;
    if (!s) return;
    if (s.mode === "panning") {
      const px = s.panX + (e.clientX - s.startX);
      const py = s.panY + (e.clientY - s.startY);
      setPan({ x: px, y: py });
      snapshot.current.pan = { x: px, y: py };
    } else if (s.mode === "selecting") {
      setSelectionRect({ x1: s.startX, y1: s.startY, x2: e.clientX, y2: e.clientY });
    }
  }, []);

  const onPointerUp = useCallback(
    (e: React.PointerEvent<Element>) => {
      const s = ptrState.current;
      ptrState.current = null;
      if (!s) return;

      if (s.mode === "selecting") {
        setSelectionRect(null);
        const rectW = Math.abs(e.clientX - s.startX);
        const rectH = Math.abs(e.clientY - s.startY);
        // Ignore tiny rects (clicks)
        if (rectW < 10 || rectH < 10) return;

        const svgRect = (e.currentTarget as SVGElement).getBoundingClientRect();
        // Convert screen rect to SVG-local coords (accounting for current transform)
        const curZoom = snapshot.current.zoom;
        const curPan = snapshot.current.pan;
        const ox = svgRect.left;
        const oy = svgRect.top;
        const rx1 = (Math.min(s.startX, e.clientX) - ox - curPan.x) / curZoom;
        const rx2 = (Math.max(s.startX, e.clientX) - ox - curPan.x) / curZoom;
        const ry1 = (Math.min(s.startY, e.clientY) - oy - curPan.y) / curZoom;
        const ry2 = (Math.max(s.startY, e.clientY) - oy - curPan.y) / curZoom;

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

  return {
    zoom,
    pan,
    transform: `translate(${pan.x} ${pan.y}) scale(${zoom})`,
    selectionRect,
    onWheel,
    onPointerDown,
    onPointerMove,
    onPointerUp,
    resetZoom,
  };
}
