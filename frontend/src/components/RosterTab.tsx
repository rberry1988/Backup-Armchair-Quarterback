import { useEffect, useMemo, useState } from "react";
import type { PlayerConsistency, RosterPlayer, RosterResponse } from "../types";
import { api } from "../api";
import { TrendTag } from "./TrendTag";
import { PositionTag } from "./PositionTag";
import { InjuryBadge } from "./InjuryBadge";

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

type SortKey = "default" | "name" | "projected_points" | "actual_points" | "percent_owned";

const SORT_COLUMNS: { key: SortKey; label: string; numeric?: boolean }[] = [
  { key: "name", label: "Player" },
  { key: "projected_points", label: "Proj.", numeric: true },
  { key: "actual_points", label: "Actual", numeric: true },
  { key: "percent_owned", label: "% Owned", numeric: true },
];

function sortRoster(roster: RosterPlayer[], key: SortKey, dir: "asc" | "desc"): RosterPlayer[] {
  if (key === "default") return roster;
  const sorted = [...roster].sort((a, b) => {
    if (key === "name") return a.name.localeCompare(b.name);
    const av = a[key] ?? -Infinity;
    const bv = b[key] ?? -Infinity;
    return av - bv;
  });
  return dir === "asc" ? sorted : sorted.reverse();
}

export function RosterTab({ leagueId }: { leagueId: number }) {
  const [data, setData] = useState<RosterResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [sortKey, setSortKey] = useState<SortKey>("default");
  const [sortDir, setSortDir] = useState<"asc" | "desc">("desc");

  useEffect(() => {
    api
      .getRoster(leagueId)
      .then(setData)
      .catch((e) => setError(e.message));
  }, [leagueId]);

  const sortedRoster = useMemo(() => (data ? sortRoster(data.roster, sortKey, sortDir) : []), [data, sortKey, sortDir]);

  if (error) return <p className="error">{error}</p>;
  if (!data) return <p>Loading...</p>;

  function toggleSort(key: SortKey) {
    if (key === sortKey) {
      setSortDir(sortDir === "asc" ? "desc" : "asc");
    } else {
      setSortKey(key);
      setSortDir(key === "name" ? "asc" : "desc");
    }
  }

  return (
    <div className="panel">
      <h2>
        {data.team} &mdash; Week {data.week}
      </h2>
      <p className="hint">Trend columns show the last few played weeks' usage (targets, carries, ...), oldest to newest.</p>
      <div className="table-scroll">
        <table>
          <thead>
            <tr>
              <th>Slot</th>
              {SORT_COLUMNS.map(({ key, label, numeric }) => (
                <th
                  key={key}
                  className={`sortable-th${numeric ? " num" : ""}${sortKey === key ? " active" : ""}`}
                  onClick={() => toggleSort(key)}
                >
                  {label}
                  {sortKey === key ? (sortDir === "asc" ? " ↑" : " ↓") : ""}
                </th>
              ))}
              <th>Pos</th>
              <th>Status</th>
              <th>Floor &ndash; Ceiling</th>
              <th>Usage Trend</th>
            </tr>
          </thead>
          <tbody>
            {sortedRoster.map((p, i) => (
              <tr key={i} className={p.is_starter ? "" : "bench-row"}>
                <td>{p.slot}</td>
                <td>{p.name}</td>
                <td className="num">{p.projected_points ?? "-"}</td>
                <td className="num">{p.actual_points ?? "-"}</td>
                <td className="num">{p.percent_owned.toFixed(1)}%</td>
                <td>
                  <PositionTag position={p.position} />
                </td>
                <td>
                  <InjuryBadge status={p.injury_status} />
                </td>
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
    </div>
  );
}
