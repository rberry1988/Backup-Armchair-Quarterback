import { useEffect, useState } from "react";
import "./App.css";
import { LoginPage } from "./components/LoginPage";
import { SetupPanel } from "./components/SetupPanel";
import { RosterTab } from "./components/RosterTab";
import { StartSitTab } from "./components/StartSitTab";
import { WaiversTab } from "./components/WaiversTab";
import { TradesTab } from "./components/TradesTab";
import { TradeGraderTab } from "./components/TradeGraderTab";
import { ExpertRankingsTab } from "./components/ExpertRankingsTab";
import { DepthChartsTab } from "./components/DepthChartsTab";
import { HandcuffsTab } from "./components/HandcuffsTab";
import { AlertsTab } from "./components/AlertsTab";
import { ScheduleTab } from "./components/ScheduleTab";
import { BenchPointsTab } from "./components/BenchPointsTab";
import { api, clearToken, getToken } from "./api";
import type { LeagueSummary, User } from "./types";

type Tab =
  | "setup"
  | "alerts"
  | "roster"
  | "start-sit"
  | "waivers"
  | "schedule"
  | "trades"
  | "trade-grader"
  | "expert-rankings"
  | "depth-charts"
  | "handcuffs"
  | "bench-points";

const TABS: { id: Tab; label: string }[] = [
  { id: "setup", label: "Setup" },
  { id: "alerts", label: "Alerts" },
  { id: "roster", label: "Roster" },
  { id: "start-sit", label: "Start / Sit" },
  { id: "waivers", label: "Waivers" },
  { id: "schedule", label: "Schedule" },
  { id: "trades", label: "Trades" },
  { id: "trade-grader", label: "Trade Grader" },
  { id: "expert-rankings", label: "Expert Rankings" },
  { id: "depth-charts", label: "Depth Charts" },
  { id: "handcuffs", label: "Handcuffs" },
  { id: "bench-points", label: "Bench Points" },
];

function App() {
  const [authChecked, setAuthChecked] = useState(false);
  const [user, setUser] = useState<User | null>(null);
  const [league, setLeague] = useState<LeagueSummary | null>(null);
  const [tab, setTab] = useState<Tab>("setup");

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
      const leagues = await api.listLeagues();
      if (leagues.length > 0) {
        const mostRecent = leagues[0];
        setLeague(mostRecent);
        setTab(mostRecent.my_team_id != null ? "alerts" : "setup");
      }
    } catch {
      clearToken();
      setUser(null);
    } finally {
      setAuthChecked(true);
    }
  }

  function handleLogout() {
    clearToken();
    setUser(null);
    setLeague(null);
    setTab("setup");
  }

  if (!authChecked) {
    return null;
  }

  if (!user) {
    return <LoginPage onLoggedIn={loadSession} />;
  }

  const canViewTeamTabs = league?.my_team_id != null;

  return (
    <div className="app">
      <header>
        <h1>Backup Armchair Quarterback</h1>
        {league && <span className="league-badge">{league.name}</span>}
        <div className="header-right">
          <span>{user.email}</span>
          <button className="logout-button" onClick={handleLogout}>
            Log out
          </button>
        </div>
      </header>

      <nav className="tabs">
        {TABS.map(({ id, label }) => (
          <button
            key={id}
            className={tab === id ? "active" : ""}
            onClick={() => setTab(id)}
            disabled={id !== "setup" && !canViewTeamTabs}
          >
            {label}
          </button>
        ))}
      </nav>

      <main>
        {tab === "setup" && <SetupPanel league={league} onLeagueChange={setLeague} />}
        {tab === "roster" && league && <RosterTab leagueId={league.id} />}
        {tab === "start-sit" && league && <StartSitTab leagueId={league.id} />}
        {tab === "waivers" && league && <WaiversTab leagueId={league.id} />}
        {tab === "trades" && league && <TradesTab leagueId={league.id} />}
        {tab === "trade-grader" && league && (
          <TradeGraderTab leagueId={league.id} myTeamId={league.my_team_id} />
        )}
        {tab === "expert-rankings" && league && <ExpertRankingsTab leagueId={league.id} />}
        {tab === "depth-charts" && league && <DepthChartsTab leagueId={league.id} />}
        {tab === "handcuffs" && league && <HandcuffsTab leagueId={league.id} />}
        {tab === "alerts" && league && <AlertsTab leagueId={league.id} />}
        {tab === "schedule" && league && <ScheduleTab leagueId={league.id} />}
        {tab === "bench-points" && league && <BenchPointsTab leagueId={league.id} />}
      </main>
    </div>
  );
}

export default App;
