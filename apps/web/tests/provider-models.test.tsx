import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, renderHook, waitFor } from '@testing-library/react'
import type { ReactNode } from 'react'
import { afterEach, expect, it, vi } from 'vitest'
import { useProviderModels } from '@/features/providers/use-provider-models'

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})

it('isolates model lists by credentials and reuses the matching cache without exposing keys', async () => {
  const firstKey = 'synthetic-key-first'
  const secondKey = 'synthetic-key-second'
  const fetchMock = vi.fn().mockImplementation(async (_url, { headers }) => ({
    ok: true,
    json: async () => ({ data: [{ id: headers.Authorization === `Bearer ${firstKey}` ? 'first-model' : 'second-model' }] }),
  }))
  vi.stubGlobal('fetch', fetchMock)
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  )
  const { result, rerender } = renderHook(
    ({ apiKey }) => useProviderModels({ providerId: 'custom', baseUrl: 'https://provider.example/v1', apiKey }),
    { wrapper, initialProps: { apiKey: firstKey } },
  )
  await waitFor(() => expect(result.current.data?.[0].id).toBe('first-model'))
  rerender({ apiKey: secondKey })
  expect(result.current.data).toBeUndefined()
  await waitFor(() => expect(result.current.data?.[0].id).toBe('second-model'))
  rerender({ apiKey: firstKey })
  expect(result.current.data?.[0].id).toBe('first-model')
  expect(fetchMock).toHaveBeenCalledTimes(2)
  const keys = client.getQueryCache().getAll().map((query) => query.queryKey)
  expect(keys).toHaveLength(2)
  expect(JSON.stringify(keys)).not.toContain(firstKey)
  expect(JSON.stringify(keys)).not.toContain(secondKey)
})
