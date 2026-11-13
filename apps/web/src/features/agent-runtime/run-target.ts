/**
 * Run routing is pure policy, kept apart from the capabilities query so the
 * header builder and the composer can share it without a React dependency or
 * query mocking.
 */

import type { AgentCapabilities } from '@/contracts/agent-capabilities'

/** Who serves a run. `unresolved` means the browser cannot prove any route works. */
export type RunRoute = 'fixtures' | 'byok' | 'server' | 'unresolved'

export interface RunTarget {
  ready: boolean
  fixtures: boolean
  route: RunRoute
  message: string
}

export interface RunTargetInput {
  capabilitiesError: boolean
  capabilities?: AgentCapabilities
  providerReadiness: { ready: boolean; message: string }
  activeProviderId: string | null
  /**
   * Whether this deployment can serve an engine run from its own configured
   * gateway with no `X-LLM-*` headers.
   *
   * `GET /api/agent/capabilities` does not report this yet, so callers pass
   * `undefined`. Unknown is not the same as "not configured": the run stays
   * unresolved instead of being promised and then failing mid-run. This is
   * the single input a contract addition has to fill.
   */
  serverGatewayConfigured?: boolean
}

const CONNECT_FAILED =
  'Cannot connect to the agent. Check the API connection and retry.'
const CHECKING = 'Checking agent availability…'
const FIXTURES_MESSAGE = 'Fixture mode — no provider required.'
const SERVER_GATEWAY_MESSAGE =
  "Server gateway — runs on this deployment's configured model."
const NO_SERVER_GATEWAY =
  'This deployment has no model gateway configured. Add a provider key in Settings → Providers.'
/**
 * Engine mode with an unknown gateway. Only the deployment's own configuration
 * decides this, so the copy names the action this browser can take without
 * claiming that a key is required or that the run will work.
 */
const SERVER_GATEWAY_UNKNOWN =
  'Add a provider key in Settings → Providers, or configure a model gateway on this deployment.'

/**
 * Resolves who serves a run, in precedence order: fixtures need no credentials,
 * an explicitly selected BYOK profile always wins over the server gateway, and
 * a confirmed server gateway runs without any `X-LLM-*` headers. Anything the
 * browser cannot verify stays unresolved, so the composer never promises a
 * route the next run cannot keep.
 */
export function resolveRunTarget(input: RunTargetInput): RunTarget {
  if (input.capabilitiesError) {
    return { ready: false, fixtures: false, route: 'unresolved', message: CONNECT_FAILED }
  }
  const capabilities = input.capabilities
  if (!capabilities) {
    return { ready: false, fixtures: false, route: 'unresolved', message: CHECKING }
  }
  if (capabilities.agent_mode === 'fixtures') {
    return { ready: true, fixtures: true, route: 'fixtures', message: FIXTURES_MESSAGE }
  }
  if (input.providerReadiness.ready) {
    return { ready: true, fixtures: false, route: 'byok', message: '' }
  }
  if (input.serverGatewayConfigured === true) {
    return { ready: true, fixtures: false, route: 'server', message: SERVER_GATEWAY_MESSAGE }
  }
  return {
    ready: false,
    fixtures: false,
    route: 'unresolved',
    message: input.activeProviderId
      ? input.providerReadiness.message
      : input.serverGatewayConfigured === false
        ? NO_SERVER_GATEWAY
        : SERVER_GATEWAY_UNKNOWN,
  }
}

/**
 * Only a resolved BYOK route carries browser-owned credentials. Fixture runs
 * never receive a key, and a server-gateway run bills the operator's
 * credentials, so the browser key is withheld from both.
 */
export function runTargetSendsProviderHeaders(target: RunTarget): boolean {
  return target.route === 'byok'
}

/** The label the composer shows for the run's serving route. */
export function runTargetLabel(target: RunTarget, byokLabel: string | null): string {
  switch (target.route) {
    case 'fixtures':
      return 'Fixture mode'
    case 'server':
      return 'Server gateway'
    case 'byok':
      return byokLabel ?? 'Provider default model'
    case 'unresolved':
      return 'Provider not set'
  }
}
