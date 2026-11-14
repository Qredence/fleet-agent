/**
 * One wire format for a byte size.
 *
 * File cards and the artifact list both print sizes. Two local copies had
 * drifted apart, so identical data could read differently depending on where
 * it appeared. Keep every size render on this function.
 *
 *   undefined/null -> null      (the caller decides, see below)
 *   < 1024         -> "512 B"   (exact bytes, no decimal)
 *   < 1024 * 1024  -> "2.0 KB"  (one decimal)
 *   >= 1024 * 1024 -> "1.5 MB"  (one decimal)
 *
 * A missing size returns null rather than "" or a dash because the artifact
 * row joins media type and size with " · " and must drop the separator
 * entirely when there is no size; a dash would instead read as "zero bytes".
 * A caller that always has a number can render the result directly.
 *
 * The unit is chosen from the rounded value, not the raw one, for the same
 * reason `formatDuration` switches to minutes at 59950ms: the kibibyte branch
 * rounds to one decimal, so 1048575 bytes would otherwise print "1024.0 KB"
 * and then jump to "1.0 MB" one byte later. Rounding first puts the boundary
 * at 1048525 bytes, where "1023.9 KB" becomes "1.0 MB".
 *
 * The scale stops at MB. Every real input is capped well below a gibibyte
 * (artifact previews at 64 KiB, request bodies at 1 MiB), so a GB branch would
 * be speculative.
 */
const KIB = 1024;
const MIB = 1024 * 1024;

export function formatByteSize(bytes: number | undefined | null): string | null {
  if (bytes == null) return null;
  if (bytes < KIB) return `${bytes} B`;
  const roundedKib = Number((bytes / KIB).toFixed(1));
  if (roundedKib < KIB) return `${roundedKib.toFixed(1)} KB`;
  return `${(bytes / MIB).toFixed(1)} MB`;
}
