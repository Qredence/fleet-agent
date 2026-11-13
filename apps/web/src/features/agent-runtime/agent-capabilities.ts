import { queryOptions, useQuery } from '@tanstack/react-query'
import { z } from 'zod'

import type { AgentCapabilities } from '@/contracts/agent-capabilities'
import capabilityContract from '@fleet-agent/contracts/agent-capabilities.schema.json'
import { useProviders } from '@/features/providers/use-providers'
import { resolveRunTarget, type RunTarget } from '@/features/agent-runtime/run-target'
import { apiFetch } from '@/lib/api-client'
import { queryClient } from '@/lib/query-client'

// Strict on purpose: an unexpected capability shape must fail closed rather
// than silently change run behavior. `server_gateway_configured` is optional
// in the contract, so a server that omits it leaves routing unknown, which
// keeps the composer failing closed instead of guessing a route.
const capabilitySchema = z.object({
  supported_content_types: z.tuple([z.literal('text')]),
  agent_mode: z.enum(capabilityContract.properties.agent_mode.enum as ['fixtures', 'engine']),
  server_gateway_configured: z.boolean().optional(),
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

/**
 * Run readiness is distinct from the credential readiness displayed in
 * provider settings. It carries the deployment's own gateway capability, so an
 * engine deployment that is already configured can run with no browser key.
 */
export function useRunReadiness(): RunTarget {
  const capabilities = useQuery(agentCapabilitiesOptions, queryClient)
  const { readiness, activeProviderId } = useProviders()
  return resolveRunTarget({
    capabilitiesError: capabilities.isError,
    capabilities: capabilities.data,
    providerReadiness: readiness,
    activeProviderId,
  })
}
