import { useRef, useState } from "react";
import type { Point } from "../api";

type Props = {
  points: Point[];
  width?: number;
  height?: number;
  format: (v: number) => string;
  label: string; // accessible name, e.g. "JUP price, last 24 hours"
};

/** Single-series sparkline: 2px line, 10% wash, end dot with surface ring, crosshair + tooltip on hover. */
export function Sparkline({ points, width = 120, height = 30, format, label }: Props) {
  const [hover, setHover] = useState<number | null>(null);
  const ref = useRef<SVGSVGElement>(null);
  if (points.length < 2) return <span className="muted">collecting…</span>;

  const pad = 5;
  const vs = points.map((p) => p.v);
  const lo = Math.min(...vs);
  const hi = Math.max(...vs);
  const span = hi - lo || Math.abs(hi) || 1;
  const x = (i: number) => pad + (i * (width - 2 * pad)) / (points.length - 1);
  const y = (v: number) => pad + (1 - (v - lo) / span) * (height - 2 * pad);
  const line = points.map((p, i) => `${i ? "L" : "M"}${x(i).toFixed(1)},${y(p.v).toFixed(1)}`).join("");
  const area = `${line}L${x(points.length - 1).toFixed(1)},${height}L${x(0).toFixed(1)},${height}Z`;
  const last = points.length - 1;

  const onMove = (e: React.PointerEvent) => {
    const r = ref.current?.getBoundingClientRect();
    if (!r) return;
    const i = Math.round(((e.clientX - r.left - pad) / (r.width - 2 * pad)) * (points.length - 1));
    setHover(Math.max(0, Math.min(points.length - 1, i)));
  };
  const h = hover != null ? points[hover] : null;

  return (
    <div className="chart" style={{ width }}>
      <svg
        ref={ref}
        width={width}
        height={height}
        role="img"
        aria-label={`${label}: from ${format(points[0].v)} to ${format(points[last].v)}`}
        onPointerMove={onMove}
        onPointerLeave={() => setHover(null)}
        style={{ touchAction: "none" }}
      >
        <path d={area} fill="var(--series-1-wash)" />
        <path d={line} fill="none" stroke="var(--series-1)" strokeWidth={2} strokeLinejoin="round" strokeLinecap="round" />
        {hover != null && <line x1={x(hover)} x2={x(hover)} y1={0} y2={height} stroke="var(--axis)" strokeWidth={1} />}
        <circle
          cx={x(hover ?? last)}
          cy={y(points[hover ?? last].v)}
          r={4}
          fill="var(--series-1)"
          stroke="var(--surface-1)"
          strokeWidth={2}
        />
        <rect x={0} y={0} width={width} height={height} fill="transparent" />
      </svg>
      {h && (
        <div className="tooltip" style={{ left: Math.min(x(hover!) + 10, width - 10), top: -6, transform: "translateY(-100%)" }}>
          <strong>{format(h.v)}</strong>
          <span className="muted">{new Date(h.t).toISOString().slice(11, 16)} UTC</span>
        </div>
      )}
    </div>
  );
}
