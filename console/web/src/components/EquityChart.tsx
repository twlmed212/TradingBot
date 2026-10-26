import { useRef, useState } from "react";
import { fmtSignedPct, fmtUsd, type Point } from "../api";

type Props = { points: Point[]; start: string; startEquity: number; apr: number };

const HOUR_MS = 3_600_000;
const YEAR_MS = 365 * 24 * HOUR_MS;

function niceStep(span: number, target: number): number {
  const raw = span / target;
  const mag = 10 ** Math.floor(Math.log10(raw));
  const n = raw / mag;
  return (n < 1.5 ? 1 : n < 3 ? 2 : n < 7 ? 5 : 10) * mag;
}

/** Hourly paper equity (solid) against USDC lending at 5% (dashed reference) and the starting balance; crosshair tooltip. */
export function EquityChart({ points, start, startEquity, apr }: Props) {
  const [hover, setHover] = useState<number | null>(null);
  const ref = useRef<SVGSVGElement>(null);
  if (points.length < 2) return <p className="muted">The chart starts after the second hourly run.</p>;

  const width = 920;
  const height = 230;
  const left = 64;
  const right = 12;
  const top = 12;
  const bottom = 24;
  const plotW = width - left - right;
  const plotH = height - top - bottom;

  const t0 = new Date(start).getTime();
  const ts = points.map((p) => new Date(p.t).getTime());
  const bench = ts.map((t) => startEquity * (1 + apr) ** ((t - t0) / YEAR_MS));
  const all = [...points.map((p) => p.v), ...bench, startEquity];
  const pad = Math.max((Math.max(...all) - Math.min(...all)) * 0.08, startEquity * 0.002);
  const lo = Math.min(...all) - pad;
  const hi = Math.max(...all) + pad;
  const step = niceStep(hi - lo, 4);
  const yTicks: number[] = [];
  for (let v = Math.ceil(lo / step) * step; v <= hi; v += step) yTicks.push(v);

  const tMin = ts[0];
  const tMax = ts[ts.length - 1];
  const x = (t: number) => left + ((t - tMin) / (tMax - tMin)) * plotW;
  const y = (v: number) => top + (1 - (v - lo) / (hi - lo)) * plotH;
  const path = (vals: number[]) => vals.map((v, i) => `${i ? "L" : "M"}${x(ts[i]).toFixed(1)},${y(v).toFixed(1)}`).join("");

  // time ticks on UTC hour or day boundaries, at most ~6 of them
  const spanH = (tMax - tMin) / HOUR_MS;
  const stepH = [1, 3, 6, 12, 24, 48, 96, 168, 336].find((s) => spanH / s <= 6) ?? 672;
  const xTicks: number[] = [];
  for (let t = Math.ceil(tMin / (stepH * HOUR_MS)) * stepH * HOUR_MS; t <= tMax; t += stepH * HOUR_MS) xTicks.push(t);
  const xLabel = (t: number) => {
    const s = new Date(t).toISOString();
    return stepH < 24 ? s.slice(11, 16) : s.slice(5, 10);
  };

  const onMove = (e: React.PointerEvent) => {
    const r = ref.current?.getBoundingClientRect();
    if (!r) return;
    const t = tMin + (((e.clientX - r.left) / r.width) * width - left) / plotW * (tMax - tMin);
    let best = 0;
    for (let i = 1; i < ts.length; i++) if (Math.abs(ts[i] - t) < Math.abs(ts[best] - t)) best = i;
    setHover(best);
  };
  const h = hover != null ? points[hover] : null;
  const last = points[points.length - 1];

  return (
    <div>
      <div className="legend" aria-hidden="true">
        <span><i className="key-solid" />Paper equity</span>
        <span><i className="key-dashed" />USDC lending at 5% (benchmark)</span>
        <span><i className="key-ref" />Start {fmtUsd(startEquity, 0)}</span>
      </div>
      <div className="chart-scroll">
      <div className="chart" style={{ maxWidth: width }}>
        <svg
          ref={ref}
          viewBox={`0 0 ${width} ${height}`}
          width="100%"
          role="img"
          aria-label={`Paper equity by hour, from ${fmtUsd(points[0].v)} to ${fmtUsd(last.v)}; USDC at 5% would be ${fmtUsd(bench[bench.length - 1])}`}
          onPointerMove={onMove}
          onPointerLeave={() => setHover(null)}
          style={{ touchAction: "none" }}
        >
          {yTicks.map((v) => (
            <g key={v}>
              <line x1={left} x2={width - right} y1={y(v)} y2={y(v)} stroke="var(--grid)" strokeWidth={1} />
              <text x={left - 8} y={y(v) + 4} textAnchor="end" fontSize="11" fill="var(--text-muted)">{fmtUsd(v, 0)}</text>
            </g>
          ))}
          <line x1={left} x2={width - right} y1={top + plotH} y2={top + plotH} stroke="var(--axis)" strokeWidth={1} />
          {xTicks.map((t) => (
            <text key={t} x={x(t)} y={height - 6} textAnchor="middle" fontSize="11" fill="var(--text-muted)">{xLabel(t)}</text>
          ))}
          <line x1={left} x2={width - right} y1={y(startEquity)} y2={y(startEquity)} stroke="var(--axis)" strokeWidth={1} />
          <path d={path(bench)} fill="none" stroke="var(--text-muted)" strokeWidth={1.5} strokeDasharray="5 4" />
          <path d={path(points.map((p) => p.v))} fill="none" stroke="var(--series-1)" strokeWidth={2} strokeLinejoin="round" strokeLinecap="round" />
          {hover != null && <line x1={x(ts[hover])} x2={x(ts[hover])} y1={top} y2={top + plotH} stroke="var(--axis)" strokeWidth={1} />}
          <circle cx={x(ts[hover ?? ts.length - 1])} cy={y((h ?? last).v)} r={4} fill="var(--series-1)" stroke="var(--surface-1)" strokeWidth={2} />
        </svg>
        {h && hover != null && (
          <div className="tooltip" style={{ left: `${(x(ts[hover]) / width) * 100}%`, top: 0, transform: `translate(${x(ts[hover]) > width * 0.7 ? "-105%" : "8px"}, 0)` }}>
            <strong>{fmtUsd(h.v)}</strong>
            <span className="muted">{fmtSignedPct(h.v / startEquity - 1, 2)} vs start · USDC 5%: {fmtUsd(bench[hover])}</span>
            <span className="muted" style={{ display: "block" }}>{h.t.slice(0, 16).replace("T", " ")} UTC</span>
          </div>
        )}
      </div>
      </div>
    </div>
  );
}
