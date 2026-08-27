import { useSyncExternalStore } from 'react'

export function useMediaQuery(query: string): boolean {
  return useSyncExternalStore(
    (onStoreChange) => {
      const mql = window.matchMedia(query)
      mql.addEventListener('change', onStoreChange)
      return () => mql.removeEventListener('change', onStoreChange)
    },
    () => window.matchMedia(query).matches,
    () => false,
  )
}

/**
 * Below 781px: both side panels become sheets. Derived from the desktop
 * layout's content minimum — 220px (project sidebar) + 1px (resize handle)
 * + 560px (conversation min) = 781px — so the sheet layout engages just
 * before the resizable panel minimums stop fitting.
 */
export function useIsMobile(): boolean {
  return useMediaQuery('(max-width: 780px)')
}

/** Below 1200px: the process panel becomes a sheet. */
export function useIsCompact(): boolean {
  return useMediaQuery('(max-width: 1199px)')
}
