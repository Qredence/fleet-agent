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

/** Below 768px: both side panels become sheets. */
export function useIsMobile(): boolean {
  return useMediaQuery('(max-width: 767px)')
}

/** Below 1200px: the process panel becomes a sheet. */
export function useIsCompact(): boolean {
  return useMediaQuery('(max-width: 1199px)')
}
