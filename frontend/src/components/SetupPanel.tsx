import { useState } from "react";
import type { LeagueSummary } from "../types";
import { ApiError, api } from "../api";

interface Props {
  // Only premium accounts can connect an ESPN session, so only they are
  // pointed at it as the way to reach a private league.
  isPremium: boolean;
  league: LeagueSummary | null;
  leagues: LeagueSummary[];
  onLeagueChange: (league: LeagueSummary) => void;
  onLeagueUpdated: (league: LeagueSummary) => void;
  onLeagueRemoved: (leagueId: number) => void;
  onLeagueSelect: (leagueId: number) => void;
}

// Off, plus a few sensible cadences. Hourly is the floor the backend
// enforces too (see auto_sync.clamp_interval_hours).
const AUTO_SYNC_CHOICES: { value: number; label: string }[] = [
  { value: 0, label: "Off" },
  { value: 1, label: "Hourly" },
  { value: 6, label: "Every 6 hours" },
  { value: 12, label: "Every 12 hours" },
  { value: 24, label: "Daily" },
];

export function SetupPanel({
  isPremium,
  league,
  leagues,
  onLeagueChange,
  onLeagueUpdated,
  onLeagueRemoved,
  onLeagueSelect,
}: Props) {
  const [leagueId, setLeagueId] = useState(league ? String(league.espn_league_id) : "");
  const [season, setSeason] = useState(league ? String(league.season) : String(new Date().getFullYear()));
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [removingId, setRemovingId] = useState<number | null>(null);
  const [savingAutoSyncId, setSavingAutoSyncId] = useState<number | null>(null);

  async function handleAutoSyncChange(target: LeagueSummary, value: string) {
    const hours = Number(value);
    setError(null);
    setSavingAutoSyncId(target.id);
    try {
      const updated = await api.setAutoSync(target.id, hours > 0, hours > 0 ? hours : target.auto_sync_interval_hours);
      onLeagueUpdated(updated);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Failed to change auto-sync.");
    } finally {
      setSavingAutoSyncId(null);
    }
  }

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

  async function handleRemove(target: LeagueSummary) {
    if (
      !window.confirm(
        `Remove ${target.name}? This deletes your synced roster/stat history for it. You can re-sync it later, but it starts over from scratch.`
      )
    )
      return;
    setError(null);
    setRemovingId(target.id);
    try {
      await api.deleteLeague(target.id);
      onLeagueRemoved(target.id);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Failed to remove league.");
    } finally {
      setRemovingId(null);
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
        Find your league ID in the ESPN Fantasy URL: fantasy.espn.com/football/league?leagueId=<b>123456</b>.{" "}
        {isPremium
          ? "Public leagues work as-is; for a private one, connect your ESPN account under Account below first."
          : "Only public leagues are supported on a basic account."}
      </p>

      {leagues.length > 0 && (
        <>
          <h3>Your Leagues</h3>
          <p className="hint">
            Auto-sync re-pulls a league from ESPN in the background on the schedule you pick, so rosters,
            projections and injuries stay current without clicking Sync League. The first run happens within a
            few minutes of switching it on.
          </p>
          <div className="table-scroll">
            <table>
              <thead>
                <tr>
                  <th>League</th>
                  <th className="num">Season</th>
                  <th>Your Team</th>
                  <th>Auto-sync</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                {leagues.map((l) => {
                  const isActive = l.id === league?.id;
                  const myTeam = l.teams.find((t) => t.id === l.my_team_id);
                  return (
                    <tr key={l.id}>
                      <td>
                        {l.name}
                        {isActive && <span className="hint"> (active)</span>}
                      </td>
                      <td className="num">{l.season}</td>
                      <td>{myTeam ? myTeam.name : <span className="hint">not set</span>}</td>
                      <td>
                        <select
                          value={l.auto_sync_enabled ? l.auto_sync_interval_hours : 0}
                          onChange={(e) => handleAutoSyncChange(l, e.target.value)}
                          disabled={savingAutoSyncId === l.id}
                          aria-label={`Auto-sync ${l.name}`}
                        >
                          {AUTO_SYNC_CHOICES.map((c) => (
                            <option key={c.value} value={c.value}>
                              {c.label}
                            </option>
                          ))}
                        </select>
                        {l.auto_sync_error && (
                          <div className="error" style={{ fontSize: "0.75rem" }} title={l.auto_sync_error}>
                            Last run failed
                          </div>
                        )}
                      </td>
                      <td style={{ display: "flex", gap: "0.4rem" }}>
                        {!isActive && <button onClick={() => onLeagueSelect(l.id)}>Switch</button>}
                        <button onClick={() => handleRemove(l)} disabled={removingId === l.id}>
                          {removingId === l.id ? "Removing..." : "Remove"}
                        </button>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </>
      )}

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
