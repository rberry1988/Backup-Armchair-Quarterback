import { useEffect, useState } from "react";
import type { RosterResponse } from "../types";
import { api } from "../api";

export function RosterTab({ leagueId }: { leagueId: number }) {
  const [data, setData] = useState<RosterResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api
      .getRoster(leagueId)
      .then(setData)
      .catch((e) => setError(e.message));
  }, [leagueId]);

  if (error) return <p className="error">{error}</p>;
  if (!data) return <p>Loading...</p>;

  return (
    <div className="panel">
      <h2>
        {data.team} &mdash; Week {data.week}
      </h2>
      <table>
        <thead>
          <tr>
            <th>Slot</th>
            <th>Player</th>
            <th>Pos</th>
            <th>Proj.</th>
            <th>Actual</th>
            <th>Status</th>
            <th>% Owned</th>
          </tr>
        </thead>
        <tbody>
          {data.roster.map((p, i) => (
            <tr key={i} className={p.is_starter ? "" : "bench-row"}>
              <td>{p.slot}</td>
              <td>{p.name}</td>
              <td>{p.position}</td>
              <td>{p.projected_points ?? "-"}</td>
              <td>{p.actual_points ?? "-"}</td>
              <td>{p.injury_status !== "ACTIVE" ? <span className="badge">{p.injury_status}</span> : "-"}</td>
              <td>{p.percent_owned.toFixed(1)}%</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
