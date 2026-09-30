import { queryOptions, useQuery } from '@tanstack/react-query'
import { z } from 'zod'

import type { AgentCapabilities } from '@/contracts/agent-capabilities'
import capabilityContract from '@fleet-agent/contracts/agent-capabilities.schema.json'
import { useProviders } from '@/features/providers/use-providers'
import { apiFetch } from '@/lib/api-client'
import { queryClient } from '@/lib/query-client'

const capabilitySchema = z.object({
  agent_mode: z.enum(capabilityContract.properties.agent_mode.enum as ['fixtures', 'engine']),
}).strict()

export const agentCapabilitiesOptions = queryOptions({
  queryKey: ['agent-capabilities'],
  queryFn: async (): Promise<AgentCapabilities> =>
    capabilitySchema.parse(await apiFetch<unknown>('/api/agent/capabilities')),
  staleTime: 30_000,
  retry: false,
})

/** Refresh the server's mode before each run; cached fixture mode cannot bypass engine setup. */
export function refreshAgentCapabilities(): Promise<AgentCapabilities> {
  return queryClient.fetchQuery({ ...agentCapabilitiesOptions, staleTime: 0 })
}

/** Run readiness is distinct from the credential readiness displayed in provider settings. */
export function useRunReadiness() {
  const capabilities = useQuery(agentCapabilitiesOptions, queryClient)
  const { readiness } = useProviders()
  if (capabilities.isError) {
    return { ready: false, fixtures: false, message: 'Cannot connect to the agent. Check the API connection and retry.' }
  }
  if (!capabilities.data) {
    return { ready: false, fixtures: false, message: 'Checking agent availability…' }
  }
  if (capabilities.data.agent_mode === 'fixtures') {
    return { ready: true, fixtures: true, message: 'Fixture mode — no provider required.' }
  }
  return { ...readiness, fixtures: false }
}
