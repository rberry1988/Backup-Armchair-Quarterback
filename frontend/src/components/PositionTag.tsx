const POSITION_CLASS: Record<string, string> = {
  QB: "pos-qb",
  RB: "pos-rb",
  WR: "pos-wr",
  TE: "pos-te",
  K: "pos-k",
  "D/ST": "pos-dst",
  DST: "pos-dst",
};

export function PositionTag({ position }: { position: string }) {
  return <span className={`pos-chip ${POSITION_CLASS[position] ?? "pos-other"}`}>{position}</span>;
}
