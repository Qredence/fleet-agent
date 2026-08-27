import { createContext, useContext, type ReactNode } from 'react'

/**
 * Marks that an AG-UI runtime (and its AuiProvider) is mounted above the
 * consumer. `AgentRuntimeProvider` provides this; preview routes
 * (/tools, /optimizer, /connectors) render the workspace shell without a
 * runtime, and AG-UI hooks throw `requires an AuiProvider` without one.
 */
const AgUiRuntimePresenceContext = createContext(false)

/**
 * Marks descendant components as having an AG-UI runtime available.
 *
 * @param children - The components rendered within the provider
 */
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

/**
 * Determines whether an AG-UI runtime is available to the consumer.
 *
 * @returns `true` if an AG-UI runtime is mounted above the consumer, `false` otherwise.
 */
export function useHasAgUiRuntime(): boolean {
  return useContext(AgUiRuntimePresenceContext)
}
