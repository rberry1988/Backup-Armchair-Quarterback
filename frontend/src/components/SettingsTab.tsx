import { SetupPanel } from "./SetupPanel";
import { AccountTab } from "./AccountTab";
import type { LeagueSummary } from "../types";

interface Props {
  email: string;
  league: LeagueSummary | null;
  onLeagueChange: (league: LeagueSummary) => void;
  onLeagueRemoved: (leagueId: number) => void;
}

export function SettingsTab({ email, league, onLeagueChange, onLeagueRemoved }: Props) {
  return (
    <>
      <SetupPanel league={league} onLeagueChange={onLeagueChange} onLeagueRemoved={onLeagueRemoved} />
      <div style={{ marginTop: "1.25rem" }}>
        <AccountTab email={email} />
      </div>
    </>
  );
}
