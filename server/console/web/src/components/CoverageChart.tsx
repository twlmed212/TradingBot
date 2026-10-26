import { useState } from "react";
import type { CoverageHour } from "../api";

/** Cycles recorded per hour against the 60 possible: single series, columns from one baseline, per-bar tooltip. */
export function CoverageChart({ hours }: { hours: CoverageHour[] }) {
  const [hover, setHover] = useState<number | null>(null);
  const width = 920;
  const height = 150;
  const left = 30;
  const bottom = 22;
  const plotH = height - bottom - 8;
  const slot = (width - left) / hours.length;
  const barW = Math.min(24, slot - 2);
  const y = (v: number) => 8 + plotH - (v / 60) * plotH;
  const h = hover != null ? hours[hover] : null;

  return (
    <div className="chart-scroll">
    <div className="chart" style={{ maxWidth: width }}>
      <svg viewBox={`0 0 ${width} ${height}`} width="100%" role="img"
        aria-label="Recorder cycles per hour over the last 24 hours, out of 60 possible">
        {[0, 30, 60].map((t) => (
          <g key={t}>
            <line x1={left} x2={width} y1={y(t)} y2={y(t)} stroke={t === 0 ? "var(--axis)" : "var(--grid)"} strokeWidth={1} />
            <text x={left - 6} y={y(t) + 4} textAnchor="end" fontSize="11" fill="var(--text-muted)">{t}</text>
          </g>
        ))}
        {hours.map((d, i) => {
          const cx = left + i * slot + slot / 2;
          const v = Math.min(d.cycles, 60);
          const top = y(v);
          const barH = Math.max(y(0) - top, 0);
          const r = Math.min(4, barH);
          const x0 = cx - barW / 2;
          // rounded data-end (top), square at the baseline
          const path = barH > 0
            ? `M${x0},${y(0)}V${top + r}Q${x0},${top} ${x0 + r},${top}H${x0 + barW - r}Q${x0 + barW},${top} ${x0 + barW},${top + r}V${y(0)}Z`
            : "";
          const missing = d.possible > 0 && d.cycles < d.possible * 0.95;
          return (
            <g key={d.hour}>
              {path && <path d={path} fill="var(--series-1)" opacity={hover == null || hover === i ? 1 : 0.55} />}
              {missing && <text x={cx} y={top - 4} textAnchor="middle" fontSize="10" fill="var(--text-secondary)">gap</text>}
              {i % 3 === 0 && (
                <text x={cx} y={height - 6} textAnchor="middle" fontSize="11" fill="var(--text-muted)">
                  {d.hour.slice(11, 16)}
                </text>
              )}
              <rect
                x={left + i * slot}
                y={0}
                width={slot}
                height={height - bottom}
                fill="transparent"
                tabIndex={0}
                onPointerEnter={() => setHover(i)}
                onPointerLeave={() => setHover(null)}
                onFocus={() => setHover(i)}
                onBlur={() => setHover(null)}
              />
            </g>
          );
        })}
      </svg>
      {h && hover != null && (
        <div className="tooltip" style={{ left: `${((left + hover * slot + slot / 2) / width) * 100}%`, top: 0, transform: "translate(-50%, -100%)" }}>
          <strong>{h.cycles} of {h.possible || 60} cycles</strong>
          <span className="muted">{h.hour.slice(11, 16)} UTC · {h.recorded}/{h.expected} readings</span>
        </div>
      )}
    </div>
    </div>
  );
}

export function CoverageTable({ hours }: { hours: CoverageHour[] }) {
  return (
    <div className="table-wrap">
      <table>
        <thead>
          <tr><th>Hour (UTC)</th><th className="num">Cycles</th><th className="num">Possible</th><th className="num">Readings</th><th className="num">Expected</th></tr>
        </thead>
        <tbody>
          {hours.slice().reverse().map((d) => (
            <tr key={d.hour}>
              <td>{d.hour.slice(0, 16).replace("T", " ")}</td>
              <td className="num">{d.cycles}</td>
              <td className="num">{d.possible}</td>
              <td className="num">{d.recorded}</td>
              <td className="num">{d.expected}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
