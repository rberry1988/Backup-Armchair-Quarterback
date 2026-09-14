import { useEffect, useState } from "react";
import "./App.css";
import { LoginPage } from "./components/LoginPage";
import { SetupPanel } from "./components/SetupPanel";
import { RosterTab } from "./components/RosterTab";
import { StartSitTab } from "./components/StartSitTab";
import { WaiversTab } from "./components/WaiversTab";
import { TradesTab } from "./components/TradesTab";
import { api, clearToken, getToken } from "./api";
import type { LeagueSummary, User } from "./types";

type Tab = "setup" | "roster" | "start-sit" | "waivers" | "trades";

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
        setTab(mostRecent.my_team_id != null ? "start-sit" : "setup");
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
        <h1>Fantasy Football Copilot</h1>
        {league && <span className="league-badge">{league.name}</span>}
        <div className="header-right">
          <span>{user.email}</span>
          <button className="logout-button" onClick={handleLogout}>
            Log out
          </button>
        </div>
      </header>

      <nav className="tabs">
        <button className={tab === "setup" ? "active" : ""} onClick={() => setTab("setup")}>
          Setup
        </button>
        <button
          className={tab === "roster" ? "active" : ""}
          onClick={() => setTab("roster")}
          disabled={!canViewTeamTabs}
        >
          Roster
        </button>
        <button
          className={tab === "start-sit" ? "active" : ""}
          onClick={() => setTab("start-sit")}
          disabled={!canViewTeamTabs}
        >
          Start / Sit
        </button>
        <button
          className={tab === "waivers" ? "active" : ""}
          onClick={() => setTab("waivers")}
          disabled={!canViewTeamTabs}
        >
          Waivers
        </button>
        <button
          className={tab === "trades" ? "active" : ""}
          onClick={() => setTab("trades")}
          disabled={!canViewTeamTabs}
        >
          Trades
        </button>
      </nav>

      <main>
        {tab === "setup" && <SetupPanel league={league} onLeagueChange={setLeague} />}
        {tab === "roster" && league && <RosterTab leagueId={league.id} />}
        {tab === "start-sit" && league && <StartSitTab leagueId={league.id} />}
        {tab === "waivers" && league && <WaiversTab leagueId={league.id} />}
        {tab === "trades" && league && <TradesTab leagueId={league.id} />}
      </main>
    </div>
  );
}

export default App;
