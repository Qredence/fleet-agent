import { createContext, useContext, type ReactNode } from 'react'

/**
 * Marks that an AG-UI runtime (and its AuiProvider) is mounted above the
 * consumer. `AgentRuntimeProvider` provides this; preview routes
 * (/tools, /optimizer, /connectors) render the workspace shell without a
 * runtime, and AG-UI hooks throw `requires an AuiProvider` without one.
 */
const AgUiRuntimePresenceContext = createContext(false)

export function AgUiRuntimePresenceProvider({
  children,
}: {
  children: ReactNode
}) {
  return (
    <AgUiRuntimePresenceContext.Provider value={true}>
      {children}
    </AgUiRuntimePresenceContext.Provider>
  )
}

export function useHasAgUiRuntime(): boolean {
  return useContext(AgUiRuntimePresenceContext)
}
