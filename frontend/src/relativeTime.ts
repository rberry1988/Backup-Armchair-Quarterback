/** "3h ago" / "just now" style label for a sync freshness indicator.
 * Assumes a naive ISO timestamp without a zone (this app's synced_at
 * values come straight from Python's isoformat()) is UTC. */
export function formatRelativeTime(iso: string | null | undefined): string | null {
  if (!iso) return null;
  const parsed = new Date(iso.endsWith("Z") || iso.includes("+") ? iso : `${iso}Z`);
  const ms = Date.now() - parsed.getTime();
  if (Number.isNaN(ms)) return null;
  if (ms < 0) return "just now";

  const minutes = Math.floor(ms / 60000);
  if (minutes < 1) return "just now";
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  return `${days}d ago`;
}
