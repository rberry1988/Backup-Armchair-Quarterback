import type { MatchupContext } from "../types";

const LABEL_CLASS: Record<string, string> = {
  "tough matchup": "matchup-tough",
  "favorable matchup": "matchup-favorable",
  "average matchup": "matchup-average",
};

export function MatchupTag({ matchup }: { matchup: MatchupContext | null }) {
  if (!matchup) return <span className="hint">-</span>;
  return (
    <span className={`matchup-tag ${LABEL_CLASS[matchup.label] ?? ""}`} title={`Defense rank ${matchup.defense_rank}/${matchup.defense_teams_ranked}`}>
      vs {matchup.opponent} · {matchup.label}
    </span>
  );
}
