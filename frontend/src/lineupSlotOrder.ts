// Starting lineup slots in a fixed, human-friendly order: QB, RB, RB, WR,
// WR, TE, Flex, Def, K — shared by the Roster and Start/Sit tabs so a
// league's starters read the same way in both places. Anything not listed
// (rare hybrid slots like "OP" or "RB/WR") falls in just after its nearest
// match; unrecognized slots sort last.
export const STARTER_SLOT_ORDER: Record<string, number> = {
  QB: 0,
  RB: 1,
  "RB/WR": 2,
  WR: 3,
  "WR/TE": 4,
  TE: 5,
  OP: 6,
  FLEX: 7,
  "D/ST": 8,
  K: 9,
};

export function starterSlotRank(slot: string): number {
  return STARTER_SLOT_ORDER[slot] ?? 99;
}
