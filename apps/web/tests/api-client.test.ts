import { afterEach, describe, expect, it, vi } from 'vitest'

import { apiFetch, apiFetchText, apiJsonFetch } from '@/lib/api-client'

afterEach(() => {
  vi.restoreAllMocks()
})

describe('generic API client headers', () => {
  it('does not attach OpenRouter credentials or attribution', async () => {
    const fetchMock = vi
      .spyOn(globalThis, 'fetch')
      .mockImplementation(async () => new Response(JSON.stringify({ ok: true }), { status: 200 }))

    await apiFetch('/api/threads')

    const init = fetchMock.mock.calls[0]?.[1]
    const headers = new Headers(init?.headers)
    expect(headers.get('X-OpenRouter-Key')).toBeNull()
    expect(headers.get('X-OpenRouter-Model')).toBeNull()
    expect(headers.get('Authorization')).toBeNull()
    expect(headers.get('HTTP-Referer')).toBeNull()
    expect(headers.get('X-Title')).toBeNull()
  })

  it('keeps the same restriction for text resources', async () => {
    const fetchMock = vi
      .spyOn(globalThis, 'fetch')
      .mockResolvedValue(new Response('content', { status: 200 }))

    await apiFetchText('/api/artifacts/example')

    const headers = new Headers(fetchMock.mock.calls[0]?.[1]?.headers)
    expect(headers.get('X-OpenRouter-Key')).toBeNull()
    expect(headers.get('Authorization')).toBeNull()
  })

  it('normalizes Headers instances and tuple headers without losing defaults', async () => {
    const fetchMock = vi
      .spyOn(globalThis, 'fetch')
      .mockImplementation(async () => new Response(JSON.stringify({ ok: true }), { status: 200 }))

    await apiFetch('/api/threads', {
      headers: new Headers({ 'X-Trace-Id': 'trace-1' }),
    })
    const fromHeaders = new Headers(fetchMock.mock.calls[0]?.[1]?.headers)
    expect(fromHeaders.get('Accept')).toBe('application/json')
    expect(fromHeaders.get('X-Trace-Id')).toBe('trace-1')

    await apiJsonFetch(
      '/api/projects',
      'POST',
      { name: 'Test' },
      { headers: [['X-Custom-Tuple', 'abc'], ['Accept', 'application/problem+json']] },
    )
    const fromTuples = new Headers(fetchMock.mock.calls[1]?.[1]?.headers)
    expect(fromTuples.get('Content-Type')).toBe('application/json')
    expect(fromTuples.get('Accept')).toBe('application/problem+json')
    expect(fromTuples.get('X-Custom-Tuple')).toBe('abc')
  })
})
