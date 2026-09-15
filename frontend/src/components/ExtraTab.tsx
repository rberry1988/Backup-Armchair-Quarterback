import { DepthChartsTab } from "./DepthChartsTab";
import { HandcuffsTab } from "./HandcuffsTab";
import { BenchPointsTab } from "./BenchPointsTab";
import { ExpertRankingsTab } from "./ExpertRankingsTab";

export function ExtraTab({ leagueId }: { leagueId: number }) {
  return (
    <>
      <HandcuffsTab leagueId={leagueId} />
      <div style={{ marginTop: "1.25rem" }}>
        <BenchPointsTab leagueId={leagueId} />
      </div>
      <div style={{ marginTop: "1.25rem" }}>
        <DepthChartsTab leagueId={leagueId} />
      </div>
      <div style={{ marginTop: "1.25rem" }}>
        <ExpertRankingsTab leagueId={leagueId} />
      </div>
    </>
  );
}
