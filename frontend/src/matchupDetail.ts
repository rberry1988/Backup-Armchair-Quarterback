/** Turns a matchup rating into the sentence behind it.
 *
 * "Tough matchup" on its own is an assertion; this is the evidence for it —
 * what this defense actually gives up to this position per game, how that
 * compares to the rest of the league, and where it ranks.
 *
 * The numbers are real yardage wherever possible (rushing yards to RBs,
 * receiving to WRs and TEs, passing to QBs), not fantasy points: explaining
 * a points projection with points allowed is circular, and yardage is the
 * thing the projection is itself derived from. See backend/app/matchup.py
 * and backend/app/advanced_stats.py.
 */

import type { MatchupContext } from "./types";

function ordinal(n: number): string {
  const rem100 = n % 100;
  if (rem100 >= 11 && rem100 <= 13) return `${n}th`;
  return `${n}${["th", "st", "nd", "rd"][n % 10] ?? "th"}`;
}

/** Yardage reads as whole numbers; rates and points want a decimal. */
function fmt(n: number, decimals: number): string {
  return n.toFixed(decimals);
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
    // The weakest rating: an opponent's own projected D/ST score standing
    // in for defensive strength. Worth labelling as the guess it is.
    const placing = tough
      ? `${ordinal(rank)} strongest of ${total}`
      : favorable
        ? `${ordinal(total - rank + 1)} weakest of ${total}`
        : `${ordinal(rank)} of ${total}`;
    return `${opponent}'s defense is projected for ${fmt(value, 1)} fantasy points this week — ${placing}. Rough estimate: no real defensive data for them yet.`;
  }

  // Whole yards, one decimal for anything else.
  const decimals = matchup.source === "yards_allowed" ? 0 : 1;
  const unit = matchup.metric ?? "pts";
  const scale = `${fmt(value, decimals)} ${unit}/gm to ${plural(matchup.position)}`;

  // Built once so `avg` is narrowed alongside the gap derived from it, and
  // so a zero gap drops the clause rather than claiming "0 below".
  const gapFrom = (direction: "below" | "above"): string => {
    if (avg == null) return "";
    const gap = Math.abs(value - avg);
    const shown = fmt(gap, decimals);
    return Number(shown) > 0 ? `${shown} ${direction} the ${fmt(avg, decimals)} league average, ` : "";
  };

  // TDs allowed add the part yardage misses: a defense can bend between the
  // 20s and still not concede, or vice versa. Only worth saying when it
  // actually differs from the league norm.
  const tdNote = (): string => {
    const { tds, tds_league_average: tdAvg } = matchup;
    if (tds == null || tdAvg == null || tdAvg === 0) return "";
    const ratio = tds / tdAvg;
    if (ratio >= 1.25) return ` They also give up more TDs than most (${fmt(tds, 1)}/gm vs ${fmt(tdAvg, 1)} average).`;
    if (ratio <= 0.75) return ` They also concede few TDs (${fmt(tds, 1)}/gm vs ${fmt(tdAvg, 1)} average).`;
    return "";
  };

  if (tough) {
    return `${opponent} allows ${scale} — ${gapFrom("below")}${ordinal(rank)} stingiest of ${total}.${tdNote()}`;
  }
  if (favorable) {
    return `${opponent} allows ${scale} — ${gapFrom("above")}${ordinal(total - rank + 1)} most generous of ${total}.${tdNote()}`;
  }
  return avg != null
    ? `${opponent} allows ${scale} — about the ${fmt(avg, decimals)} league average (${ordinal(rank)} of ${total}).${tdNote()}`
    : `${opponent} allows ${scale} — ${ordinal(rank)} of ${total}.${tdNote()}`;
}
