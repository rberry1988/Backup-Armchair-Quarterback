import { useEffect, useMemo, useState } from "react";
import type { StartSitResponse, StartSitRow } from "../types";
import { api } from "../api";
import { MatchupTag } from "./MatchupTag";
import { InjuryBadge } from "./InjuryBadge";
import { formatPoints } from "../formatPoints";
import { starterSlotRank } from "../lineupSlotOrder";
import { matchupDetail } from "../matchupDetail";

// Backend returns lineup rows in a "most-constrained slot first" solver
// order, not a display order — same QB/RB/RB/WR/WR/TE/FLEX/D/K ordering
// as the Roster tab, so a league's starters read the same in both places.
function orderedLineup(lineup: StartSitRow[]): StartSitRow[] {
  return [...lineup].sort((a, b) => {
    const rankDiff = starterSlotRank(a.slot) - starterSlotRank(b.slot);
    if (rankDiff !== 0) return rankDiff;
    return (b.current_starter.projected_points ?? -Infinity) - (a.current_starter.projected_points ?? -Infinity);
  });
}

/** What to say when there's no opponent to rate. A missing matchup is
 * nearly always a bye — the team simply isn't in this week's schedule —
 * but it's also what you get before a league has ever been synced with
 * schedule data, so the two are distinguished by whether a projection
 * exists at all rather than asserted blindly. */
function noMatchupNote(row: StartSitRow): string {
  if (row.current_starter.projected_points == null) return "On bye this week.";
  return "No opponent data for this team yet — re-sync to pull the schedule.";
}

export function StartSitTab({ leagueId }: { leagueId: number }) {
  const [data, setData] = useState<StartSitResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api
      .getStartSit(leagueId)
      .then(setData)
      .catch((e) => setError(e.message));
  }, [leagueId]);

  const lineup = useMemo(() => (data ? orderedLineup(data.lineup) : []), [data]);

  if (error) return <p className="error">{error}</p>;
  if (!data) return <p>Loading...</p>;

  return (
    <div className="panel">
      <h2>
        Start / Sit &mdash; Week {data.week} ({data.swaps_recommended} suggested swap
        {data.swaps_recommended === 1 ? "" : "s"})
      </h2>
      <div className="table-scroll">
        <table>
          <thead>
            <tr>
              <th>Slot</th>
              <th>Currently Starting</th>
              <th className="num">Proj.</th>
              <th>Matchup</th>
              <th>Why</th>
            </tr>
          </thead>
          <tbody>
            {/* Keyed by position too: most leagues start two RBs or three WRs,
                so slot_id alone repeats across rows. */}
            {lineup.map((row, i) => (
              <tr key={`${row.slot_id}-${i}`} className={row.swap_recommended ? "swap-row" : ""}>
                <td>{row.slot}</td>
                <td>
                  {row.current_starter.name}
                  <InjuryBadge status={row.current_starter.injury_status} />
                  {/* The swap suggestion lives here now that it has no
                      column of its own — it belongs next to the player it
                      replaces, and only appears on the rows that need it. */}
                  {row.swap_recommended && (
                    <div className="swap-note">
                      &rarr; Start <strong>{row.recommended_starter.name}</strong> instead
                      {row.reason ? ` (${row.reason})` : ""}
                    </div>
                  )}
                </td>
                <td className="num">{formatPoints(row.current_starter.projected_points)}</td>
                <td>
                  <MatchupTag matchup={row.current_starter.matchup} />
                </td>
                <td className="matchup-detail">{matchupDetail(row.current_starter.matchup) ?? noMatchupNote(row)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
