import { useCallback, useEffect, useState, useTransition } from 'react'

import {
  getActiveProviderId,
  getProfiles,
  getProviderReadiness,
  type ProviderReadiness,
  onProvidersChange,
  removeProfile as removeStoredProfile,
  setActiveProviderId as setStoredActiveProviderId,
  upsertProfile as upsertStoredProfile,
  type ProviderProfile,
} from '@/features/providers/providers-store'

export interface UseProvidersReturn {
  readiness: ProviderReadiness
  profiles: ProviderProfile[]
  activeProviderId: string | null
  setActiveProviderId: (id: string | null) => void
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
  const [activeProviderId, setActiveProviderIdState] = useState<string | null>(() =>
    getActiveProviderId(),
  )
  const [, startTransition] = useTransition()
  const [, refresh] = useState(0)

  useEffect(() => {
    const syncState = () => {
      startTransition(() => {
        setProfiles(getProfiles())
        setActiveProviderIdState(getActiveProviderId())
        refresh((value) => value + 1)
      })
    }

    const unsubscribe = onProvidersChange(syncState)
    return () => unsubscribe()
  }, [])

  const setActiveProviderId = useCallback((id: string | null) => {
    setStoredActiveProviderId(id)
    setActiveProviderIdState(getActiveProviderId())
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
    readiness: getProviderReadiness(activeProviderId),
    activeProviderId,
    setActiveProviderId,
    upsertProfile,
    removeProfile,
  }
}
