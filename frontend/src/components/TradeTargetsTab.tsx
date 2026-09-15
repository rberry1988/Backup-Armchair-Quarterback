import { TradesTab } from "./TradesTab";
import { TradeGraderTab } from "./TradeGraderTab";

export function TradeTargetsTab({ leagueId, myTeamId }: { leagueId: number; myTeamId: number | null }) {
  return (
    <>
      <TradesTab leagueId={leagueId} />
      <div style={{ marginTop: "1.25rem" }}>
        <TradeGraderTab leagueId={leagueId} myTeamId={myTeamId} />
      </div>
    </>
  );
}
