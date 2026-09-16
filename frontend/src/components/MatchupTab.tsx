import { useEffect, useState } from "react";
import type { MatchupLineupRow, MatchupPreviewResponse, MatchupSide } from "../types";
import { api } from "../api";
import { formatPoints } from "../formatPoints";
import { MatchupTag } from "./MatchupTag";
import { InjuryBadge } from "./InjuryBadge";
import { starterSlotRank } from "../lineupSlotOrder";

/** Same QB/RB/WR/TE/FLEX/D/K ordering as every other tab, so the two
 * lineups line up row-for-row and can be read across. */
function ordered(lineup: MatchupLineupRow[]): MatchupLineupRow[] {
  return [...lineup].sort((a, b) => {
    const rank = starterSlotRank(a.slot) - starterSlotRank(b.slot);
    if (rank !== 0) return rank;
    return (b.projected_points ?? -Infinity) - (a.projected_points ?? -Infinity);
  });
}

function SideColumn({ side, label }: { side: MatchupSide; label: string }) {
  return (
    <div className="matchup-side">
      <h3>
        {side.name} <span className="hint">{side.record}</span>
      </h3>
      <p className="matchup-total">
        {formatPoints(side.projected)} <span className="hint">projected &middot; {label}</span>
      </p>
      <div className="table-scroll">
        <table>
          <thead>
            <tr>
              <th>Slot</th>
              <th>Player</th>
              <th className="num">Proj.</th>
              <th>Matchup</th>
            </tr>
          </thead>
          <tbody>
            {ordered(side.lineup).map((row, i) => (
              <tr key={`${row.slot_id}-${i}`}>
                <td>{row.slot}</td>
                <td>
                  {row.name}
                  <InjuryBadge status={row.injury_status} />
                </td>
                <td className="num">{formatPoints(row.projected_points)}</td>
                <td>
                  <MatchupTag matchup={row.matchup} />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

export function MatchupTab({ leagueId }: { leagueId: number }) {
  const [data, setData] = useState<MatchupPreviewResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let ignore = false;
    api
      .getMatchupPreview(leagueId)
      .then((d) => {
        if (!ignore) setData(d);
      })
      .catch((e) => {
        if (!ignore) setError(e.message);
      });
    return () => {
      ignore = true;
    };
  }, [leagueId]);

  if (error) return <p className="error">{error}</p>;
  if (!data) return <p>Loading...</p>;

  if (!data.opponent) {
    return (
      <div className="panel">
        <h2>This Week's Matchup</h2>
        <p>
          {data.schedule_available
            ? "You don't have an opponent this week — that's a bye in your league's schedule."
            : "No head-to-head schedule yet. Sync this league again to pull it from ESPN."}
        </p>
      </div>
    );
  }

  const margin = data.margin ?? 0;
  const winPct = data.win_probability ?? 50;
  const favored = margin > 0;
  const swing = data.biggest_swing;

  return (
    <div className="panel">
      <h2>
        Week {data.week}: {data.me.name} vs {data.opponent.name}
      </h2>

      <div className="matchup-verdict">
        <div className={`win-prob ${favored ? "win-prob-good" : "win-prob-bad"}`}>{winPct}%</div>
        <div>
          <p className="verdict">
            {favored ? "Favored by" : "Trailing by"} {formatPoints(Math.abs(margin))} projected points
          </p>
          <p className="hint">
            {/* The margin is the real number; say plainly what turns it into
                a percentage rather than implying more precision than exists. */}
            Win probability assumes a typical weekly swing of about {data.stdev_assumed} points per team. Treat it as
            a rough read on how safe the margin is, not a forecast.
          </p>
        </div>
      </div>

      {swing && (
        <p className="matchup-swing">
          Biggest single change available: start <strong>{swing.in}</strong> over <strong>{swing.out}</strong> at{" "}
          {swing.slot} &mdash; worth {formatPoints(swing.gain)} points and takes you to{" "}
          <strong>{swing.win_probability_after}%</strong>.
        </p>
      )}

      <div className="matchup-grid">
        <SideColumn side={data.me} label="you" />
        <SideColumn side={data.opponent} label="them" />
      </div>
    </div>
  );
}
