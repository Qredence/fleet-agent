import { afterEach, describe, expect, it, vi } from 'vitest'

import { createAgentFetch } from '@/features/agent-runtime/agent-runtime-provider'
import {
  setApiKey,
  setCustomModelEnabled,
  setSelectedModel,
} from '@/lib/openrouter-auth'

afterEach(() => {
  localStorage.clear()
  vi.restoreAllMocks()
})

describe('agent request provider headers', () => {
  it('sends BYOK and the selected model only to /api/agent', async () => {
    setApiKey('sk-or-browser')
    setSelectedModel('anthropic/claude-3.5-sonnet')
    setCustomModelEnabled(true)
    const fetchMock = vi
      .spyOn(globalThis, 'fetch')
      .mockResolvedValue(new Response('{}', { status: 200 }))
    const fetchAgent = createAgentFetch()

    await fetchAgent('http://localhost:8000/api/agent', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
    })
    await fetchAgent('http://localhost:8000/api/threads/thread-1', {
      method: 'GET',
    })

    const agentHeaders = new Headers(fetchMock.mock.calls[0]?.[1]?.headers)
    expect(agentHeaders.get('X-LLM-Key')).toBe('sk-or-browser')
    expect(agentHeaders.get('X-LLM-Base-Url')).toBe('https://openrouter.ai/api/v1')
    expect(agentHeaders.get('X-LLM-Model')).toBe('anthropic/claude-3.5-sonnet')
    expect(agentHeaders.get('X-LLM-Response-Format')).toBe(
      'native_function_calling',
    )
    expect(agentHeaders.get('X-LLM-Messages-Format')).toBe('system_role')
    const genericHeaders = new Headers(fetchMock.mock.calls[1]?.[1]?.headers)
    expect(genericHeaders.get('X-LLM-Key')).toBeNull()
    expect(genericHeaders.get('X-LLM-Model')).toBeNull()
  })

  it('uses the server model when custom selection is disabled', async () => {
    setApiKey('sk-or-browser')
    setSelectedModel('anthropic/claude-3.5-sonnet')
    setCustomModelEnabled(false)
    const fetchMock = vi
      .spyOn(globalThis, 'fetch')
      .mockResolvedValue(new Response('{}', { status: 200 }))

    await createAgentFetch()('http://localhost:8000/api/agent?stream=1', {
      method: 'POST',
    })

    const headers = new Headers(fetchMock.mock.calls[0]?.[1]?.headers)
    expect(headers.get('X-LLM-Key')).toBe('sk-or-browser')
    expect(headers.get('X-LLM-Model')).toBeNull()
  })
})
