/**
 * One wire format for a duration in milliseconds.
 *
 * The same value surfaces in the conversation, the process panel and inline
 * tool cards. Three local copies had drifted apart, so identical data read
 * differently depending on where it appeared. Keep every duration render on
 * this function.
 *
 *   undefined/null -> "—"
 *   < 1000         -> "250ms"
 *   < 60000        -> "12.5s"   (one decimal)
 *   >= 60000       -> "2m 5s"
 */
export function formatDuration(ms: number | undefined | null): string {
  if (ms == null) return "—";
  if (ms < 1000) return `${ms}ms`;
  if (ms < 60000) return `${(ms / 1000).toFixed(1)}s`;
  const minutes = Math.floor(ms / 60000);
  const seconds = Math.floor((ms % 60000) / 1000);
  return `${minutes}m ${seconds}s`;
}
