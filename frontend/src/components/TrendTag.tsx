import type { PlayerTrend } from "../types";

const ARROW: Record<string, string> = { up: "↑", down: "↓", flat: "→" };
const TREND_CLASS: Record<string, string> = { up: "trend-up", down: "trend-down", flat: "trend-flat" };

export function TrendTag({ trend }: { trend: PlayerTrend | null }) {
  if (!trend) return <span className="hint">-</span>;
  const entries = Object.values(trend.stats);
  if (entries.length === 0) return <span className="hint">-</span>;

  return (
    <span className="trend-tag-group">
      {entries.map((stat, i) => (
        <span key={i} className={`trend-tag ${stat.trend ? TREND_CLASS[stat.trend] : ""}`}>
          {stat.label} {stat.recent.join("→")}
          {stat.trend && ARROW[stat.trend] ? ` ${ARROW[stat.trend]}` : ""}
        </span>
      ))}
    </span>
  );
}
