import { useCallback, useEffect, useState, useTransition } from 'react'

import {
  getActiveProviderId,
  getProfiles,
  onProvidersChange,
  removeProfile as removeStoredProfile,
  setActiveProviderId as setStoredActiveProviderId,
  upsertProfile as upsertStoredProfile,
  type ProviderProfile,
} from '@/lib/providers'

export interface UseProvidersReturn {
  profiles: ProviderProfile[]
  activeProviderId: string
  setActiveProviderId: (id: string) => void
  upsertProfile: (profile: ProviderProfile) => void
  removeProfile: (id: string) => void
}

/**
 * React hook for the browser-owned provider registry.
 *
 * Synchronizes across components and tabs via storage events.
 */
export function useProviders(): UseProvidersReturn {
  const [profiles, setProfiles] = useState<ProviderProfile[]>(() => getProfiles())
  const [activeProviderId, setActiveProviderIdState] = useState<string>(() =>
    getActiveProviderId(),
  )
  const [, startTransition] = useTransition()

  useEffect(() => {
    const syncState = () => {
      startTransition(() => {
        setProfiles(getProfiles())
        setActiveProviderIdState(getActiveProviderId())
      })
    }

    const unsubscribe = onProvidersChange(syncState)
    return () => unsubscribe()
  }, [])

  const setActiveProviderId = useCallback((id: string) => {
    setStoredActiveProviderId(id)
    setActiveProviderIdState(id)
  }, [])

  const upsertProfile = useCallback((profile: ProviderProfile) => {
    upsertStoredProfile(profile)
    setProfiles(getProfiles())
  }, [])

  const removeProfile = useCallback((id: string) => {
    removeStoredProfile(id)
    setProfiles(getProfiles())
    setActiveProviderIdState(getActiveProviderId())
  }, [])

  return {
    profiles,
    activeProviderId,
    setActiveProviderId,
    upsertProfile,
    removeProfile,
  }
}
