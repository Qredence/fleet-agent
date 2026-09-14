export const SURFACE_BG: Record<number, string> = {
  1: "bg-surface-1",
  2: "bg-surface-2",
  3: "bg-surface-3",
  4: "bg-surface-4",
  5: "bg-surface-5",
  6: "bg-surface-6",
  7: "bg-surface-7",
  8: "bg-surface-8",
};

export const SURFACE_SHADOW: Record<number, string> = {
  1: "shadow-surface-1",
  2: "shadow-surface-2",
  3: "shadow-surface-3",
  4: "shadow-surface-4",
  5: "shadow-surface-5",
  6: "shadow-surface-6",
  7: "shadow-surface-7",
  8: "shadow-surface-8",
};

/** Clamp a surface level into the 1-8 ladder the lookup tables cover. */
function level(value: number): number {
  return Math.round(Math.max(1, Math.min(8, value)));
}

/**
 * Generates background and shadow classes for the specified surface levels.
 *
 * @param bgLevel - The background surface level, clamped and rounded to a value from 1 through 8.
 * @param shadowLevel - The shadow surface level, clamped and rounded to a value from 1 through 8.
 * @returns The corresponding background and shadow CSS classes.
 */
export function surfaceClasses(bgLevel: number, shadowLevel: number = bgLevel): string {
  // Clamp before indexing: a fractional or out-of-range level would otherwise
  // render "undefined undefined".
  return `${SURFACE_BG[level(bgLevel)]} ${SURFACE_SHADOW[level(shadowLevel)]}`;
}
