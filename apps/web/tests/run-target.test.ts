import { describe, expect, it } from 'vitest'

import type { AgentCapabilities } from '@/contracts/agent-capabilities'
import {
  resolveRunTarget,
  runTargetLabel,
  runTargetSendsProviderHeaders,
  type RunTargetInput,
} from '@/features/agent-runtime/run-target'

const NOT_READY = { ready: false, message: 'Choose a provider in Settings → Providers before sending a message.' }
const READY = { ready: true, message: '' }
const ENGINE: AgentCapabilities = { agent_mode: 'engine', supported_content_types: ['text'] }
const FIXTURES: AgentCapabilities = { agent_mode: 'fixtures', supported_content_types: ['text'] }

function input(overrides: Partial<RunTargetInput> = {}): RunTargetInput {
  return {
    capabilitiesError: false,
    capabilities: ENGINE,
    providerReadiness: NOT_READY,
    activeProviderId: null,
    ...overrides,
  }
}

describe('run target precedence', () => {
  it('runs on the server gateway with no browser provider and withholds X-LLM headers', () => {
    const target = resolveRunTarget(input({ serverGatewayConfigured: true }))
    expect(target).toEqual({
      ready: true,
      fixtures: false,
      route: 'server',
      message: "Server gateway — runs on this deployment's configured model.",
    })
    expect(runTargetSendsProviderHeaders(target)).toBe(false)
    expect(runTargetLabel(target, null)).toBe('Server gateway')
  })

  it('lets a selected BYOK profile win over a configured server gateway', () => {
    const target = resolveRunTarget(
      input({ providerReadiness: READY, activeProviderId: 'openrouter', serverGatewayConfigured: true }),
    )
    expect(target.route).toBe('byok')
    expect(runTargetSendsProviderHeaders(target)).toBe(true)
    expect(runTargetLabel(target, 'GPT-4o mini')).toBe('GPT-4o mini')
  })

  it('stays unresolved when the gateway is unknown instead of promising a run', () => {
    const target = resolveRunTarget(input())
    expect(target.ready).toBe(false)
    expect(target.route).toBe('unresolved')
    expect(runTargetSendsProviderHeaders(target)).toBe(false)
    expect(target.message).toContain('configure a model gateway')
  })

  it('reports a server without a gateway as needing a key', () => {
    const target = resolveRunTarget(input({ serverGatewayConfigured: false }))
    expect(target.ready).toBe(false)
    expect(target.message).toContain('no model gateway configured')
  })

  it('keeps fixture mode credential-free regardless of gateway state', () => {
    for (const serverGatewayConfigured of [true, false, undefined]) {
      const target = resolveRunTarget(
        input({ capabilities: FIXTURES, providerReadiness: READY, serverGatewayConfigured }),
      )
      expect(target).toEqual({
        ready: true,
        fixtures: true,
        route: 'fixtures',
        message: 'Fixture mode — no provider required.',
      })
      expect(runTargetSendsProviderHeaders(target)).toBe(false)
      expect(runTargetLabel(target, 'GPT-4o mini')).toBe('Fixture mode')
    }
  })

  it('is not ready while the capabilities lookup fails', () => {
    const target = resolveRunTarget(
      input({ capabilitiesError: true, capabilities: undefined, serverGatewayConfigured: true }),
    )
    expect(target.ready).toBe(false)
    expect(target.message).toContain('Cannot connect')
  })
})
