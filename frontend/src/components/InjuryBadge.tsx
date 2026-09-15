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

/** Nothing for a healthy/unlisted player; a severity-colored badge otherwise
 * — Questionable often clears by kickoff, Doubtful rarely does, Out/IR/
 * Suspension definitely won't, and treating all three as the same red
 * badge buries that distinction. */
export function InjuryBadge({ status }: { status: string }) {
  if (!status || status === "ACTIVE") return null;
  return <span className={`badge ${SEVERITY_CLASS[status] ?? "injury-out"}`}>{LABEL[status] ?? status}</span>;
}
