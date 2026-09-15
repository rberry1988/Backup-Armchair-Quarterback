import { useState } from "react";
import type { LeagueSummary } from "../types";
import { ApiError, api } from "../api";

interface Props {
  league: LeagueSummary | null;
  onLeagueChange: (league: LeagueSummary) => void;
}

export function SetupPanel({ league, onLeagueChange }: Props) {
  const [leagueId, setLeagueId] = useState(league ? String(league.espn_league_id) : "");
  const [season, setSeason] = useState(league ? String(league.season) : String(new Date().getFullYear()));
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSync() {
    setLoading(true);
    setError(null);
    try {
      const parsedId = Number(leagueId);
      const parsedSeason = Number(season);
      const result = await api.sync(parsedId, parsedSeason);
      onLeagueChange(result);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Failed to sync league. Check the ID and season.");
    } finally {
      setLoading(false);
    }
  }

  async function handleSelectTeam(teamId: number) {
    if (!league) return;
    setError(null);
    try {
      const updated = await api.setMyTeam(league.id, teamId);
      onLeagueChange(updated);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Failed to save your team selection.");
    }
  }

  return (
    <div className="panel">
      <h2>League Setup</h2>
      <div className="form-row">
        <label>
          ESPN League ID
          <input value={leagueId} onChange={(e) => setLeagueId(e.target.value)} placeholder="e.g. 123456" />
        </label>
        <label>
          Season
          <input value={season} onChange={(e) => setSeason(e.target.value)} placeholder="e.g. 2025" />
        </label>
        <button onClick={handleSync} disabled={loading || !leagueId || !season}>
          {loading ? "Syncing..." : "Sync League"}
        </button>
      </div>
      {error && <p className="error">{error}</p>}
      <p className="hint">
        Find your league ID in the ESPN Fantasy URL: fantasy.espn.com/football/league?leagueId=<b>123456</b>.
        Only public leagues are supported out of the box.
      </p>

      {league && (
        <>
          <h3>
            {league.name} &mdash; Week {league.current_week}
          </h3>
          <label className="team-picker">
            Your team:
            <select
              value={league.my_team_id ?? ""}
              onChange={(e) => handleSelectTeam(Number(e.target.value))}
            >
              <option value="" disabled>
                Select your team
              </option>
              {league.teams.map((t) => (
                <option key={t.id} value={t.id}>
                  {t.name} ({t.wins}-{t.losses}-{t.ties})
                </option>
              ))}
            </select>
          </label>

          <details>
            <summary>Synced scoring rules ({league.scoring_rules.length})</summary>
            <ul className="scoring-list">
              {league.scoring_rules.map((r) => (
                <li key={r.stat_id}>
                  {r.stat_name}: {r.points > 0 ? "+" : ""}
                  {r.points}
                </li>
              ))}
            </ul>
          </details>
        </>
      )}
    </div>
  );
}
