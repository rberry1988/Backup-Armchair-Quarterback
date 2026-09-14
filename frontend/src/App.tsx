import { useEffect, useState } from "react";
import "./App.css";
import { SetupPanel } from "./components/SetupPanel";
import { RosterTab } from "./components/RosterTab";
import { StartSitTab } from "./components/StartSitTab";
import { WaiversTab } from "./components/WaiversTab";
import { TradesTab } from "./components/TradesTab";
import { api } from "./api";
import type { LeagueSummary } from "./types";

type Tab = "setup" | "roster" | "start-sit" | "waivers" | "trades";

function App() {
  const [league, setLeague] = useState<LeagueSummary | null>(null);
  const [tab, setTab] = useState<Tab>("setup");

  useEffect(() => {
    const savedId = localStorage.getItem("leagueId");
    if (savedId) {
      api
        .getLeague(Number(savedId))
        .then((l) => {
          setLeague(l);
          setTab(l.my_team_id ? "start-sit" : "setup");
        })
        .catch(() => {
          /* not synced yet, stay on setup */
        });
    }
  }, []);

  const canViewTeamTabs = league?.my_team_id != null;

  return (
    <div className="app">
      <header>
        <h1>Fantasy Football Copilot</h1>
        {league && <span className="league-badge">{league.name}</span>}
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
