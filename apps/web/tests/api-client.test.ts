import { afterEach, describe, expect, it, vi } from 'vitest'

import { apiFetch, apiFetchText } from '@/lib/api-client'

afterEach(() => {
  vi.restoreAllMocks()
})

describe('generic API client headers', () => {
  it('does not attach OpenRouter credentials or attribution', async () => {
    const fetchMock = vi
      .spyOn(globalThis, 'fetch')
      .mockResolvedValue(new Response(JSON.stringify({ ok: true }), { status: 200 }))

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
})
