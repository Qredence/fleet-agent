/**
 * Run routing is pure policy, kept apart from the capabilities query so the
 * header builder and the composer can share it without a React dependency or
 * query mocking.
 */

import type { AgentCapabilities } from '@/contracts/agent-capabilities'

/** Who serves a run. `unresolved` means the browser cannot prove any route works. */
export type RunRoute = 'fixtures' | 'byok' | 'server' | 'unresolved'

/**
 * Why a target is in its state. `route` alone cannot separate a run that is
 * still loading from one whose connection failed from one that needs a
 * provider, and the trigger label must never present the first two as the
 * third.
 */
export type RunReason =
  | 'fixtures'
  | 'byok'
  | 'server'
  | 'checking'
  | 'capabilities_unavailable'
  | 'provider_needs_setup'
  | 'no_server_gateway'
  | 'server_gateway_unknown'

export interface RunTarget {
  ready: boolean
  fixtures: boolean
  route: RunRoute
  reason: RunReason
  message: string
}

export interface RunTargetInput {
  capabilitiesError: boolean
  capabilities?: AgentCapabilities
  providerReadiness: { ready: boolean; message: string }
  activeProviderId: string | null
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
 * Resolves who serves a run, in precedence order: fixtures need no credentials;
 * an explicitly selected BYOK profile always wins, including when that profile
 * still needs setup; and a deployment whose capabilities report a gateway
 * serves runs that have no profile selected, without any `X-LLM-*` headers.
 *
 * `server_gateway_configured` is optional in the contract, so an older server
 * that omits it leaves the value unknown. Unknown is not "not configured": the
 * route stays unresolved rather than being promised and failing mid-run.
 */
export function resolveRunTarget(input: RunTargetInput): RunTarget {
  if (input.capabilitiesError) {
    return {
      ready: false,
      fixtures: false,
      route: 'unresolved',
      reason: 'capabilities_unavailable',
      message: CONNECT_FAILED,
    }
  }
  const capabilities = input.capabilities
  if (!capabilities) {
    return {
      ready: false,
      fixtures: false,
      route: 'unresolved',
      reason: 'checking',
      message: CHECKING,
    }
  }
  if (capabilities.agent_mode === 'fixtures') {
    return {
      ready: true,
      fixtures: true,
      route: 'fixtures',
      reason: 'fixtures',
      message: FIXTURES_MESSAGE,
    }
  }
  if (input.providerReadiness.ready) {
    return { ready: true, fixtures: false, route: 'byok', reason: 'byok', message: '' }
  }
  // An explicitly selected profile owns the run even when it cannot serve one.
  // Falling through to the deployment gateway would keep Settings showing that
  // profile as active while the run quietly spent the operator's credentials.
  if (input.activeProviderId) {
    return {
      ready: false,
      fixtures: false,
      route: 'unresolved',
      reason: 'provider_needs_setup',
      message: input.providerReadiness.message,
    }
  }
  if (capabilities.server_gateway_configured === true) {
    return {
      ready: true,
      fixtures: false,
      route: 'server',
      reason: 'server',
      message: SERVER_GATEWAY_MESSAGE,
    }
  }
  return {
    ready: false,
    fixtures: false,
    route: 'unresolved',
    reason:
      capabilities.server_gateway_configured === false
        ? 'no_server_gateway'
        : 'server_gateway_unknown',
    message:
      capabilities.server_gateway_configured === false
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

/**
 * The label the composer shows for the run's serving route. Each unresolved
 * cause keeps its own label so a loading query or an unreachable API never
 * reads as a missing provider.
 */
export function runTargetLabel(target: RunTarget, byokLabel: string | null): string {
  switch (target.reason) {
    case 'fixtures':
      return 'Fixture mode'
    case 'server':
      return 'Server gateway'
    case 'byok':
      return byokLabel ?? 'Provider default model'
    case 'provider_needs_setup':
      return 'Provider needs setup'
    case 'checking':
      return 'Checking agent…'
    case 'capabilities_unavailable':
      return 'Agent unavailable'
    case 'no_server_gateway':
      return 'Provider not set'
    case 'server_gateway_unknown':
      // An older server that omits the flag. Naming a provider would assert
      // the gateway is absent when it is only unknown, so this states the
      // missing information instead.
      return 'Gateway unknown'
  }
}
