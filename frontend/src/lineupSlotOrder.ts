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

/** The fields the lineup ordering depends on — satisfied by both a roster
 * row and the Trade Grader's player-picker entries. */
export interface SlottedPlayer {
  slot: string;
  is_starter: boolean;
  projected_points: number | null;
}

/** Starters first in lineup-slot order (ties inside a duplicated slot, e.g.
 * both RB spots, broken by projected points), then bench by projected
 * points. Shared so every tab lists a roster the same way. */
export function byLineupOrder<T extends SlottedPlayer>(players: T[]): T[] {
  const byProjDesc = (a: T, b: T) => (b.projected_points ?? -Infinity) - (a.projected_points ?? -Infinity);
  const starters = players
    .filter((p) => p.is_starter)
    .sort((a, b) => {
      const rankDiff = starterSlotRank(a.slot) - starterSlotRank(b.slot);
      return rankDiff !== 0 ? rankDiff : byProjDesc(a, b);
    });
  const bench = players.filter((p) => !p.is_starter).sort(byProjDesc);
  return [...starters, ...bench];
}
