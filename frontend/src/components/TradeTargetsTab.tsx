import { TradesTab } from "./TradesTab";
import { TradeGraderTab } from "./TradeGraderTab";

export function TradeTargetsTab({
  leagueId,
  myTeamId,
  isPremium,
}: {
  leagueId: number;
  myTeamId: number | null;
  isPremium: boolean;
}) {
  return (
    <>
      <TradesTab leagueId={leagueId} isPremium={isPremium} />
      <div style={{ marginTop: "1.25rem" }}>
        <TradeGraderTab leagueId={leagueId} myTeamId={myTeamId} />
      </div>
    </>
  );
}
