import { Fragment, useEffect, useState } from "react";
import type { BenchPointsResponse } from "../types";
import { api } from "../api";

export function BenchPointsTab({ leagueId }: { leagueId: number }) {
  const [data, setData] = useState<BenchPointsResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [expanded, setExpanded] = useState<number | null>(null);

  useEffect(() => {
    let ignore = false;
    api
      .getBenchPoints(leagueId)
      .then((res) => {
        if (!ignore) setData(res);
      })
      .catch((e) => {
        if (!ignore) setError(e.message);
      });
    return () => {
      ignore = true;
    };
  }, [leagueId]);

  if (error) return <p className="error">{error}</p>;
  if (!data) return <p>Reading past weeks from ESPN...</p>;

  if (data.weeks_counted === 0) {
    return (
      <div className="panel">
        <h2>Points Left on the Bench</h2>
        <p>No completed weeks to score yet. This fills in once your league has played a week.</p>
      </div>
    );
  }

  return (
    <div className="panel">
      <h2>Points Left on the Bench</h2>
      <p className="hint">
        Each past week's actual starting lineup scored against the best lineup that same roster could have
        fielded. Click a week to see the specific swaps.
      </p>

      <div className="trade-builder">
        <Stat label="Left on bench, all season" value={data.total_left_on_bench} emphasis />
        <Stat label="Per week" value={data.average_left_on_bench} />
        <Stat label="You scored" value={data.total_actual} />
        <Stat label="Best possible" value={data.total_optimal} />
      </div>

      <p className="hint">
        {data.perfect_weeks} of {data.weeks_counted} weeks were perfectly optimized
        {data.worst_week
          ? `. Worst week was week ${data.worst_week.week}, leaving ${data.worst_week.left_on_bench} points behind.`
          : "."}
      </p>

      <div className="table-scroll">
        <table>
          <thead>
            <tr>
              <th>Week</th>
              <th className="num">Started</th>
              <th className="num">Best possible</th>
              <th className="num">Left on bench</th>
            </tr>
          </thead>
          <tbody>
            {data.weeks.map((week) => (
              <Fragment key={week.week}>
                <tr
                  onClick={() => setExpanded(expanded === week.week ? null : week.week)}
                  style={{ cursor: week.missed.length > 0 ? "pointer" : "default" }}
                  className={week.left_on_bench > 0 ? "swap-row" : ""}
                >
                  <td>
                    {week.missed.length > 0 ? (expanded === week.week ? "▾ " : "▸ ") : ""}
                    Week {week.week}
                  </td>
                  <td className="num">{week.actual_points}</td>
                  <td className="num">{week.optimal_points}</td>
                  <td className="num">{week.left_on_bench > 0 ? `-${week.left_on_bench}` : "optimal"}</td>
                </tr>
                {expanded === week.week &&
                  week.missed.map((miss, i) => (
                    <tr key={`${week.week}-miss-${i}`} className="bench-row">
                      <td></td>
                      <td colSpan={3} className="hint">
                        {miss.slot}: started {miss.started.name} ({miss.started.points}) instead of{" "}
                        {miss.should_have_started.name} ({miss.should_have_started.points}) &mdash; {miss.points_missed}{" "}
                        points
                      </td>
                    </tr>
                  ))}
              </Fragment>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function Stat({ label, value, emphasis }: { label: string; value: number; emphasis?: boolean }) {
  return (
    <div className="trade-side" style={{ flex: "1 1 140px", minWidth: "140px" }}>
      <div className="hint">{label}</div>
      <div style={{ fontSize: emphasis ? "1.6rem" : "1.2rem", fontWeight: 600 }}>{value}</div>
    </div>
  );
}
