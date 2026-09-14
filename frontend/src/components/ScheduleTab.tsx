import { useEffect, useState } from "react";
import type { OutlookSummary, OutlookWeek, ScheduleOutlookResponse } from "../types";
import { api } from "../api";

const SUMMARY_CLASS: Record<string, string> = {
  "favorable stretch": "matchup-favorable",
  "average stretch": "matchup-average",
  "tough stretch": "matchup-tough",
};

const WEEK_CLASS: Record<string, string> = {
  "favorable matchup": "matchup-favorable",
  "average matchup": "matchup-average",
  "tough matchup": "matchup-tough",
};

export function ScheduleTab({ leagueId }: { leagueId: number }) {
  const [data, setData] = useState<ScheduleOutlookResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api
      .getScheduleOutlook(leagueId)
      .then(setData)
      .catch((e) => setError(e.message));
  }, [leagueId]);

  if (error) return <p className="error">{error}</p>;
  if (!data) return <p>Loading...</p>;
  if (data.error) return <p className="error">{data.error}</p>;

  if (!data.available) {
    return (
      <div className="panel">
        <h2>Schedule Outlook</h2>
        <p>
          The full-season NFL schedule wasn't available at your last sync. Re-sync your league to populate bye
          weeks and the multi-week outlook.
        </p>
      </div>
    );
  }

  const upcomingWeeks = data.outlook[0]?.upcoming.map((w) => w.week) ?? [];

  return (
    <>
      <div className="panel">
        <h2>Bye Week Planner</h2>
        {data.byes.length === 0 ? (
          <p className="hint">No remaining bye weeks on your roster.</p>
        ) : (
          <>
            <p className="hint">Upcoming weeks where your players are off, worst collisions flagged.</p>
            {data.byes.map((group) => (
              <div key={group.week} className="partner-card">
                <h4>
                  Week {group.week} <span className="pos-tag">{group.count} player{group.count === 1 ? "" : "s"} off</span>
                </h4>
                {group.warnings.map((warning) => (
                  <p key={warning} className="error" style={{ margin: "0.2rem 0", fontSize: "0.85rem" }}>
                    {warning}
                  </p>
                ))}
                <p className="hint">
                  {group.players.map((p) => `${p.name} (${p.position})`).join(", ")}
                </p>
              </div>
            ))}
          </>
        )}
      </div>

      <div className="panel" style={{ marginTop: "1.25rem" }}>
        <h2>Next {data.weeks_ahead} Weeks</h2>
        <p className="hint">
          Toughest schedules first, rated the same way as this week's matchup tags. Playoff columns are weeks{" "}
          {(data.playoff_weeks ?? []).join(", ")} — the stretch that decides your season.
        </p>
        <table>
          <thead>
            <tr>
              <th>Player</th>
              <th>Pos</th>
              <th>Bye</th>
              {upcomingWeeks.map((week) => (
                <th key={week}>Wk {week}</th>
              ))}
              <th>Next {data.weeks_ahead}</th>
              <th>Playoffs</th>
            </tr>
          </thead>
          <tbody>
            {data.outlook.map((player) => (
              <tr key={player.espn_player_id}>
                <td>{player.name}</td>
                <td>{player.position}</td>
                <td className="hint">{player.bye_week ?? "-"}</td>
                {player.upcoming.map((week) => (
                  <td key={week.week}>
                    <WeekCell week={week} />
                  </td>
                ))}
                <td>
                  <SummaryTag summary={player.upcoming_summary} />
                </td>
                <td>
                  <SummaryTag summary={player.playoff_summary} />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  );
}

function WeekCell({ week }: { week: OutlookWeek }) {
  if (week.is_bye) return <span className="matchup-tag matchup-average">BYE</span>;
  if (!week.label) return <span className="hint">{week.opponent ?? "-"}</span>;
  return (
    <span
      className={`matchup-tag ${WEEK_CLASS[week.label] ?? "matchup-average"}`}
      title={
        week.defense_rank
          ? `Opponent defense ranked ${week.defense_rank} of ${week.defense_teams_ranked} vs this position`
          : undefined
      }
    >
      {week.opponent}
    </span>
  );
}

function SummaryTag({ summary }: { summary: OutlookSummary }) {
  if (!summary.label) return <span className="hint">-</span>;
  return (
    <span className={`matchup-tag ${SUMMARY_CLASS[summary.label] ?? "matchup-average"}`}>
      {summary.label}
      {summary.byes > 0 ? ` · ${summary.byes} bye` : ""}
    </span>
  );
}
