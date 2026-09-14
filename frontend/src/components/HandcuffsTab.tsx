import { useEffect, useState } from "react";
import type { HandcuffEntry, HandcuffsResponse } from "../types";
import { api } from "../api";

const STATUS_LABEL: Record<HandcuffEntry["status"], string> = {
  free_agent: "Free agent — grab this",
  mine: "Already on your roster",
  rostered: "Rostered elsewhere",
};

const STATUS_CLASS: Record<HandcuffEntry["status"], string> = {
  free_agent: "grade-A",
  mine: "grade-B",
  rostered: "grade-C",
};

export function HandcuffsTab({ leagueId }: { leagueId: number }) {
  const [data, setData] = useState<HandcuffsResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api
      .getHandcuffs(leagueId)
      .then(setData)
      .catch((e) => setError(e.message));
  }, [leagueId]);

  if (error) return <p className="error">{error}</p>;
  if (!data) return <p>Loading...</p>;

  return (
    <div className="panel">
      <h2>RB Handcuffs</h2>
      <p className="hint">
        For each RB on your roster, the next back on the same NFL team per the inferred depth chart — the player
        most likely to inherit their role if they're hurt.
      </p>

      {data.handcuffs.length === 0 ? (
        <p>No RB handcuffs found. This can happen if your running backs are their team's only synced RB.</p>
      ) : (
        <table>
          <thead>
            <tr>
              <th>Your RB</th>
              <th>Team</th>
              <th>Handcuff</th>
              <th>Status</th>
            </tr>
          </thead>
          <tbody>
            {data.handcuffs.map((h) => (
              <tr key={h.rb.espn_player_id}>
                <td>{h.rb.name}</td>
                <td>{h.rb.pro_team}</td>
                <td>{h.handcuff.name}</td>
                <td>
                  <span className={`grade-badge ${STATUS_CLASS[h.status]}`}>{STATUS_LABEL[h.status]}</span>
                  {h.status === "rostered" && h.handcuff.owner_team_name && (
                    <span className="hint"> ({h.handcuff.owner_team_name})</span>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
