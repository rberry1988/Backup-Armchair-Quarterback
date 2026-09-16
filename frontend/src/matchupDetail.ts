/** Turns a matchup rating into the sentence behind it.
 *
 * "Tough matchup" on its own is an assertion; this is the evidence for it —
 * what this defense actually gives up to this position, how that compares
 * to the rest of the league, and where it ranks. See
 * backend/app/matchup.py for where the numbers come from.
 */

import type { MatchupContext } from "./types";

function ordinal(n: number): string {
  const rem100 = n % 100;
  if (rem100 >= 11 && rem100 <= 13) return `${n}th`;
  return `${n}${["th", "st", "nd", "rd"][n % 10] ?? "th"}`;
}

/** One decimal, always. These numbers sit side by side in a sentence, and
 * "5 pts/gm ... 8 league average" next to "16.3" reads like a different
 * kind of measurement rather than the same one with a round value. */
function fmt(n: number): string {
  return n.toFixed(1);
}

function plural(position: string | null | undefined): string {
  if (!position) return "this position";
  // D/ST and K read badly pluralised; the rest are fine.
  return position === "D/ST" || position === "K" ? position : `${position}s`;
}

export function matchupDetail(matchup: MatchupContext | null): string | null {
  if (!matchup) return null;

  const { label, opponent, defense_rank: rank, defense_teams_ranked: total, value, league_average: avg } = matchup;
  const tough = label === "tough matchup";
  const favorable = label === "favorable matchup";

  // Older payloads (and anything synced before these numbers existed)
  // carry only the rating, so fall back to what can honestly be said.
  if (value == null) {
    return `${opponent} ranks ${ordinal(rank)} of ${total} against ${plural(matchup.position)}.`;
  }

  if (matchup.source === "dst_projection") {
    // The fallback rating: an opponent's own projected D/ST score as a
    // stand-in for defensive strength. Worth labelling as the rougher
    // measure it is rather than dressing it up.
    const placing = tough
      ? `${ordinal(rank)} strongest of ${total}`
      : favorable
        ? `${ordinal(total - rank + 1)} weakest of ${total}`
        : `${ordinal(rank)} of ${total}`;
    return `${opponent}'s defense is projected for ${fmt(value)} fantasy points this week — ${placing}. Rough estimate: no points-allowed data for them yet.`;
  }

  const scale = `${fmt(value)} pts/gm to ${plural(matchup.position)}`;
  // Built once so `avg` is narrowed alongside the gap derived from it, and
  // so a zero gap drops the clause rather than claiming "0.0 below".
  const gapFrom = (direction: "below" | "above"): string => {
    if (avg == null) return "";
    const gap = Math.abs(Math.round((value - avg) * 10) / 10);
    return gap > 0 ? `${fmt(gap)} ${direction} the ${fmt(avg)} league average, ` : "";
  };

  if (tough) {
    return `${opponent} allows ${scale} — ${gapFrom("below")}${ordinal(rank)} stingiest of ${total}.`;
  }
  if (favorable) {
    return `${opponent} allows ${scale} — ${gapFrom("above")}${ordinal(total - rank + 1)} most generous of ${total}.`;
  }
  return avg != null
    ? `${opponent} allows ${scale} — about the ${fmt(avg)} league average (${ordinal(rank)} of ${total}).`
    : `${opponent} allows ${scale} — ${ordinal(rank)} of ${total}.`;
}
