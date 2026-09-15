import { useEffect, useState } from "react";
import type { DepthChartEntry, DepthChartsResponse } from "../types";
import { api } from "../api";
import { InjuryBadge } from "./InjuryBadge";

const POSITION_ORDER = ["QB", "RB", "WR", "TE", "K"];

export function DepthChartsTab({ leagueId }: { leagueId: number }) {
  const [data, setData] = useState<DepthChartsResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [team, setTeam] = useState<string | null>(null);

  useEffect(() => {
    api
      .getDepthCharts(leagueId)
      .then((res) => {
        setData(res);
        const teams = Object.keys(res.depth_charts).sort();
        setTeam(teams[0] ?? null);
      })
      .catch((e) => setError(e.message));
  }, [leagueId]);

  if (error) return <p className="error">{error}</p>;
  if (!data) return <p>Loading...</p>;

  const teams = Object.keys(data.depth_charts).sort();
  if (teams.length === 0) {
    return (
      <div className="panel">
        <h2>Depth Charts</h2>
        <p>No synced players yet. Sync your league first.</p>
      </div>
    );
  }

  const byPosition = team ? data.depth_charts[team] ?? {} : {};

  return (
    <div className="panel">
      <h2>Depth Charts</h2>
      <p className="hint">
        Inferred from usage, not an official ESPN depth chart: ranked by nflverse snap % where available, falling
        back to ESPN's percent-started and then projected points for players nflverse hasn't matched yet.
      </p>

      <label>
        Team{" "}
        <select value={team ?? ""} onChange={(e) => setTeam(e.target.value)}>
          {teams.map((t) => (
            <option key={t} value={t}>
              {t}
            </option>
          ))}
        </select>
      </label>

      {POSITION_ORDER.map((pos) => (
        <DepthChartGroup key={pos} title={pos} players={byPosition[pos] ?? []} />
      ))}
    </div>
  );
}

function DepthChartGroup({ title, players }: { title: string; players: DepthChartEntry[] }) {
  if (!players || players.length === 0) return null;
  return (
    <div className="waiver-group">
      <h3>{title}</h3>
      <div className="table-scroll">
        <table>
          <thead>
            <tr>
              <th className="num">Depth</th>
              <th>Player</th>
              <th className="num">Snap %</th>
              <th className="num">Proj</th>
              <th>Status</th>
              <th>Owner</th>
            </tr>
          </thead>
          <tbody>
            {players.map((p) => (
              <tr key={p.espn_player_id}>
                <td className="num">{p.depth_rank}</td>
                <td>{p.name}</td>
                <td className="num">
                  {p.snap_pct != null ? (
                    `${p.snap_pct}%`
                  ) : (
                    <span
                      className="hint"
                      title="No real snap-share data for this player yet — ranked by ESPN's percent-started/projected points instead, a rougher estimate."
                    >
                      est.
                    </span>
                  )}
                </td>
                <td className="num">{p.projected_points ?? "-"}</td>
                <td>
                  <InjuryBadge status={p.injury_status} />
                </td>
                <td className="hint">{p.is_free_agent ? "Free agent" : p.owner_team_name ?? "-"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
