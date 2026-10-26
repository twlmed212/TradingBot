import { useState } from "react";
import {
  ageOf, fmtAge, fmtPct, fmtPrice, fmtSignedPct, fmtSignedUsd, fmtTimeUtc, fmtUsd,
  type Announcements, type CoverageHour, type H9, type H9Token, type Market, type Markets, type Overview, type Poll, type Research,
} from "./api";
import { CoverageChart, CoverageTable } from "./components/CoverageChart";
import { EquityChart } from "./components/EquityChart";
import { Sparkline } from "./components/Sparkline";
import { Status, type Level } from "./components/Status";

const COST_LIMIT_BPS = 50; // a round trip above 50 bps at the intended size is flagged as too costly

function Card(props: { id: string; title: string; sub?: string; actions?: React.ReactNode; stale?: boolean; children: React.ReactNode }) {
  return (
    <section className="card" id={props.id} aria-labelledby={`${props.id}-h`}>
      <div className="card-head">
        <h2 id={`${props.id}-h`}>{props.title}</h2>
        {props.sub && <span className="sub">{props.sub}</span>}
        {props.actions && <div className="actions">{props.actions}</div>}
      </div>
      <div className={props.stale ? "stale" : undefined}>{props.children}</div>
    </section>
  );
}

function Tile({ label, value, meta, status }: { label: string; value: React.ReactNode; meta?: React.ReactNode; status?: React.ReactNode }) {
  return (
    <div className="tile">
      <span className="label">{label}</span>
      {status}
      <span className="value">{value}</span>
      {meta && <span className="meta">{meta}</span>}
    </div>
  );
}

function ErrorBanner({ what, error }: { what: string; error: string | null }) {
  return error ? <div className="error-banner" role="alert">Could not load {what}: {error}. Showing the last data received.</div> : null;
}

// --- health -----------------------------------------------------------------

function recorderLevel(o: Overview): [Level, string] {
  const age = o.recorder.last_cycle_age_s;
  if (o.recorder.service === "failed" || o.recorder.service === "inactive") return ["critical", "Stopped"];
  if (age == null) return ["neutral", "No data yet"];
  if (age < 150) return ["good", "Recording"];
  if (age < 600) return ["warning", "Delayed"];
  return ["critical", "Not recording"];
}

function coverageLevel(x: number | null): Level {
  if (x == null) return "neutral";
  if (x >= 0.995) return "good";
  if (x >= 0.95) return "warning";
  return "serious";
}

export function Health({ overview, coverage }: { overview: Poll<Overview>; coverage: Poll<CoverageHour[]> }) {
  const [table, setTable] = useState(false);
  const o = overview.data;
  if (!o) return <Card id="health" title="Data health"><ErrorBanner what="health" error={overview.error} />{!overview.error && <p className="muted">Loading…</p>}</Card>;
  const [lvl, lbl] = recorderLevel(o);
  const r = o.recorder;
  const lastSeen = ageOf(o.announcements.last_seen_at);
  return (
    <Card
      id="health"
      title="Data health"
      sub="Jupiter quote recorder on AWS · target ≥ 99.5% (gate G1)"
      stale={overview.refreshing && !!overview.data}
      actions={<button className="iconbtn" onClick={() => setTable((t) => !t)}>{table ? "Show chart" : "Show table"}</button>}
    >
      <ErrorBanner what="health" error={overview.error} />
      <div className="tiles">
        <Tile label="Recorder" status={<Status level={lvl} label={lbl} />} value={fmtAge(r.last_cycle_age_s)}
          meta={r.last_cycle ? `last cycle ${r.last_cycle.recorded}/${r.last_cycle.expected} readings` : undefined} />
        <Tile label="Cycles on time, 24 h" status={<Status level={coverageLevel(r.cycle_coverage_24h)} label={r.cycle_coverage_24h != null && r.cycle_coverage_24h >= 0.995 ? "On target" : "Gaps"} />}
          value={fmtPct(r.cycle_coverage_24h)} meta={`${r.cycles_24h.toLocaleString()} of ${r.cycles_expected_24h.toLocaleString()} minutes`} />
        <Tile label="Readings complete, 24 h" status={<Status level={coverageLevel(r.reading_coverage_24h)} label={r.reading_coverage_24h != null && r.reading_coverage_24h >= 0.995 ? "On target" : "Missing readings"} />}
          value={fmtPct(r.reading_coverage_24h)} meta={`${r.readings_24h.toLocaleString()} of ${r.readings_expected_24h.toLocaleString()}`} />
        <Tile label="Listings archive" status={<Status level={o.announcements.service === "active" ? "good" : "neutral"} label={o.announcements.service === "active" ? "Collecting" : `Collector ${o.announcements.service}`} />}
          value={o.announcements.count.toLocaleString()} meta={`last checked ${fmtAge(lastSeen)}`} />
        <Tile label="Server" value={o.host.mem_available_mb != null ? `${o.host.mem_available_mb} MB free` : "—"}
          meta={`disk ${o.host.disk_used_gb}/${o.host.disk_total_gb} GB · data ${o.host.data_mb ?? "—"} MB · load ${o.host.load_1m}`} />
      </div>
      <div style={{ marginTop: 18 }}>
        <div className="sub muted" style={{ marginBottom: 6 }}>Cycles recorded per hour, last 24 h (60 possible)</div>
        <ErrorBanner what="coverage" error={coverage.error} />
        {coverage.data ? (table ? <CoverageTable hours={coverage.data} /> : <CoverageChart hours={coverage.data} />) : <p className="muted">Loading…</p>}
      </div>
    </Card>
  );
}

