import { useEffect, useState } from "react";
import { usePoll, type Announcements, type CoverageHour, type H9, type Markets, type Overview, type Research } from "./api";
import { Bot, Health, Listings, MarketsSection, PaperTest, ResearchSection } from "./sections";

type Theme = "system" | "light" | "dark";

function readTheme(): Theme {
  try {
    const t = localStorage.getItem("deskbot-theme");
    return t === "light" || t === "dark" ? t : "system";
  } catch {
    return "system";
  }
}

export function App() {
  const overview = usePoll<Overview>("/api/overview", 15_000);
  const coverage = usePoll<CoverageHour[]>("/api/coverage?hours=24", 60_000);
  const markets = usePoll<Markets>("/api/markets", 30_000);
  const research = usePoll<Research>("/api/research", 120_000);
  const announcements = usePoll<Announcements>("/api/announcements?limit=120", 60_000);
  const h9 = usePoll<H9>("/api/h9", 30_000);
  const [theme, setTheme] = useState<Theme>(readTheme);

  useEffect(() => {
    const root = document.documentElement;
    if (theme === "system") root.removeAttribute("data-theme");
    else root.setAttribute("data-theme", theme);
    try {
      localStorage.setItem("deskbot-theme", theme);
    } catch {
      /* storage unavailable: theme still applies for this visit */
    }
  }, [theme]);

  const next: Record<Theme, Theme> = { system: "light", light: "dark", dark: "system" };
  const updated = overview.updatedAt?.toISOString().slice(11, 19);

  return (
    <>
      <header className="topbar">
        <span className="brand">deskbot console</span>
        <span className="chip">Watch-only</span>
        <span className="chip">Paper</span>
        <nav className="topnav" aria-label="Sections">
          <a href="#health">Health</a>
          <a href="#paper">H9 paper</a>
          <a href="#bot">Bot</a>
          <a href="#markets">Markets</a>
          <a href="#research">Research</a>
          <a href="#listings">Listings</a>
        </nav>
        <span className="spacer" />
        <span className="refresh" aria-live="polite">{updated ? `updated ${updated} UTC` : "connecting…"}</span>
        <button className="iconbtn" onClick={() => setTheme(next[theme])} aria-label={`Theme: ${theme}. Change theme`}>
          Theme: {theme}
        </button>
      </header>
      <main>
        <Health overview={overview} coverage={coverage} />
        <PaperTest h9={h9} />
        <Bot overview={overview} />
        <MarketsSection markets={markets} />
        <ResearchSection research={research} />
        <Listings announcements={announcements} />
      </main>
    </>
  );
}
