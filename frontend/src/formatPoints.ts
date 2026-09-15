// Projected points are stored/sorted at full precision, but reading
// "14.32 pts" adds noise without adding useful signal for a projection —
// display them rounded to the nearest whole number everywhere.
export function formatPoints(value: number | null | undefined): string {
  return value == null ? "-" : String(Math.round(value));
}
