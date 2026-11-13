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
 *   < 59950        -> "12.5s"   (one decimal)
 *   >= 59950       -> "2m 5s"
 *
 * The minute boundary sits at 59950ms, not 60000ms, because the seconds branch
 * rounds to one decimal: 59.96s would otherwise print "60.0s" and then jump to
 * "1m 0s" one millisecond later. Rounding the total to whole seconds here keeps
 * the reading monotonic across the switch.
 */
export function formatDuration(ms: number | undefined | null): string {
  if (ms == null) return "—";
  if (ms < 1000) return `${ms}ms`;
  if (ms < 59950) return `${(ms / 1000).toFixed(1)}s`;
  const totalSeconds = Math.round(ms / 1000);
  return `${Math.floor(totalSeconds / 60)}m ${totalSeconds % 60}s`;
}
