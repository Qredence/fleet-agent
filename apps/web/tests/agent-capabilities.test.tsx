import { act, renderHook, waitFor } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import { refreshAgentCapabilities, useRunReadiness } from '@/features/agent-runtime/agent-capabilities'
import { queryClient } from '@/lib/query-client'

afterEach(() => {
  queryClient.clear()
  vi.restoreAllMocks()
  localStorage.clear()
})

it('refreshes cached fixture mode before the next run', async () => {
  const fetchMock = vi.spyOn(globalThis, 'fetch')
    .mockResolvedValueOnce(new Response('{"agent_mode":"fixtures"}'))
    .mockResolvedValueOnce(new Response('{"agent_mode":"engine"}'))
  expect(await refreshAgentCapabilities()).toEqual({ agent_mode: 'fixtures' })
  expect(await refreshAgentCapabilities()).toEqual({ agent_mode: 'engine' })
  expect(fetchMock).toHaveBeenCalledTimes(2)
  expect(fetchMock.mock.calls[0]?.[0]).toContain('/api/agent/capabilities')
})

it('fails closed on malformed capability responses', async () => {
  vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response('{"agent_mode":"unknown"}'))
  await expect(refreshAgentCapabilities()).rejects.toThrow()
})

it('reports loading, then fixture readiness, then an API failure', async () => {
  let resolve!: (response: Response) => void
  vi.spyOn(globalThis, 'fetch').mockImplementationOnce(() => new Promise((done) => { resolve = done }))
    .mockRejectedValueOnce(new Error('offline'))
  const { result } = renderHook(useRunReadiness)
  expect(result.current.ready).toBe(false)
  expect(result.current.message).toContain('Checking')
  await act(async () => { resolve(new Response('{"agent_mode":"fixtures"}')) })
  await waitFor(() => expect(result.current.fixtures).toBe(true))
  await act(async () => { await refreshAgentCapabilities().catch(() => {}) })
  await waitFor(() => expect(result.current.ready).toBe(false))
  expect(result.current.message).toContain('Cannot connect')
})
