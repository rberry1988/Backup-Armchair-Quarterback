import { useEffect, useState } from "react";
import type { PlayerConsistency, RosterResponse } from "../types";
import { api } from "../api";
import { TrendTag } from "./TrendTag";

const CONSISTENCY_CLASS: Record<string, string> = {
  steady: "matchup-favorable",
  streaky: "matchup-average",
  "boom/bust": "matchup-tough",
  unrated: "matchup-average",
};

function ConsistencyTag({ consistency }: { consistency: PlayerConsistency | null }) {
  if (!consistency) return <span className="hint">-</span>;
  return (
    <span
      className={`matchup-tag ${CONSISTENCY_CLASS[consistency.label] ?? "matchup-average"}`}
      title={`${consistency.weeks_counted} weeks: avg ${consistency.average}, floor ${consistency.floor}, ceiling ${consistency.ceiling} (boom ${consistency.boom_rate}% / bust ${consistency.bust_rate}%)`}
    >
      {consistency.label} {consistency.floor}&ndash;{consistency.ceiling}
    </span>
  );
}

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
      <p className="hint">Trend columns show the last few played weeks' usage (targets, carries, ...), oldest to newest.</p>
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
            <th>Floor &ndash; Ceiling</th>
            <th>Usage Trend</th>
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
              <td>
                <ConsistencyTag consistency={p.consistency} />
              </td>
              <td>
                <TrendTag trend={p.trend} />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
