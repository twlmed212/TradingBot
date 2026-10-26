export type Level = "good" | "warning" | "serious" | "critical" | "neutral";

/** Status always ships icon + label; color never carries the meaning alone. */
export function Status({ level, label }: { level: Level; label: string }) {
  return (
    <span className={`status ${level}`}>
      <StatusIcon level={level} />
      <span>{label}</span>
    </span>
  );
}

function StatusIcon({ level }: { level: Level }) {
  const common = { width: 14, height: 14, viewBox: "0 0 16 16", fill: "none", "aria-hidden": true } as const;
  switch (level) {
    case "good":
      return (
        <svg {...common}>
          <circle cx="8" cy="8" r="7" fill="currentColor" />
          <path d="M4.8 8.3l2.1 2.1 4.3-4.6" stroke="#fff" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      );
    case "warning":
    case "serious":
      return (
        <svg {...common}>
          <path d="M8 1.5l7 12.5H1z" fill="currentColor" strokeLinejoin="round" />
          <path d="M8 6v3.6" stroke="#111" strokeWidth="1.6" strokeLinecap="round" />
          <circle cx="8" cy="11.6" r="0.9" fill="#111" />
        </svg>
      );
    case "critical":
      return (
        <svg {...common}>
          <path d="M5.1 1h5.8L15 5.1v5.8L10.9 15H5.1L1 10.9V5.1z" fill="currentColor" />
          <path d="M5.6 5.6l4.8 4.8M10.4 5.6l-4.8 4.8" stroke="#fff" strokeWidth="1.7" strokeLinecap="round" />
        </svg>
      );
    default:
      return (
        <svg {...common}>
          <circle cx="8" cy="8" r="6.2" stroke="currentColor" strokeWidth="1.6" />
          <path d="M5 8h6" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
        </svg>
      );
  }
}
