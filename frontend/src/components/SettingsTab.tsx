import { SetupPanel } from "./SetupPanel";
import { AccountTab } from "./AccountTab";
import type { LeagueSummary } from "../types";

interface Props {
  email: string;
  displayName: string | null;
  onDisplayNameChange: (displayName: string | null) => void;
  league: LeagueSummary | null;
  leagues: LeagueSummary[];
  onLeagueChange: (league: LeagueSummary) => void;
  onLeagueRemoved: (leagueId: number) => void;
  onLeagueSelect: (leagueId: number) => void;
}

export function SettingsTab({
  email,
  displayName,
  onDisplayNameChange,
  league,
  leagues,
  onLeagueChange,
  onLeagueRemoved,
  onLeagueSelect,
}: Props) {
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
        <AccountTab email={email} displayName={displayName} onDisplayNameChange={onDisplayNameChange} />
      </div>
    </>
  );
}
