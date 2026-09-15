import { useEffect, useState } from "react";
import type { ExpertRankingGroup, ExpertRankingPlayer, ExpertRankingsResponse } from "../types";
import { api } from "../api";
import { PositionTag } from "./PositionTag";

const POSITIONS = ["QB", "RB", "WR", "TE", "K", "DST"];

export function ExpertRankingsTab({ leagueId }: { leagueId: number }) {
  const [data, setData] = useState<ExpertRankingsResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [period, setPeriod] = useState<"ros" | "weekly">("ros");

  useEffect(() => {
    api
      .getExpertRankings(leagueId)
      .then(setData)
      .catch((e) => setError(e.message));
  }, [leagueId]);

  if (error) return <p className="error">{error}</p>;
  if (!data) return <p>Loading...</p>;

  if (!data.available) {
    return (
      <div className="panel">
        <h2>Expert Consensus Rankings</h2>
        <p>
          Not configured. Set <code>FANTASYPROS_API_KEY</code> in <code>backend/.env</code> and re-sync your
          league to see FantasyPros' expert consensus rankings here.
        </p>
      </div>
    );
  }

  const groups: ExpertRankingGroup = (period === "ros" ? data.ros : data.weekly) ?? {};

  return (
    <div className="panel">
      <h2>Expert Consensus Rankings</h2>
      <p className="hint">
        FantasyPros' expert consensus rankings ({data.scoring}), week {data.week}. A free API key only returns the
        top 10 per list, so this covers elite/startable players, not full rosters or waiver-wire depth.
      </p>

      <div className="tabs" style={{ marginBottom: "1rem" }}>
        <button className={period === "ros" ? "active" : ""} onClick={() => setPeriod("ros")}>
          Rest of Season
        </button>
        <button className={period === "weekly" ? "active" : ""} onClick={() => setPeriod("weekly")}>
          This Week
        </button>
      </div>

      <ExpertGroupTable title="Overall" players={groups.overall ?? []} />
      {POSITIONS.map((pos) => (
        <ExpertGroupTable key={pos} title={pos} players={groups[pos] ?? []} />
      ))}
    </div>
  );
}

function ExpertGroupTable({ title, players }: { title: string; players: ExpertRankingPlayer[] }) {
  if (!players || players.length === 0) return null;
  return (
    <div className="waiver-group">
      <h3>{title}</h3>
      <div className="table-scroll">
        <table>
          <thead>
            <tr>
              <th className="num">Rank</th>
              <th>Player</th>
              <th>Pos</th>
              <th>Team</th>
              <th>Pos Rank</th>
              <th>Expert Range</th>
            </tr>
          </thead>
          <tbody>
            {players.map((p) => (
              <tr key={p.fantasypros_id}>
                <td className="num">{p.ecr_rank}</td>
                <td>
                  <a href={p.page_url} target="_blank" rel="noreferrer">
                    {p.name}
                  </a>
                </td>
                <td>
                  <PositionTag position={p.position} />
                </td>
                <td>{p.team}</td>
                <td>{p.pos_rank}</td>
                <td className="hint">
                  {p.rank_min ?? "-"}&ndash;{p.rank_max ?? "-"}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
