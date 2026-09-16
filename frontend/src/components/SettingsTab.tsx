import { SetupPanel } from "./SetupPanel";
import { AccountTab } from "./AccountTab";
import type { LeagueSummary } from "../types";

interface Props {
  email: string;
  displayName: string | null;
  isPremium: boolean;
  onDisplayNameChange: (displayName: string | null) => void;
  league: LeagueSummary | null;
  leagues: LeagueSummary[];
  onLeagueChange: (league: LeagueSummary) => void;
  onLeagueUpdated: (league: LeagueSummary) => void;
  onLeagueRemoved: (leagueId: number) => void;
  onLeagueSelect: (leagueId: number) => void;
}

export function SettingsTab({
  email,
  displayName,
  isPremium,
  onDisplayNameChange,
  league,
  leagues,
  onLeagueChange,
  onLeagueUpdated,
  onLeagueRemoved,
  onLeagueSelect,
}: Props) {
  return (
    <>
      <SetupPanel
        isPremium={isPremium}
        league={league}
        leagues={leagues}
        onLeagueChange={onLeagueChange}
        onLeagueUpdated={onLeagueUpdated}
        onLeagueRemoved={onLeagueRemoved}
        onLeagueSelect={onLeagueSelect}
      />
      <div style={{ marginTop: "1.25rem" }}>
        <AccountTab
          email={email}
          displayName={displayName}
          isPremium={isPremium}
          onDisplayNameChange={onDisplayNameChange}
        />
      </div>
    </>
  );
}
