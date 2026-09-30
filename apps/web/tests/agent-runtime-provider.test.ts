import { refreshAgentCapabilities } from '@/features/agent-runtime/agent-capabilities'
import { beforeEach, afterEach, describe, expect, it, vi } from 'vitest'

import { createAgentFetch } from '@/features/agent-runtime/agent-runtime-provider'
import {
  clearApiKey,
  setApiKey,
  setCustomModelEnabled,
  setSelectedModel,
} from '@/features/providers/openrouter-auth'

import { setActiveProviderId } from '@/features/providers/providers-store'

vi.mock('@/features/agent-runtime/agent-capabilities', () => ({
  refreshAgentCapabilities: vi.fn(),
}))
beforeEach(() => {
  vi.mocked(refreshAgentCapabilities).mockReset().mockResolvedValue({ agent_mode: 'engine' })
})

afterEach(() => {
  localStorage.clear()
  vi.restoreAllMocks()
})

describe('agent request provider headers', () => {
  it('sends BYOK and the selected model only to /api/agent', async () => {
    setApiKey('sk-or-browser')
    setActiveProviderId('openrouter')
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

  it('keeps the provider default model when custom selection is disabled', async () => {
    setApiKey('sk-or-browser')
    setActiveProviderId('openrouter')
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
  it('blocks every agent POST while unselected or disconnected, including repeated queued and regenerated requests', async () => {
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response('{}'))
    const fetchAgent = createAgentFetch()
    for (const body of ['{"runId":"send"}', '{"runId":"regenerate"}', '{"runId":"queued"}']) {
      await expect(fetchAgent('http://localhost:8000/api/agent', { method: 'POST', body })).rejects.toThrow(/Choose a provider/)
    }
    expect(fetchMock).not.toHaveBeenCalled()
    setApiKey('test-key')
    setActiveProviderId('openrouter')
    await fetchAgent('http://localhost:8000/api/agent', {method: 'POST'})
    clearApiKey()
    await expect(fetchAgent('http://localhost:8000/api/agent', {method: 'POST'})).rejects.toThrow(/needs setup/)
    expect(fetchMock).toHaveBeenCalledTimes(1)
    await fetchAgent('http://localhost:8000/api/projects', {method: 'GET'})
    expect(fetchMock).toHaveBeenCalledTimes(2)
  })

})


it('omits stored and supplied provider headers for fixture sends and refreshes before regeneration', async () => {
  setApiKey('seeded-key')
  setActiveProviderId('openrouter')
  vi.mocked(refreshAgentCapabilities).mockResolvedValueOnce({ agent_mode: 'fixtures' })
  const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response('{}'))
  const send = createAgentFetch()
  await send('http://localhost:8000/api/agent', { method: 'POST', headers: { 'X-LLM-Key': 'supplied-key', 'X-LLM-Model': 'supplied-model' } })
  const headers = new Headers(fetchMock.mock.calls[0]?.[1]?.headers)
  expect([...headers.keys()].some((key) => key.startsWith('x-llm-'))).toBe(false)
  clearApiKey()
  await expect(send('http://localhost:8000/api/agent', { method: 'POST', body: '{"runId":"regenerate"}' })).rejects.toThrow(/needs setup/)
  expect(refreshAgentCapabilities).toHaveBeenCalledTimes(2)
  expect(fetchMock).toHaveBeenCalledTimes(1)
})

it('blocks the POST when capability lookup fails', async () => {
  vi.mocked(refreshAgentCapabilities).mockRejectedValueOnce(new Error('API unavailable'))
  const fetchMock = vi.spyOn(globalThis, 'fetch')
  await expect(createAgentFetch()('http://localhost:8000/api/agent', { method: 'POST' })).rejects.toThrow('API unavailable')
  expect(fetchMock).not.toHaveBeenCalled()
})
