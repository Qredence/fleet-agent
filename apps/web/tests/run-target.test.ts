import { describe, expect, it } from 'vitest'

import type { AgentCapabilities } from '@/contracts/agent-capabilities'
import {
  resolveRunTarget,
  runTargetLabel,
  runTargetSendsProviderHeaders,
  type RunTargetInput,
} from '@/features/agent-runtime/run-target'

const NOT_READY = { ready: false, message: 'OpenRouter needs setup. Add an API key and endpoint in Settings → Providers.' }
const READY = { ready: true, message: '' }

function capabilities(
  agentMode: 'engine' | 'fixtures',
  serverGatewayConfigured?: boolean,
): AgentCapabilities {
  return {
    agent_mode: agentMode,
    supported_content_types: ['text'],
    ...(serverGatewayConfigured === undefined ? {} : { server_gateway_configured: serverGatewayConfigured }),
  }
}

function input(overrides: Partial<RunTargetInput> = {}): RunTargetInput {
  return {
    capabilitiesError: false,
    capabilities: capabilities('engine', true),
    providerReadiness: NOT_READY,
    activeProviderId: null,
    ...overrides,
  }
}

describe('run target precedence', () => {
  it('runs on the server gateway with no browser provider and withholds X-LLM headers', () => {
    const target = resolveRunTarget(input())
    expect(target).toEqual({
      ready: true,
      fixtures: false,
      route: 'server',
      reason: 'server',
      message: "Server gateway — runs on this deployment's configured model.",
    })
    expect(runTargetSendsProviderHeaders(target)).toBe(false)
    expect(runTargetLabel(target, null)).toBe('Server gateway')
  })

  it('lets a selected BYOK profile win over a configured server gateway', () => {
    const target = resolveRunTarget(
      input({ providerReadiness: READY, activeProviderId: 'openrouter' }),
    )
    expect(target.route).toBe('byok')
    expect(runTargetSendsProviderHeaders(target)).toBe(true)
    expect(runTargetLabel(target, 'GPT-4o mini')).toBe('GPT-4o mini')
  })

  it('keeps an explicitly selected profile that needs setup off the deployment gateway', () => {
    // The user chose their own provider; a missing key must not silently move
    // the run onto the operator's credentials.
    const target = resolveRunTarget(input({ activeProviderId: 'openrouter' }))
    expect(target.ready).toBe(false)
    expect(target.route).toBe('unresolved')
    expect(target.reason).toBe('provider_needs_setup')
    expect(target.message).toContain('OpenRouter needs setup')
    expect(runTargetSendsProviderHeaders(target)).toBe(false)
  })

  it('stays unresolved when an older server omits the gateway field', () => {
    const target = resolveRunTarget(input({ capabilities: capabilities('engine') }))
    expect(target.ready).toBe(false)
    expect(target.route).toBe('unresolved')
    expect(target.reason).toBe('server_gateway_unknown')
    expect(runTargetSendsProviderHeaders(target)).toBe(false)
    expect(target.message).toContain('configure a model gateway')
  })

  it('reports a server without a gateway as needing a key', () => {
    const target = resolveRunTarget(input({ capabilities: capabilities('engine', false) }))
    expect(target.ready).toBe(false)
    expect(target.reason).toBe('no_server_gateway')
    expect(target.message).toContain('no model gateway configured')
  })

  it('keeps fixture mode credential-free regardless of gateway state', () => {
    for (const serverGatewayConfigured of [true, false, undefined]) {
      const target = resolveRunTarget(
        input({
          capabilities: capabilities('fixtures', serverGatewayConfigured),
          providerReadiness: READY,
        }),
      )
      expect(target).toEqual({
        ready: true,
        fixtures: true,
        route: 'fixtures',
        reason: 'fixtures',
        message: 'Fixture mode — no provider required.',
      })
      expect(runTargetSendsProviderHeaders(target)).toBe(false)
      expect(runTargetLabel(target, 'GPT-4o mini')).toBe('Fixture mode')
    }
  })

  it('is not ready while the capabilities lookup fails', () => {
    const target = resolveRunTarget(
      input({ capabilitiesError: true, capabilities: undefined }),
    )
    expect(target.ready).toBe(false)
    expect(target.reason).toBe('capabilities_unavailable')
    expect(target.message).toContain('Cannot connect')
  })
})

describe('run target labels', () => {
  it('never presents a loading or unreachable agent as a missing provider', () => {
    const checking = resolveRunTarget(input({ capabilities: undefined }))
    const unavailable = resolveRunTarget(input({ capabilitiesError: true, capabilities: undefined }))
    const noProvider = resolveRunTarget(input({ capabilities: capabilities('engine', false) }))
    const needsSetup = resolveRunTarget(input({ activeProviderId: 'openrouter' }))

    const labels = [checking, unavailable, noProvider, needsSetup].map((target) =>
      runTargetLabel(target, 'GPT-4o mini'),
    )
    expect(new Set(labels).size).toBe(4)
    expect(runTargetLabel(checking, null)).toBe('Checking agent…')
    expect(runTargetLabel(unavailable, null)).toBe('Agent unavailable')
    expect(runTargetLabel(needsSetup, null)).toBe('Provider needs setup')
    expect(runTargetLabel(noProvider, null)).toBe('Provider not set')
  })
})
