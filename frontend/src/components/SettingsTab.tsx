import { SetupPanel } from "./SetupPanel";
import { AccountTab } from "./AccountTab";
import type { LeagueSummary } from "../types";

interface Props {
  email: string;
  league: LeagueSummary | null;
  leagues: LeagueSummary[];
  onLeagueChange: (league: LeagueSummary) => void;
  onLeagueRemoved: (leagueId: number) => void;
  onLeagueSelect: (leagueId: number) => void;
}

export function SettingsTab({ email, league, leagues, onLeagueChange, onLeagueRemoved, onLeagueSelect }: Props) {
  return (
    <>
      <SetupPanel
        league={league}
        leagues={leagues}
        onLeagueChange={onLeagueChange}
        onLeagueRemoved={onLeagueRemoved}
        onLeagueSelect={onLeagueSelect}
      />
      <div style={{ marginTop: "1.25rem" }}>
        <AccountTab email={email} />
      </div>
    </>
  );
}
