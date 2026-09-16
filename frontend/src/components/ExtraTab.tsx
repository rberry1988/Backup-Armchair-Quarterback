import { PlayoffOddsTab } from "./PlayoffOddsTab";
import { ActivityTab } from "./ActivityTab";
import { DepthChartsTab } from "./DepthChartsTab";
import { HandcuffsTab } from "./HandcuffsTab";
import { BenchPointsTab } from "./BenchPointsTab";
import { ExpertRankingsTab } from "./ExpertRankingsTab";

export function ExtraTab({ leagueId }: { leagueId: number }) {
  return (
    <>
      {/* Playoffs and Activity lead: they're the two that change a
          decision. Depth Charts and Expert Consensus stay last, where
          they were deliberately placed. */}
      <PlayoffOddsTab leagueId={leagueId} />
      <div style={{ marginTop: "1.25rem" }}>
        <ActivityTab leagueId={leagueId} />
      </div>
      <div style={{ marginTop: "1.25rem" }}>
        <HandcuffsTab leagueId={leagueId} />
      </div>
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
