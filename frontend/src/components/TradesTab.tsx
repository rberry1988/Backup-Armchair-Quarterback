import { useEffect, useState } from "react";
import type { TradeResponse } from "../types";
import { api } from "../api";

export function TradesTab({ leagueId }: { leagueId: number }) {
  const [data, setData] = useState<TradeResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api
      .getTrades(leagueId)
      .then(setData)
      .catch((e) => setError(e.message));
  }, [leagueId]);

  if (error) return <p className="error">{error}</p>;
  if (!data) return <p>Loading...</p>;

  return (
    <div className="panel">
      <h2>Trade Targets</h2>

      <h3>Your needs</h3>
      {data.needs.length === 0 ? (
        <p>No glaring weak spots &mdash; your starting lineup is at or above league median everywhere.</p>
      ) : (
        <ul>
          {data.needs.map((n) => (
            <li key={n.position}>
              <strong>{n.position}</strong>: {n.my_starting_strength} proj pts vs league median {n.league_median}
            </li>
          ))}
        </ul>
      )}

      <h3>What you can trade away</h3>
      {data.surplus_to_trade.length === 0 ? (
        <p>No standout bench surplus detected.</p>
      ) : (
        <ul>
          {data.surplus_to_trade.map((s) => (
            <li key={s.position}>
              <strong>{s.position}</strong>: deepest bench in the league ({s.my_bench_depth} proj pts on the bench)
            </li>
          ))}
        </ul>
      )}

      <h3>Suggested trade partners</h3>
      {data.suggested_partners.length === 0 ? (
        <p>No clear complementary partner found this week.</p>
      ) : (
        data.suggested_partners.map((p) => (
          <div key={p.team} className="partner-card">
            <h4>{p.team}</h4>
            <p>
              They could send: {p.they_could_send.map((x) => x.position).join(", ")}
              <br />
              They might want: {p.they_might_want.map((x) => x.position).join(", ")}
            </p>
          </div>
        ))
      )}
    </div>
  );
}
