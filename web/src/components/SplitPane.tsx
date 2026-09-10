import { useCallback, useRef, useState } from "react";

interface SplitPaneProps {
  top: React.ReactNode;
  bottom: React.ReactNode;
  defaultTopPercent?: number;
  minTopPercent?: number;
  maxTopPercent?: number;
}

export default function SplitPane({
  top,
  bottom,
  defaultTopPercent = 55,
  minTopPercent = 20,
  maxTopPercent = 80,
}: SplitPaneProps) {
  const [topPercent, setTopPercent] = useState(defaultTopPercent);
  const containerRef = useRef<HTMLDivElement>(null);
  const dragging = useRef(false);

  const onPointerDown = useCallback((e: React.PointerEvent) => {
    dragging.current = true;
    (e.target as Element).setPointerCapture(e.pointerId);
  }, []);

  const onPointerMove = useCallback(
    (e: React.PointerEvent) => {
      if (!dragging.current || !containerRef.current) return;
      const rect = containerRef.current.getBoundingClientRect();
      const pct = ((e.clientY - rect.top) / rect.height) * 100;
      setTopPercent(Math.min(maxTopPercent, Math.max(minTopPercent, pct)));
    },
    [minTopPercent, maxTopPercent],
  );

  const onPointerUp = useCallback(() => {
    dragging.current = false;
  }, []);

  return (
    <div
      ref={containerRef}
      className="flex h-full flex-col"
      onPointerMove={onPointerMove}
      onPointerUp={onPointerUp}
      onPointerLeave={onPointerUp}
    >
      <div style={{ height: `${topPercent}%` }} className="overflow-auto">
        {top}
      </div>
      <div
        className="flex h-2 cursor-row-resize items-center justify-center bg-border-subtle hover:bg-accent/30 active:bg-accent/50"
        onPointerDown={onPointerDown}
        title="Drag to resize"
      >
        <div className="h-0.5 w-8 rounded-full bg-muted/50" />
      </div>
      <div style={{ height: `calc(${100 - topPercent}% - 8px)` }} className="overflow-auto">
        {bottom}
      </div>
    </div>
  );
}
