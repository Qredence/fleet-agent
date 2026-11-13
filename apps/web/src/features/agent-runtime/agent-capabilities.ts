import { queryOptions, useQuery } from '@tanstack/react-query'
import { z } from 'zod'

import type { AgentCapabilities } from '@/contracts/agent-capabilities'
import capabilityContract from '@fleet-agent/contracts/agent-capabilities.schema.json'
import { useProviders } from '@/features/providers/use-providers'
import { resolveRunTarget, type RunTarget } from '@/features/agent-runtime/run-target'
import { apiFetch } from '@/lib/api-client'
import { queryClient } from '@/lib/query-client'

// Strict on purpose: an unexpected capability shape must fail closed rather
// than silently change run behavior.
const capabilitySchema = z.object({
  supported_content_types: z.tuple([z.literal('text')]),
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

/**
 * Run readiness is distinct from the credential readiness displayed in
 * provider settings.
 *
 * BLOCKED on a contract addition: `GET /api/agent/capabilities` reports only
 * the agent mode, so `serverGatewayConfigured` is passed as `undefined` here
 * and an engine run without a BYOK profile stays unresolved. Once the server
 * reports whether it has its own gateway, read it and pass it here.
 */
export function useRunReadiness(): RunTarget {
  const capabilities = useQuery(agentCapabilitiesOptions, queryClient)
  const { readiness, activeProviderId } = useProviders()
  return resolveRunTarget({
    capabilitiesError: capabilities.isError,
    capabilities: capabilities.data,
    providerReadiness: readiness,
    activeProviderId,
    serverGatewayConfigured: undefined,
  })
}
