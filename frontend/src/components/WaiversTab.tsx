import { useEffect, useState } from "react";
import type { RestOfSeasonSuggestion, WaiverGroup, WaiverResponse, WaiverSuggestion } from "../types";
import { api } from "../api";
import { formatPoints } from "../formatPoints";
import { MatchupTag } from "./MatchupTag";
import { TrendTag } from "./TrendTag";
import { InjuryBadge } from "./InjuryBadge";

type Lens = "this-week" | "rest-of-season";

function ThisWeekTable({ group }: { group: WaiverGroup<WaiverSuggestion> }) {
  return (
    <div className="waiver-group">
      <h3>{group.position}</h3>
      <div className="table-scroll">
        <table>
          <thead>
            <tr>
              <th>Add</th>
              <th className="num">Proj.</th>
              <th>Matchup</th>
              <th className="num">% Owned</th>
              <th>Drop</th>
              <th className="num">Net Gain</th>
              <th className="num">Suggested FAAB</th>
              <th>Usage Trend</th>
            </tr>
          </thead>
          <tbody>
            {group.suggestions.map((s, i) => (
              <tr key={i}>
                <td>
                  {s.add.name}
                  <InjuryBadge status={s.add.injury_status} />
                </td>
                <td className="num">{formatPoints(s.add.projected_points)}</td>
                <td>
                  <MatchupTag matchup={s.add.matchup} />
                </td>
                <td className="num">{s.add.percent_owned}%</td>
                <td>{s.drop_candidate ? s.drop_candidate.name : "-"}</td>
                <td className="num">+{s.point_upgrade}</td>
                <td className="num">{s.suggested_faab_pct}%</td>
                <td>
                  <TrendTag trend={s.add.trend} />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function RestOfSeasonTable({ group }: { group: WaiverGroup<RestOfSeasonSuggestion> }) {
  return (
    <div className="waiver-group">
      <h3>{group.position}</h3>
      <div className="table-scroll">
        <table>
          <thead>
            <tr>
              <th>Add</th>
              <th className="num">Value</th>
              <th className="num">Pos. Rank</th>
              <th className="num">30d Trend</th>
              <th className="num">Proj.</th>
              <th className="num">% Owned</th>
              <th>Drop</th>
              <th className="num">Value Gain</th>
            </tr>
          </thead>
          <tbody>
            {group.suggestions.map((s, i) => (
              <tr key={i}>
                <td>
                  {s.add.name}
                  <InjuryBadge status={s.add.injury_status} />
                </td>
                <td className="num">{s.add.fantasycalc?.value ?? "—"}</td>
                <td className="num">
                  {s.add.fantasycalc?.position_rank != null ? `${group.position}${s.add.fantasycalc.position_rank}` : "—"}
                </td>
                <td className={`num${(s.add.fantasycalc?.trend_30_day ?? 0) < 0 ? " trend-down" : " trend-up"}`}>
                  {s.add.fantasycalc?.trend_30_day != null
                    ? `${s.add.fantasycalc.trend_30_day > 0 ? "+" : ""}${s.add.fantasycalc.trend_30_day}`
                    : "—"}
                </td>
                <td className="num">{formatPoints(s.add.projected_points)}</td>
                <td className="num">{s.add.percent_owned}%</td>
                <td>{s.drop_candidate ? s.drop_candidate.name : "-"}</td>
                <td className="num">+{s.value_upgrade}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

export function WaiversTab({ leagueId }: { leagueId: number }) {
  const [data, setData] = useState<WaiverResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [lens, setLens] = useState<Lens>("this-week");

  useEffect(() => {
    let ignore = false;
    api
      .getWaivers(leagueId)
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

  const groups = lens === "this-week" ? data.this_week : data.rest_of_season;

  return (
    <div className="panel">
      <h2>Waiver Wire Targets</h2>

      <div className="lens-toggle">
        <button className={lens === "this-week" ? "active" : ""} onClick={() => setLens("this-week")}>
          This Week
        </button>
        <button className={lens === "rest-of-season" ? "active" : ""} onClick={() => setLens("rest-of-season")}>
          Rest of Season
        </button>
      </div>

      {lens === "this-week" ? (
        <p className="hint">
          Ranked by who helps you win <em>this week</em>. Net Gain factors in more than the raw projection &mdash; a
          rising usage trend or favorable matchup nudges a player up, a falling trend or tough matchup nudges them
          down. Suggested FAAB is a starting point (% of a 100-point budget) scaled off that net gain over your
          weakest rostered player at the position; ignore it if your league uses waiver priority.
        </p>
      ) : (
        <p className="hint">
          Ranked by FantasyCalc market value &mdash; a consensus read on what a player is worth for the{" "}
          <em>remainder of the season</em>, from real trades in leagues like yours. These deliberately differ from the
          weekly list: the best streamer this week often isn't the best asset to hold. Players who are currently out
          are included here, since an injured stash is frequently the point of a rest-of-season pickup.
        </p>
      )}

      {groups.length === 0 ? (
        lens === "rest-of-season" && !data.fantasycalc_available ? (
          <p>
            No market values available yet &mdash; they're pulled during a league sync. Sync this league again (or
            turn on auto-sync in Settings) to populate them.
          </p>
        ) : (
          <p>No upgrades found on the waiver wire right now &mdash; your roster looks solid.</p>
        )
      ) : (
        groups.map((group) =>
          lens === "this-week" ? (
            <ThisWeekTable key={group.position} group={group as WaiverGroup<WaiverSuggestion>} />
          ) : (
            <RestOfSeasonTable key={group.position} group={group as WaiverGroup<RestOfSeasonSuggestion>} />
          )
        )
      )}
    </div>
  );
}
