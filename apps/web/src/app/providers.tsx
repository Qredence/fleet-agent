import { QueryClientProvider } from '@tanstack/react-query'
import { useEffect, type ReactNode } from 'react'

import { queryClient } from '@/lib/query-client'
import { applyTheme, useWorkspaceStore } from '@/state/workspace-store'

/**
 * Provides application-wide data fetching and theme management to child components.
 *
 * @param children - The components rendered within the providers
 * @returns The children wrapped with the query client provider
 */
export function AppProviders({ children }: { children: ReactNode }) {
  const theme = useWorkspaceStore((s) => s.theme)

  useEffect(() => {
    applyTheme(theme)

    if (theme === 'system') {
      const media = window.matchMedia('(prefers-color-scheme: dark)')
      const listener = () => applyTheme('system')
      media.addEventListener('change', listener)
      return () => media.removeEventListener('change', listener)
    }
  }, [theme])

  return <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
}
