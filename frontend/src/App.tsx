import { useEffect, useState } from "react";
import "./App.css";
import { LoginPage } from "./components/LoginPage";
import { SettingsTab } from "./components/SettingsTab";
import { RosterTab } from "./components/RosterTab";
import { StartSitTab } from "./components/StartSitTab";
import { WaiversTab } from "./components/WaiversTab";
import { TradeTargetsTab } from "./components/TradeTargetsTab";
import { AlertsTab } from "./components/AlertsTab";
import { ScheduleTab } from "./components/ScheduleTab";
import { ExtraTab } from "./components/ExtraTab";
import { AdminTab } from "./components/AdminTab";
import { api, clearToken, getToken } from "./api";
import { formatRelativeTime } from "./relativeTime";
import type { LeagueSummary, User } from "./types";

type Tab =
  | "settings"
  | "alerts"
  | "roster"
  | "start-sit"
  | "waivers"
  | "schedule"
  | "trade-targets"
  | "extra"
  | "admin";

// Tabs that don't need a synced league selected to be usable.
const NO_LEAGUE_REQUIRED: Tab[] = ["settings", "admin"];

const BASE_TABS: { id: Tab; label: string }[] = [
  { id: "settings", label: "Settings" },
  { id: "alerts", label: "Alerts" },
  { id: "roster", label: "Roster" },
  { id: "start-sit", label: "Start / Sit" },
  { id: "waivers", label: "Waivers" },
  { id: "schedule", label: "Schedule" },
  { id: "trade-targets", label: "Trades" },
  { id: "extra", label: "Extra" },
];

function App() {
  const [authChecked, setAuthChecked] = useState(false);
  const [user, setUser] = useState<User | null>(null);
  const [league, setLeague] = useState<LeagueSummary | null>(null);
  const [leagues, setLeagues] = useState<LeagueSummary[]>([]);
  const [tab, setTab] = useState<Tab>("settings");

  useEffect(() => {
    if (!getToken()) {
      setAuthChecked(true);
      return;
    }
    loadSession();
  }, []);

  async function loadSession() {
    try {
      const me = await api.me();
      setUser(me);
      const fetchedLeagues = await api.listLeagues();
      setLeagues(fetchedLeagues);
      if (fetchedLeagues.length > 0) {
        const mostRecent = fetchedLeagues[0];
        setLeague(mostRecent);
        setTab(mostRecent.my_team_id != null ? "alerts" : "settings");
      }
    } catch {
      clearToken();
      setUser(null);
    } finally {
      setAuthChecked(true);
    }
  }

  // Called after both a fresh sync and a team-selection change (SetupPanel
  // uses the same callback for either) — merges the updated league into
  // the full list instead of just replacing the active one, so switching
  // to a second league doesn't make the first one disappear from view.
  function handleLeagueChange(updated: LeagueSummary) {
    setLeagues((prev) => [updated, ...prev.filter((l) => l.id !== updated.id)]);
    setLeague(updated);
  }

  // Updates one league in place, keeping list order and whichever league is
  // active — unlike handleLeagueChange, which deliberately promotes the
  // league it's given and switches to it. Toggling a setting on a league
  // you aren't currently viewing shouldn't yank you over to it.
  function handleLeagueUpdated(updated: LeagueSummary) {
    setLeagues((prev) => prev.map((l) => (l.id === updated.id ? updated : l)));
    setLeague((prev) => (prev && prev.id === updated.id ? updated : prev));
  }

  function handleLeagueSelect(leagueId: number) {
    const found = leagues.find((l) => l.id === leagueId);
    if (found) setLeague(found);
  }

  function handleLeagueRemoved(leagueId: number) {
    const remaining = leagues.filter((l) => l.id !== leagueId);
    setLeagues(remaining);
    if (league?.id === leagueId) {
      const next = remaining[0] ?? null;
      setLeague(next);
      setTab(next && next.my_team_id != null ? "alerts" : "settings");
    }
  }

  function handleLogout() {
    clearToken();
    setUser(null);
    setLeague(null);
    setLeagues([]);
    setTab("settings");
  }

  if (!authChecked) {
    return null;
  }

  if (!user) {
    return <LoginPage onLoggedIn={loadSession} />;
  }

  const canViewTeamTabs = league?.my_team_id != null;
  const visibleBaseTabs = BASE_TABS.filter((t) => t.id !== "extra" || user.is_premium);
  const tabs = user.is_admin ? [...visibleBaseTabs, { id: "admin" as const, label: "Admin" }] : visibleBaseTabs;

  return (
    <div className="app">
      <header>
        <h1>Backup Armchair Quarterback</h1>
        {leagues.length > 1 ? (
          <select
            className="league-badge"
            value={league?.id ?? ""}
            onChange={(e) => handleLeagueSelect(Number(e.target.value))}
            aria-label="Switch league"
          >
            {leagues.map((l) => (
              <option key={l.id} value={l.id}>
                {l.name} ({l.season})
              </option>
            ))}
          </select>
        ) : (
          league && <span className="league-badge">{league.name}</span>
        )}
        {league?.synced_at && (
          <span className="hint sync-freshness" title={new Date(league.synced_at).toLocaleString()}>
            Synced {formatRelativeTime(league.synced_at)}
          </span>
        )}
        <div className="header-right">
          <span>{user.display_name || user.email}</span>
          <button className="logout-button" onClick={handleLogout}>
            Log out
          </button>
        </div>
      </header>

      <nav className="tabs">
        {tabs.map(({ id, label }) => (
          <button
            key={id}
            className={tab === id ? "active" : ""}
            onClick={() => setTab(id)}
            disabled={!NO_LEAGUE_REQUIRED.includes(id) && !canViewTeamTabs}
          >
            {label}
          </button>
        ))}
      </nav>

      <main>
        {tab === "settings" && (
          <SettingsTab
            email={user.email}
            displayName={user.display_name}
            isPremium={user.is_premium}
            onDisplayNameChange={(displayName) => setUser((prev) => (prev ? { ...prev, display_name: displayName } : prev))}
            league={league}
            leagues={leagues}
            onLeagueChange={handleLeagueChange}
            onLeagueUpdated={handleLeagueUpdated}
            onLeagueRemoved={handleLeagueRemoved}
            onLeagueSelect={handleLeagueSelect}
          />
        )}
        {tab === "roster" && league && <RosterTab leagueId={league.id} />}
        {tab === "start-sit" && league && <StartSitTab leagueId={league.id} />}
        {tab === "waivers" && league && <WaiversTab leagueId={league.id} isPremium={user.is_premium} />}
        {tab === "trade-targets" && league && (
          <TradeTargetsTab leagueId={league.id} myTeamId={league.my_team_id} />
        )}
        {tab === "alerts" && league && <AlertsTab leagueId={league.id} />}
        {tab === "schedule" && league && <ScheduleTab leagueId={league.id} />}
        {tab === "extra" && league && user.is_premium && <ExtraTab leagueId={league.id} />}
        {tab === "admin" && user.is_admin && <AdminTab currentUserId={user.id} />}
      </main>
    </div>
  );
}

export default App;
