import type { FantasyProsInjury } from "../types";

const SEVERITY_CLASS: Record<string, string> = {
  QUESTIONABLE: "injury-questionable",
  DOUBTFUL: "injury-doubtful",
  OUT: "injury-out",
  INJURY_RESERVE: "injury-out",
  SUSPENSION: "injury-out",
};

const LABEL: Record<string, string> = {
  INJURY_RESERVE: "IR",
  SUSPENSION: "SUSP",
};

function fpTooltip(fpInjury: FantasyProsInjury): string {
  const parts: string[] = [];
  if (fpInjury.probability_of_playing != null) {
    parts.push(`${Math.round(fpInjury.probability_of_playing * 100)}% chance of playing`);
  }
  if (fpInjury.practice_report.length) {
    parts.push(`Practice: ${fpInjury.practice_report.join(" → ")}`);
  }
  if (fpInjury.comment) {
    parts.push(fpInjury.comment);
  }
  return parts.join(" — ");
}

/** Nothing for a healthy/unlisted player; a severity-colored badge otherwise
 * — Questionable often clears by kickoff, Doubtful rarely does, Out/IR/
 * Suspension definitely won't, and treating all three as the same red
 * badge buries that distinction. When FantasyPros has richer context (a
 * probability-of-playing estimate, this week's practice participation, an
 * analyst's comment) than ESPN's bare status string, it's surfaced as a
 * tooltip rather than more on-page clutter. */
export function InjuryBadge({ status, fpInjury }: { status: string; fpInjury?: FantasyProsInjury | null }) {
  if (!status || status === "ACTIVE") return null;
  const title = fpInjury ? fpTooltip(fpInjury) : undefined;
  return (
    <span className={`badge ${SEVERITY_CLASS[status] ?? "injury-out"}`} title={title || undefined}>
      {LABEL[status] ?? status}
    </span>
  );
}
