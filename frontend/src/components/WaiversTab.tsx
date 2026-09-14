import { useEffect, useState } from "react";
import type { WaiverResponse } from "../types";
import { api } from "../api";
import { MatchupTag } from "./MatchupTag";

export function WaiversTab({ leagueId }: { leagueId: number }) {
  const [data, setData] = useState<WaiverResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api
      .getWaivers(leagueId)
      .then(setData)
      .catch((e) => setError(e.message));
  }, [leagueId]);

  if (error) return <p className="error">{error}</p>;
  if (!data) return <p>Loading...</p>;

  if (data.recommendations.length === 0) {
    return (
      <div className="panel">
        <h2>Waiver Wire</h2>
        <p>No upgrades found on the waiver wire right now &mdash; your roster looks solid.</p>
      </div>
    );
  }

  return (
    <div className="panel">
      <h2>Waiver Wire Targets</h2>
      <p className="hint">
        Suggested FAAB bid is a starting point (% of a 100-point budget), scaled by how much the pickup projects to
        add over your weakest rostered player at that position. Ignore it if your league uses waiver priority
        instead of FAAB.
      </p>
      {data.recommendations.map((rec) => (
        <div key={rec.position} className="waiver-group">
          <h3>{rec.position}</h3>
          <table>
            <thead>
              <tr>
                <th>Add</th>
                <th>Proj.</th>
                <th>Matchup</th>
                <th>% Owned</th>
                <th>Drop</th>
                <th>Net Gain</th>
                <th>Suggested FAAB</th>
              </tr>
            </thead>
            <tbody>
              {rec.suggestions.map((s, i) => (
                <tr key={i}>
                  <td>{s.add.name}</td>
                  <td>{s.add.projected_points ?? "-"}</td>
                  <td>
                    <MatchupTag matchup={s.add.matchup} />
                  </td>
                  <td>{s.add.percent_owned}%</td>
                  <td>{s.drop_candidate ? s.drop_candidate.name : "-"}</td>
                  <td>+{s.point_upgrade}</td>
                  <td>{s.suggested_faab_pct}%</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ))}
    </div>
  );
}
