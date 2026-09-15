import { useEffect, useState } from "react";
import type { StartSitResponse } from "../types";
import { api } from "../api";
import { MatchupTag } from "./MatchupTag";
import { InjuryBadge } from "./InjuryBadge";
import { formatPoints } from "../formatPoints";

export function StartSitTab({ leagueId }: { leagueId: number }) {
  const [data, setData] = useState<StartSitResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api
      .getStartSit(leagueId)
      .then(setData)
      .catch((e) => setError(e.message));
  }, [leagueId]);

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
              <th>Recommendation</th>
              <th>Why</th>
            </tr>
          </thead>
          <tbody>
            {/* Keyed by position too: most leagues start two RBs or three WRs,
                so slot_id alone repeats across rows. */}
            {data.lineup.map((row, i) => (
              <tr key={`${row.slot_id}-${i}`} className={row.swap_recommended ? "swap-row" : ""}>
                <td>{row.slot}</td>
                <td>
                  {row.current_starter.name}
                  <InjuryBadge status={row.current_starter.injury_status} />
                </td>
                <td className="num">{formatPoints(row.current_starter.projected_points)}</td>
                <td>
                  <MatchupTag matchup={row.current_starter.matchup} />
                </td>
                <td>
                  {row.swap_recommended ? (
                    <strong>Start {row.recommended_starter.name} instead</strong>
                  ) : (
                    "Keep starting"
                  )}
                </td>
                <td>{row.reason ?? "-"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