// --- H9 paper test ----------------------------------------------------------

const fmtDay = (iso: string) =>
  new Date(iso).toLocaleDateString("en-GB", { weekday: "short", day: "numeric", month: "short", timeZone: "UTC" });

type Started = Extract<H9, { started: true }>;

function h9RunLevel(d: Started): [Level, string] {
  if (d.timer === "failed" || d.timer === "inactive") return ["critical", "Timer stopped"];
  if (new Date(d.last_run) >= new Date(d.end)) return ["neutral", "Finished"];
  const age = ageOf(d.last_run) ?? 0;
  if (age < 80 * 60) return ["good", "Running"];
  if (age < 3 * 3600) return ["warning", "Late"];
  return ["critical", "Not running"];
}

const signClass = (v: number | null) => (v == null || Math.abs(v) < 0.005 ? "" : v > 0 ? "delta-up" : "delta-down");

function TokenRow({ t }: { t: H9Token }) {
  // a short loses when the price rises, so the move is coloured by its effect on P&L, and the sign stays visible
  const moveEffect = t.move == null ? null : t.side === "short" ? -t.move : t.move;
  const nearStop = t.to_stop != null && t.to_stop < 0.1;
  return (
    <tr>
      <td><strong>{t.coin}</strong></td>
      <td className="secondary">{t.side === "closed" ? "closed" : t.side}</td>
      <td className="num">{t.side === "closed" ? "—" : fmtUsd(t.notional, 0)}</td>
      <td className="num">{t.entry != null ? fmtPrice(t.entry) : "—"}</td>
      <td className="num">{t.mark != null ? fmtPrice(t.mark) : "—"}</td>
      <td className={`num ${signClass(moveEffect)}`}>{fmtSignedPct(t.move)}</td>
      <td className="num">{t.stop != null ? fmtPrice(t.stop) : "—"}</td>
      <td className="num">{t.to_stop == null ? "—" : nearStop ? <Status level="warning" label={fmtPct(t.to_stop)} /> : fmtPct(t.to_stop)}</td>
      <td className={`num ${signClass(t.unrealized)}`}>{fmtSignedUsd(t.unrealized)}</td>
      <td className={`num ${signClass(t.booked)}`}>{fmtSignedUsd(t.booked)}</td>
      <td className={`num ${signClass(t.total)}`}><strong>{fmtSignedUsd(t.total)}</strong></td>
    </tr>
  );
}

