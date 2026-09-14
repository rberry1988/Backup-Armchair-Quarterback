import { useEffect, useState } from "react";
import type { StartSitResponse } from "../types";
import { api } from "../api";
import { MatchupTag } from "./MatchupTag";

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
      <table>
        <thead>
          <tr>
            <th>Slot</th>
            <th>Currently Starting</th>
            <th>Proj.</th>
            <th>Matchup</th>
            <th>Recommendation</th>
            <th>Why</th>
          </tr>
        </thead>
        <tbody>
          {data.lineup.map((row) => (
            <tr key={row.slot_id} className={row.swap_recommended ? "swap-row" : ""}>
              <td>{row.slot}</td>
              <td>
                {row.current_starter.name}
                {row.current_starter.injury_status !== "ACTIVE" && (
                  <span className="badge">{row.current_starter.injury_status}</span>
                )}
              </td>
              <td>{row.current_starter.projected_points ?? "-"}</td>
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
  );
}
