import { useEffect, useRef, useState } from "react";

export type LastCycle = { expected: number; recorded: number; errors: string[] };

export type Overview = {
  server_time: string;
  recorder: {
    service: string;
    first_cycle_at: string | null;
    last_cycle_at?: string;
    last_cycle_age_s?: number;
    last_cycle?: LastCycle;
    cycles_1h: number;
    cycles_expected_1h: number;
    cycle_coverage_1h: number | null;
    reading_coverage_1h: number | null;
    cycles_24h: number;
    cycles_expected_24h: number;
    cycle_coverage_24h: number | null;
    reading_coverage_24h: number | null;
    readings_24h: number;
    readings_expected_24h: number;
  };
  announcements: { service: string; count: number; last_seen_at: string | null; last_published_at?: string | null };
  host: {
    mem_total_mb: number | null;
    mem_available_mb: number | null;
    disk_total_gb: number;
    disk_used_gb: number;
    load_1m: number;
    uptime_s: number | null;
    data_mb: number | null;
  };
  bot: { state: string; mode: string; reason: string };
};

export type CoverageHour = { hour: string; cycles: number; possible: number; recorded: number; expected: number };

export type Point = { t: string; v: number };
export type SizeCost = { roundtrip_bps: number; median_24h_bps: number; at: string; fee_bps: number | null; router: string | null };
export type Market = {
  symbol: string;
  mint: string;
  pair: string;
  price_usd: number | null;
  price_at: string | null;
  price_change_24h: number | null;
  price_series: Point[];
  cost_series_1k: Point[];
  sizes: Record<string, SizeCost>;
  binance_price_usd: number | null;
};
export type Markets = { as_of: string; markets: Market[] };

export type Announcement = {
  source: "binance" | "upbit";
  published_at: string;
  first_seen_at: string;
  title: string;
  url: string | null;
  event_type: string;
  tickers: string[];
};
export type Announcements = { items: Announcement[]; counts_7d: Record<string, number> };

export type ResearchItem = {
  id: string | null;
  file: string;
  title: string;
  registered: string | null;
  verdict: "PASS" | "FAIL" | "PENDING" | "RUNNING";
  detail: string | null;
  notes: string[];
};
export type Research = {
  items: ResearchItem[];
  stop_rule: { deadline: string; days_left: number; hypotheses_used: number; hypotheses_max: number; passed: string[] };
};

export type H9Token = {
  coin: string;
  side: "short" | "long" | "closed";
  qty: number;
  entry: number | null;
  mark: number | null;
  opened_at: string | null;
  notional: number;
  move: number | null;
  stop: number | null;
  to_stop: number | null;
  unrealized: number;
  booked: number;
  total: number;
};
export type H9Week = { week: string; return: number; complete: boolean };
export type H9 =
  | { started: false; timer: string }
  | {
      started: true;
      timer: string;
      start: string;
      end: string;
      last_run: string;
      last_run_at: string;
      next_run: string;
      next_rebalance: string | null;
      start_equity: number;
      usdc_apr: number;
      equity: number;
      live_equity: number | null;
      cash: number;
      gross: number;
      n_short: number;
      series: Point[];
      brake_until: string | null;
      blacklist: { coin: string; until: string }[];
      tokens: H9Token[];
      events: { hour: string; note: string }[];
      weeks: H9Week[];
      criteria: {
        net_return: number;
        usdc_return: number;
        max_dd: number;
        dd_now: number;
        max_dd_limit: number;
        weeks_up: number;
        weeks_done: number;
        weeks_up_min: number;
        top_token: string | null;
        top_share: number | null;
        top_share_limit: number;
        runs: number;
        runs_due: number;
        runs_min: number;
        runs_total: number;
      };
    };

export type Poll<T> = { data: T | null; error: string | null; refreshing: boolean; updatedAt: Date | null };

/** Polls a read-only endpoint. Keeps the previous data while refetching so the layout never jumps. */
export function usePoll<T>(url: string, everyMs: number): Poll<T> {
  const [state, setState] = useState<Poll<T>>({ data: null, error: null, refreshing: true, updatedAt: null });
  const timer = useRef<number | undefined>(undefined);

  useEffect(() => {
    let alive = true;
    const load = async () => {
      setState((s) => ({ ...s, refreshing: true }));
      try {
        const res = await fetch(url, { headers: { Accept: "application/json" } });
        if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
        const data = (await res.json()) as T;
        if (alive) setState({ data, error: null, refreshing: false, updatedAt: new Date() });
      } catch (e) {
        if (alive) setState((s) => ({ ...s, error: e instanceof Error ? e.message : String(e), refreshing: false }));
      }
      if (alive) timer.current = window.setTimeout(load, everyMs);
    };
    load();
    return () => {
      alive = false;
      window.clearTimeout(timer.current);
    };
  }, [url, everyMs]);

  return state;
}

// --- formatting ------------------------------------------------------------

export function fmtAge(seconds: number | undefined | null): string {
  if (seconds == null) return "—";
  if (seconds < 90) return `${Math.round(seconds)}s ago`;
  if (seconds < 5400) return `${Math.round(seconds / 60)} min ago`;
  if (seconds < 172800) return `${Math.round(seconds / 3600)} h ago`;
  return `${Math.round(seconds / 86400)} d ago`;
}

export function ageOf(iso: string | null | undefined, now = Date.now()): number | null {
  return iso ? (now - new Date(iso).getTime()) / 1000 : null;
}

export function fmtPct(x: number | null | undefined, digits = 1): string {
  return x == null ? "—" : `${(x * 100).toFixed(digits)}%`;
}

export function fmtSignedPct(x: number | null | undefined, digits = 1): string {
  if (x == null) return "—";
  const v = Number((x * 100).toFixed(digits)); // sign of the shown value, so a tiny move never reads "−0.0%"
  return `${v > 0 ? "+" : v < 0 ? "−" : ""}${Math.abs(v).toFixed(digits)}%`;
}

/** Prices span 1e-6 (BONK) to 1e2 (SOL); keep 4 significant digits. */
export function fmtPrice(x: number | null | undefined): string {
  if (x == null) return "—";
  if (x >= 1000) return `$${x.toLocaleString("en-US", { maximumFractionDigits: 0 })}`;
  if (x >= 1) return `$${x.toFixed(2)}`;
  return `$${x.toPrecision(4)}`;
}

export function fmtUsd(x: number | null | undefined, digits = 2): string {
  if (x == null) return "—";
  const sign = x < 0 ? "−" : "";
  return `${sign}$${Math.abs(x).toLocaleString("en-US", { minimumFractionDigits: digits, maximumFractionDigits: digits })}`;
}

export function fmtSignedUsd(x: number | null | undefined, digits = 2): string {
  if (x == null) return "—";
  return `${x > 0 ? "+" : ""}${fmtUsd(x, digits)}`;
}

export function fmtTimeUtc(iso: string): string {
  const d = new Date(iso);
  return `${d.toISOString().slice(5, 10)} ${d.toISOString().slice(11, 16)}`;
}