export function PaperTest({ h9 }: { h9: Poll<H9> }) {
  const d = h9.data;
  const title = "H9 paper test";
  const sub = "short Solana tokens, long SOL · public Hyperliquid prices · paper money, no orders";
  if (!d || !d.started) {
    return (
      <Card id="paper" title={title} sub={sub}>
        <ErrorBanner what="the H9 paper test" error={h9.error} />
        {!d ? !h9.error && <p className="muted">Loading…</p> : <p className="muted">No hourly run yet (timer {d.timer}).</p>}
      </Card>
    );
  }
  const c = d.criteria;
  const [lvl, lbl] = h9RunLevel(d);
  const runShare = c.runs / c.runs_due;
  const weekShare = c.weeks_done ? c.weeks_up / c.weeks_done : null;
  const daysLeft = Math.max(0, Math.ceil((new Date(d.end).getTime() - Date.now()) / 86_400_000));
  return (
    <Card id="paper" title={title} sub={`${sub} · verdict ${fmtDay(d.end)} 2027`} stale={h9.refreshing && !!d}>
      <ErrorBanner what="the H9 paper test" error={h9.error} />
      <div className="tiles">
        <Tile label="Paper equity" status={<Status level={lvl} label={lbl} />} value={fmtUsd(d.equity)}
          meta={`start ${fmtUsd(d.start_equity, 0)} · hourly mark ${d.last_run.slice(11, 16)} UTC${d.live_equity != null ? ` · live ≈ ${fmtUsd(d.live_equity)}` : ""}`} />
        <Tile label="1 · Net return vs USDC 5%" status={<Status level={c.net_return > c.usdc_return ? "good" : "warning"} label={c.net_return > c.usdc_return ? "Ahead of USDC" : "Behind USDC"} />}
          value={fmtSignedPct(c.net_return, 2)} meta={`USDC would be ${fmtSignedPct(c.usdc_return, 2)} · after costs and funding`} />
        <Tile label="2 · Max drawdown"
          status={<Status level={c.max_dd > c.max_dd_limit ? "critical" : c.max_dd > c.max_dd_limit * 0.67 ? "warning" : "good"} label={c.max_dd > c.max_dd_limit ? "Limit broken" : c.max_dd > c.max_dd_limit * 0.67 ? "Near limit" : "Within limit"} />}
          value={fmtPct(c.max_dd)} meta={`now ${fmtPct(c.dd_now)} below peak · limit ${fmtPct(c.max_dd_limit, 0)}`} />
        <Tile label="3 · Weeks positive"
          status={<Status level={weekShare == null ? "neutral" : weekShare >= c.weeks_up_min ? "good" : "warning"} label={weekShare == null ? "No full week yet" : weekShare >= c.weeks_up_min ? "On track" : "Below 55%"} />}
          value={c.weeks_done ? `${c.weeks_up} of ${c.weeks_done}` : "—"} meta={`need ≥ ${fmtPct(c.weeks_up_min, 0)} of the full Monday-to-Monday weeks`} />
        <Tile label="4 · Largest token share of profit"
          status={<Status level={c.top_share == null ? "neutral" : c.top_share <= c.top_share_limit ? "good" : "warning"} label={c.top_share == null ? "No profit yet" : c.top_share <= c.top_share_limit ? "Spread out" : "Too concentrated"} />}
          value={c.top_share == null ? "—" : fmtPct(c.top_share, 0)} meta={c.top_token ? `${c.top_token} · limit ${fmtPct(c.top_share_limit, 0)}` : `checked once there is a profit · limit ${fmtPct(c.top_share_limit, 0)}`} />
        <Tile label="5 · Hourly runs completed"
          status={<Status level={runShare >= c.runs_min ? "good" : "warning"} label={runShare >= c.runs_min ? "On target" : "Missed runs"} />}
          value={`${c.runs.toLocaleString()} of ${c.runs_due.toLocaleString()}`} meta={`${fmtPct(runShare)} · need ≥ ${fmtPct(c.runs_min, 0)} · ${c.runs_total.toLocaleString()} in all`} />
      </div>
      <ul className="factline">
        <li>Next run <strong>{d.next_run.slice(11, 16)} UTC</strong></li>
        <li>Next weekly rebalance <strong>{d.next_rebalance ? `${fmtDay(d.next_rebalance)} ${d.next_rebalance.slice(11, 16)} UTC` : "none (window over)"}</strong></li>
        <li>Shorts <strong>{d.n_short}</strong> · gross <strong>{fmtUsd(d.gross, 0)}</strong></li>
        <li>Drawdown brake <strong>{d.brake_until ? `on until ${fmtDay(d.brake_until)}` : "off"}</strong></li>
        <li>Blocked after a stop <strong>{d.blacklist.length ? d.blacklist.map((b) => `${b.coin} until ${fmtDay(b.until)}`).join(", ") : "none"}</strong></li>
        <li>Verdict in <strong>{daysLeft} days</strong></li>
      </ul>
      <div style={{ marginTop: 18 }}>
        <EquityChart points={d.series} start={d.start} startEquity={d.start_equity} apr={d.usdc_apr} />
      </div>
      <div style={{ marginTop: 18 }}>
        <div className="sub muted" style={{ marginBottom: 6 }}>Positions and profit by token · stop closes a short at +30% and blocks it for 14 days</div>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Token</th><th>Side</th><th className="num">Size</th><th className="num">Entry</th><th className="num">Now</th>
                <th className="num">Move</th><th className="num">Stop at</th><th className="num">Room to stop</th>
                <th className="num">Unrealized</th><th className="num">Booked</th><th className="num">Total P&amp;L</th>
              </tr>
            </thead>
            <tbody>{d.tokens.map((t) => <TokenRow key={t.coin} t={t} />)}</tbody>
          </table>
        </div>
        <p className="muted footnote">Booked = closed profit + funding − trading costs (10 bps per side). Now and unrealized use live Hyperliquid mid prices; the official numbers are the hourly marks above.</p>
      </div>
      <div className="two-col">
        <div>
          <div className="sub muted" style={{ marginBottom: 6 }}>Weekly results (criterion 3)</div>
          {d.weeks.length === 0 ? <p className="muted">The first full week starts {fmtDay(d.next_rebalance ?? d.start)}.</p> : (
            <div className="table-wrap">
              <table>
                <thead><tr><th>Week starting</th><th className="num">Return</th><th>State</th></tr></thead>
                <tbody>
                  {d.weeks.slice().reverse().map((w) => (
                    <tr key={w.week}>
                      <td>{fmtDay(`${w.week}T00:00:00Z`)}</td>
                      <td className={`num ${signClass(w.return)}`}>{fmtSignedPct(w.return, 2)}</td>
                      <td className="secondary">{w.complete ? (w.return > 0 ? "positive" : "not positive") : "in progress"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
        <div>
          <div className="sub muted" style={{ marginBottom: 6 }}>Engine events (rebalances, stops, brake)</div>
          {d.events.length === 0 ? <p className="muted">None yet.</p> : (
            <ul className="events">
              {d.events.map((e) => (
                <li key={e.hour}><span className="num muted">{fmtTimeUtc(e.hour)}</span> {e.note}</li>
              ))}
            </ul>
          )}
        </div>
      </div>
    </Card>
  );
}

// --- bot --------------------------------------------------------------------

export function Bot({ overview }: { overview: Poll<Overview> }) {
  const b = overview.data?.bot;
  return (
    <Card id="bot" title="Trading bot" sub="paper mode only · no wallet connected">
      {b ? (
        <div className="tiles">
          <Tile label="State" status={<Status level="neutral" label="Not running" />} value="—" meta={b.reason} />
          <Tile label="Paper P&L" value="—" meta="Shown once the paper bot runs. Measured in SOL and USD, against staked SOL." />
          <Tile label="Controls" value="—" meta="Pause, kill switch and trade approvals arrive in step 2, after a strategy passes." />
        </div>
      ) : <p className="muted">Loading…</p>}
    </Card>
  );
}

// --- markets ----------------------------------------------------------------

function costLevel(m: Market): [Level, string] {
  const k1 = m.sizes["1000"]?.roundtrip_bps;
  const k10 = m.sizes["10000"]?.roundtrip_bps;
  if (k1 == null) return ["neutral", "No quote"];
  if (k1 > COST_LIMIT_BPS) return ["critical", "Too costly"];
  if (k10 != null && k10 > COST_LIMIT_BPS) return ["warning", "$1k only"];
  return ["good", "OK to $10k"];
}

const bps = (v: number) => `${v.toFixed(0)} bps`;
const costCell = (v: number) => (v < 0 ? `${bps(v)} · crossed` : bps(v));
const CROSSED_NOTE = "Negative means the buy and sell quotes crossed at that moment; usually a stale quote, not a free trade.";

export function MarketsSection({ markets }: { markets: Poll<Markets> }) {
  const d = markets.data;
  return (
    <Card id="markets" title="Markets" sub={`live Jupiter V2 quotes · round trip = buy + sell at the same size, median of the last 3 readings · plan limit ${COST_LIMIT_BPS} bps`} stale={markets.refreshing && !!d}>
      <ErrorBanner what="markets" error={markets.error} />
      {!d ? <p className="muted">Loading…</p> : (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Pair</th>
                <th className="num">Price</th>
                <th className="num">24 h</th>
                <th>Price, 24 h</th>
                <th className="num">Round trip $1k</th>
                <th className="num">Round trip $10k</th>
                <th>Cost at $1k, 24 h</th>
                <th>Plan limit</th>
                <th className="num">Updated</th>
              </tr>
            </thead>
            <tbody>
              {d.markets.map((m) => {
                const [lvl, lbl] = costLevel(m);
                const k1 = m.sizes["1000"];
                const k10 = m.sizes["10000"];
                return (
                  <tr key={m.mint}>
                    <td><strong>{m.symbol}</strong><span className="muted">/{m.pair.split("/")[1]}</span></td>
                    <td className="num">{fmtPrice(m.price_usd)}</td>
                    <td className={`num ${m.price_change_24h == null ? "" : m.price_change_24h >= 0 ? "delta-up" : "delta-down"}`}>{fmtSignedPct(m.price_change_24h)}</td>
                    <td><Sparkline points={m.price_series} format={fmtPrice} label={`${m.symbol} price, last 24 hours`} /></td>
                    <td className="num" title={k1 ? `24 h median ${bps(k1.median_24h_bps)} · fee ${k1.fee_bps ?? "?"} bps · ${k1.router ?? ""}${k1.roundtrip_bps < 0 ? ` · ${CROSSED_NOTE}` : ""}` : undefined}>{k1 ? costCell(k1.roundtrip_bps) : "—"}</td>
                    <td className="num" title={k10 ? `24 h median ${bps(k10.median_24h_bps)} · fee ${k10.fee_bps ?? "?"} bps · ${k10.router ?? ""}${k10.roundtrip_bps < 0 ? ` · ${CROSSED_NOTE}` : ""}` : undefined}>{k10 ? costCell(k10.roundtrip_bps) : "—"}</td>
                    <td><Sparkline points={m.cost_series_1k} format={bps} label={`${m.symbol} round-trip cost at $1k, last 24 hours`} /></td>
                    <td><Status level={lvl} label={lbl} /></td>
                    <td className="num muted">{fmtAge(ageOf(k1?.at ?? m.price_at))}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </Card>
  );
}

// --- research ---------------------------------------------------------------

export function ResearchSection({ research }: { research: Poll<Research> }) {
  const d = research.data;
  if (!d) return <Card id="research" title="Research"><ErrorBanner what="research" error={research.error} />{!research.error && <p className="muted">Loading…</p>}</Card>;
  const s = d.stop_rule;
  const totalDays = 98; // 25 Oct 2026 → 31 Jan 2027, fixed when the rule was set
  const items = [...d.items].sort((a, b) => (a.id ?? "").localeCompare(b.id ?? "", undefined, { numeric: true }));
  return (
    <Card id="research" title="Research" sub="pre-registered kill tests · rules written before each run">
      <ErrorBanner what="research" error={research.error} />
      <div className="stoprule">
        <div>
          <div className="label secondary" style={{ fontSize: 12 }}>Stop rule: days left until {s.deadline}</div>
          <div style={{ fontSize: 22, fontWeight: 600 }}>{s.days_left} days</div>
          <div className="meter" role="meter" aria-valuemin={0} aria-valuemax={totalDays} aria-valuenow={s.days_left} aria-label="Days left before the stop rule applies">
            <span style={{ width: `${Math.max(0, Math.min(100, (s.days_left / totalDays) * 100))}%` }} />
          </div>
        </div>
        <div>
          <div className="label secondary" style={{ fontSize: 12 }}>Ideas tested beyond H1–H2</div>
          <div style={{ fontSize: 22, fontWeight: 600 }}>{s.hypotheses_used} of {s.hypotheses_max}</div>
          <div className="meter" role="meter" aria-valuemin={0} aria-valuemax={s.hypotheses_max} aria-valuenow={s.hypotheses_used} aria-label="Hypotheses used">
            <span style={{ width: `${(s.hypotheses_used / s.hypotheses_max) * 100}%` }} />
          </div>
        </div>
        <div>
          <div className="label secondary" style={{ fontSize: 12 }}>Passed so far</div>
          <div style={{ fontSize: 22, fontWeight: 600 }}>{s.passed.length ? s.passed.join(", ") : "none"}</div>
          <div className="muted" style={{ fontSize: 12 }}>A pass unlocks paper trading of that rule.</div>
        </div>
      </div>
      <div className="research-grid">
        {items.map((h) => (
          <article className="hyp" key={h.file}>
            <span className="hid">{h.id ?? "—"} · registered {h.registered ?? "?"}</span>
            <h3>{h.title}</h3>
            <Status
              level={h.verdict === "PASS" ? "good" : h.verdict === "FAIL" ? "critical" : "neutral"}
              label={h.verdict === "PASS" ? "Passed" : h.verdict === "FAIL" ? `Failed${h.detail ? ` · ${h.detail}` : ""}` : h.verdict === "RUNNING" ? "Running forward test" : "Not run yet"}
            />
            {h.notes.length > 0 && <ul>{h.notes.slice(0, 2).map((n, i) => <li key={i}>{n}</li>)}</ul>}
          </article>
        ))}
      </div>
    </Card>
  );
}

// --- listings ---------------------------------------------------------------

const TYPE_LABEL: Record<string, string> = {
  binance_spot_listing: "Spot listing",
  binance_futures_listing: "Futures listing",
  binance_futures_premarket: "Futures pre-market",
  binance_alpha: "Alpha",
  upbit_new_listing: "New listing",
  upbit_market_added: "Market added",
  upbit_market_opened: "Market opened",
  upbit_market_removed: "Market removed",
  upbit_delisting: "Delisting",
  upbit_warning: "Warning",
};

function safeUrl(url: string | null): string | null {
  if (!url) return null;
  try {
    const u = new URL(url);
    return u.protocol === "https:" && /(^|\.)(binance\.com|upbit\.com)$/.test(u.hostname) ? u.toString() : null;
  } catch {
    return null;
  }
}

export function Listings({ announcements }: { announcements: Poll<Announcements> }) {
  const [src, setSrc] = useState<"all" | "binance" | "upbit">("all");
  const d = announcements.data;
  const items = d?.items.filter((i) => src === "all" || i.source === src) ?? [];
  return (
    <Card
      id="listings"
      title="Exchange listings"
      sub="Binance and Upbit announcements · parsed by rules · source for listing alerts"
      stale={announcements.refreshing && !!d}
      actions={
        <div className="seg" role="group" aria-label="Exchange">
          {(["all", "binance", "upbit"] as const).map((s) => (
            <button key={s} aria-pressed={src === s} onClick={() => setSrc(s)}>{s === "all" ? "All" : s === "binance" ? "Binance" : "Upbit"}</button>
          ))}
        </div>
      }
    >
      <ErrorBanner what="listings" error={announcements.error} />
      {!d ? <p className="muted">Loading…</p> : (
        <div className="table-wrap">
          <table>
            <thead>
              <tr><th>Published (UTC)</th><th>Exchange</th><th>Type</th><th>Tickers</th><th>Announcement</th></tr>
            </thead>
            <tbody>
              {items.slice(0, 40).map((a) => {
                const href = safeUrl(a.url);
                return (
                  <tr key={`${a.source}-${a.published_at}-${a.title}`}>
                    <td className="num" style={{ textAlign: "left" }}>{fmtTimeUtc(a.published_at)}</td>
                    <td>{a.source === "binance" ? "Binance" : "Upbit"}</td>
                    <td className="secondary">{TYPE_LABEL[a.event_type] ?? a.event_type}</td>
                    <td className="mono">{a.tickers.join(", ") || "—"}</td>
                    <td>{href ? <a href={href} target="_blank" rel="noopener noreferrer">{a.title}</a> : a.title}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </Card>
  );
}
