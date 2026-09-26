import { useEffect, useState, useCallback } from 'react'
import {
  getSearchApiKey,
  setSearchApiKey as setStoredSearchApiKey,
  clearSearchApiKey as clearStoredSearchApiKey,
  getSearchProvider,
  setSearchProvider as setStoredSearchProvider,
  onSearchSettingsChange,
  SEARCH_PROVIDERS,
  type SearchProvider,
  type SearchProviderInfo,
} from '@/lib/search-settings'

export interface UseSearchSettingsReturn {
  apiKey: string | null
  provider: SearchProvider
  providerInfo: SearchProviderInfo
  isConnected: boolean
  setApiKey: (key: string) => void
  clearApiKey: () => void
  setProvider: (provider: SearchProvider) => void
}

/**
 * React hook for managing browser-owned search provider API keys and settings.
 * Synchronizes across components and tabs via storage events.
 */
export function useSearchSettings(): UseSearchSettingsReturn {
  const [apiKey, setLocalApiKey] = useState<string | null>(() => getSearchApiKey())
  const [provider, setLocalProvider] = useState<SearchProvider>(() =>
    getSearchProvider(),
  )

  useEffect(() => {
    const syncState = () => {
      setLocalApiKey(getSearchApiKey())
      setLocalProvider(getSearchProvider())
    }

    const unsubscribe = onSearchSettingsChange(syncState)
    return () => unsubscribe()
  }, [])

  const setApiKey = useCallback((key: string) => {
    setStoredSearchApiKey(key)
    setLocalApiKey(getSearchApiKey())
  }, [])

  const clearApiKey = useCallback(() => {
    clearStoredSearchApiKey()
    setLocalApiKey(null)
  }, [])

  const setProvider = useCallback((newProvider: SearchProvider) => {
    setStoredSearchProvider(newProvider)
    setLocalProvider(newProvider)
  }, [])

  return {
    apiKey,
    provider,
    providerInfo: SEARCH_PROVIDERS[provider],
    isConnected: Boolean(apiKey && apiKey.trim().length > 0),
    setApiKey,
    clearApiKey,
    setProvider,
  }
}
