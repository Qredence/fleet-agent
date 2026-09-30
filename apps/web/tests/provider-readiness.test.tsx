import { act, renderHook, waitFor } from '@testing-library/react'
import { afterEach, expect, it } from 'vitest'
import { useProviders } from '@/features/providers/use-providers'
import { PROVIDERS_STORAGE_KEY, setActiveProviderId } from '@/features/providers/providers-store'
import { setApiKey, STORAGE_KEY } from '@/features/providers/openrouter-auth'

afterEach(() => localStorage.clear())

it('reactively updates readiness on same-tab auth and cross-tab selection and credential changes', async () => {
  localStorage.clear()
  const { result } = renderHook(useProviders)
  expect(result.current.readiness.ready).toBe(false)
  act(() => {
    setApiKey('test-key')
    setActiveProviderId('openrouter')
  })
  await waitFor(() => expect(result.current.readiness.ready).toBe(true))
  act(() => {
    localStorage.removeItem(STORAGE_KEY)
    window.dispatchEvent(new StorageEvent('storage', {key: STORAGE_KEY}))
  })
  await waitFor(() => expect(result.current.readiness.ready).toBe(false))
  expect(result.current.activeProviderId).toBe('openrouter')
  act(() => {
    const store = JSON.parse(localStorage.getItem(PROVIDERS_STORAGE_KEY)!)
    localStorage.setItem(PROVIDERS_STORAGE_KEY, JSON.stringify({...store, activeProviderId: 'server'}))
    window.dispatchEvent(new StorageEvent('storage', {key: PROVIDERS_STORAGE_KEY}))
  })
  await waitFor(() => expect(result.current.activeProviderId).toBeNull())
})
