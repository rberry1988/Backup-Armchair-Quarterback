import { useEffect, useState } from "react";
import type { PlayoffOddsResponse } from "../types";
import { api } from "../api";

function oddsClass(odds: number): string {
  if (odds >= 75) return "odds-strong";
  if (odds >= 40) return "odds-live";
  if (odds >= 10) return "odds-slim";
  return "odds-dead";
}

export function PlayoffOddsTab({ leagueId }: { leagueId: number }) {
  const [data, setData] = useState<PlayoffOddsResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let ignore = false;
    api
      .getPlayoffOdds(leagueId)
      .then((d) => {
        if (!ignore) setData(d);
      })
      .catch((e) => {
        if (!ignore) setError(e.message);
      });
    return () => {
      ignore = true;
    };
  }, [leagueId]);

  if (error) return <p className="error">{error}</p>;
  if (!data) return <p>Loading...</p>;

  if (!data.available) {
    return (
      <div className="panel">
        <h2>Playoff Odds</h2>
        <p>
          {data.reason === "no_schedule"
            ? "No head-to-head schedule yet. Sync this league again to pull it from ESPN."
            : "Not enough league data to simulate the rest of the season yet."}
        </p>
      </div>
    );
  }

  const me = data.me;
  const harder = me?.schedule_difficulty != null && me.schedule_difficulty > 0;

  return (
    <div className="panel">
      <h2>Playoff Odds &mdash; Week {data.week}</h2>

      {me && (
        <div className="matchup-verdict">
          <div className={`win-prob ${oddsClass(me.playoff_odds)}`}>{me.playoff_odds}%</div>
          <div>
            <p className="verdict">
              {me.record}, projected to finish {me.projected_wins} wins &mdash; top {data.playoff_teams} make it.
            </p>
            <p className="hint">
              {me.schedule_difficulty != null ? (
                <>
                  Your remaining opponents average {me.remaining_opponent_ppg} points a game,{" "}
                  {harder ? (
                    <>
                      <strong>{Math.abs(me.schedule_difficulty)} above</strong> the league's {data.league_average_ppg}{" "}
                      &mdash; a harder run-in than most.
                    </>
                  ) : (
                    <>
                      <strong>{Math.abs(me.schedule_difficulty)} below</strong> the league's {data.league_average_ppg}{" "}
                      &mdash; an easier run-in than most.
                    </>
                  )}
                </>
              ) : (
                <>No games left to simulate.</>
              )}
            </p>
          </div>
        </div>
      )}

      <p className="hint">
        {/* Say what the number rests on. Early-season odds are built on a
            handful of games and shouldn't be read as firm. */}
        {data.simulations.toLocaleString()} simulations of the {data.weeks_remaining} week
        {data.weeks_remaining === 1 ? "" : "s"} left. Team strength comes from points scored per game, not win-loss
        record &mdash; fantasy records are noisy, and the highest-scoring team in a league is often not the one on
        top.{" "}
        {data.games_played < 5 && (
          <strong>Only {data.games_played} games played so far, so treat these as a rough early read.</strong>
        )}
      </p>

      <div className="table-scroll">
        <table>
          <thead>
            <tr>
              <th>Team</th>
              <th>Record</th>
              <th className="num">Pts/Gm</th>
              <th className="num">Proj. Wins</th>
              <th className="num">Remaining SOS</th>
              <th className="num">Playoff Odds</th>
            </tr>
          </thead>
          <tbody>
            {data.standings.map((row) => (
              <tr key={row.team_id} className={row.is_me ? "swap-row" : ""}>
                <td>
                  {row.team}
                  {row.is_me && <span className="hint"> (you)</span>}
                </td>
                <td>{row.record}</td>
                <td className="num">{row.points_per_game}</td>
                <td className="num">{row.projected_wins}</td>
                <td className={`num${row.schedule_difficulty != null && row.schedule_difficulty > 0 ? " trend-down" : " trend-up"}`}>
                  {row.schedule_difficulty != null
                    ? `${row.schedule_difficulty > 0 ? "+" : ""}${row.schedule_difficulty}`
                    : "—"}
                </td>
                <td className={`num ${oddsClass(row.playoff_odds)}-text`}>{row.playoff_odds}%</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
