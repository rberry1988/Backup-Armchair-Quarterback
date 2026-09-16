import { useEffect, useState } from "react";
import type {
  LiveMatchupResponse,
  LivePlayer,
  LiveSide,
  MatchupLineupRow,
  MatchupPreviewResponse,
  MatchupSide,
} from "../types";
import { api } from "../api";
import { formatPoints } from "../formatPoints";
import { MatchupTag } from "./MatchupTag";
import { InjuryBadge } from "./InjuryBadge";
import { starterSlotRank } from "../lineupSlotOrder";

/** Same QB/RB/WR/TE/FLEX/D/K ordering as every other tab, so the two
 * lineups line up row-for-row and can be read across. */
function ordered(lineup: MatchupLineupRow[]): MatchupLineupRow[] {
  return [...lineup].sort((a, b) => {
    const rank = starterSlotRank(a.slot) - starterSlotRank(b.slot);
    if (rank !== 0) return rank;
    return (b.projected_points ?? -Infinity) - (a.projected_points ?? -Infinity);
  });
}

function SideColumn({ side, label }: { side: MatchupSide; label: string }) {
  return (
    <div className="matchup-side">
      <h3>
        {side.name} <span className="hint">{side.record}</span>
      </h3>
      <p className="matchup-total">
        {formatPoints(side.projected)} <span className="hint">projected &middot; {label}</span>
      </p>
      <div className="table-scroll">
        <table>
          <thead>
            <tr>
              <th>Slot</th>
              <th>Player</th>
              <th className="num">Proj.</th>
              <th>Matchup</th>
            </tr>
          </thead>
          <tbody>
            {ordered(side.lineup).map((row, i) => (
              <tr key={`${row.slot_id}-${i}`}>
                <td>{row.slot}</td>
                <td>
                  {row.name}
                  <InjuryBadge status={row.injury_status} />
                </td>
                <td className="num">{formatPoints(row.projected_points)}</td>
                <td>
                  <MatchupTag matchup={row.matchup} />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

/** While games are on, this replaces the pre-game column. The difference
 * that matters is `banked` vs `estimate`: points already scored are
 * certain, everything else is still a projection. */
function LiveColumn({ side, label }: { side: LiveSide; label: string }) {
  return (
    <div className="matchup-side">
      <h3>{side.name}</h3>
      <p className="matchup-total">
        {formatPoints(side.banked)}{" "}
        <span className="hint">
          scored &middot; {label} &middot; proj. {formatPoints(side.estimate)}
        </span>
      </p>
      <p className="hint">
        {side.yet_to_play} yet to play, {side.in_progress} in progress
      </p>
      <div className="table-scroll">
        <table>
          <thead>
            <tr>
              <th>Slot</th>
              <th>Player</th>
              <th className="num">Pts</th>
              <th className="num">Proj.</th>
              <th>Game</th>
            </tr>
          </thead>
          <tbody>
            {[...side.players]
              .sort((a, b) => starterSlotRank(a.slot) - starterSlotRank(b.slot))
              .map((p: LivePlayer, i) => (
                <tr key={`${p.slot}-${i}`} className={p.state === "in" ? "live-playing" : ""}>
                  <td>{p.slot}</td>
                  <td>{p.name}</td>
                  <td className="num">{formatPoints(p.points)}</td>
                  <td className="num">{p.projected_points != null ? formatPoints(p.projected_points) : "-"}</td>
                  <td className={`live-state live-${p.state}`}>
                    {p.state === "post" ? "Final" : p.state === "in" ? p.detail || "Playing" : p.detail || "Not started"}
                  </td>
                </tr>
              ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

export function MatchupTab({ leagueId }: { leagueId: number }) {
  const [data, setData] = useState<MatchupPreviewResponse | null>(null);
  const [live, setLive] = useState<LiveMatchupResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let ignore = false;
    api
      .getMatchupPreview(leagueId)
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

  // Fetched separately so the pre-game view (served from the database)
  // renders immediately instead of waiting on two round trips to ESPN.
  // Polls only while a game is actually running -- there's nothing to
  // refresh on a Tuesday, and hammering ESPN is how you get blocked.
  useEffect(() => {
    let ignore = false;
    let timer: number | undefined;

    const poll = () => {
      api
        .getMatchupLive(leagueId)
        .then((res) => {
          if (ignore) return;
          setLive(res);
          if (res.available && res.in_progress) {
            timer = window.setTimeout(poll, 60_000);
          }
        })
        .catch(() => {
          // Live data is an enhancement; its absence leaves the pre-game
          // view intact rather than replacing it with an error.
          if (!ignore) setLive(null);
        });
    };

    poll();
    return () => {
      ignore = true;
      if (timer) window.clearTimeout(timer);
    };
  }, [leagueId]);

  if (error) return <p className="error">{error}</p>;
  if (!data) return <p>Loading...</p>;

  if (!data.opponent) {
    return (
      <div className="panel">
        <h2>This Week's Matchup</h2>
        <p>
          {data.schedule_available
            ? "You don't have an opponent this week — that's a bye in your league's schedule."
            : "No head-to-head schedule yet. Sync this league again to pull it from ESPN."}
        </p>
      </div>
    );
  }

  // Live numbers win once any game has kicked off: they're built from
  // points already on the board, so they're strictly better informed than
  // the projection this tab opened with.
  const isLive = live?.available === true;
  const margin = isLive ? live.margin : data.margin ?? 0;
  const winPct = isLive ? live.win_probability : data.win_probability ?? 50;
  const favored = margin > 0;
  const swing = data.biggest_swing;

  return (
    <div className="panel">
      <h2>
        Week {data.week}: {data.me.name} vs {data.opponent.name}
      </h2>

      <div className="matchup-verdict">
        <div className={`win-prob ${favored ? "win-prob-good" : "win-prob-bad"}`}>{winPct}%</div>
        <div>
          <p className="verdict">
            {favored ? "Up by" : margin < 0 ? "Down by" : "Level —"}{" "}
            {margin !== 0 && formatPoints(Math.abs(margin))}{" "}
            {isLive ? "projected, with games in play" : "projected points"}
          </p>
          <p className="hint">
            {isLive ? (
              <>
                {/* Why the live number deserves more trust than the pre-game
                    one: the uncertainty it carries is only over what's left. */}
                Live: {formatPoints(live.me.banked)}&ndash;{formatPoints(live.opponent.banked)} on the board, with{" "}
                {live.me.yet_to_play + live.opponent.yet_to_play} starters yet to play. The odds tighten as games
                finish, because only unplayed points are still uncertain.
              </>
            ) : (
              <>
                Win probability assumes a typical weekly swing of about {data.stdev_assumed} points per team. Treat it
                as a rough read on how safe the margin is, not a forecast.
              </>
            )}
          </p>
        </div>
      </div>

      {swing && !isLive && (
        <p className="matchup-swing">
          Biggest single change available: start <strong>{swing.in}</strong> over <strong>{swing.out}</strong> at{" "}
          {swing.slot} &mdash; worth {formatPoints(swing.gain)} points and takes you to{" "}
          <strong>{swing.win_probability_after}%</strong>.
        </p>
      )}

      <div className="matchup-grid">
        {isLive ? (
          <>
            <LiveColumn side={live.me} label="you" />
            <LiveColumn side={live.opponent} label="them" />
          </>
        ) : (
          <>
            <SideColumn side={data.me} label="you" />
            <SideColumn side={data.opponent} label="them" />
          </>
        )}
      </div>
    </div>
  );
}
