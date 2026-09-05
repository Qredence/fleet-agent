import { useEffect, useState, useCallback } from 'react'

import {
  getApiKey as getStoredApiKey,
  setApiKey as setStoredApiKey,
  clearApiKey as clearStoredApiKey,
  getSelectedModel as getStoredSelectedModel,
  setSelectedModel as setStoredSelectedModel,
  isCustomModelEnabled as getStoredCustomModelEnabled,
  setCustomModelEnabled as setStoredCustomModelEnabled,
  onAuthChange,
  DEFAULT_OPENCODE_ZEN_MODEL,
} from '@/lib/opencode-zen-auth'

export interface UseOpenCodeZenAuthReturn {
  apiKey: string | null
  isAuthenticated: boolean
  selectedModel: string
  customModelEnabled: boolean
  setApiKey: (key: string) => void
  setSelectedModel: (model: string) => void
  setCustomModelEnabled: (enabled: boolean) => void
  signOut: () => void
}

/**
 * React hook for the browser-owned OpenCode Zen BYOK key and the per-profile
 * model selection. OpenCode Zen uses a static Bearer token (no OAuth), so
 * there is no callback handling here. The hook mirrors `useOpenRouterAuth`
 * so the settings dialog can render a uniform Auth & Model block.
 */
export function useOpenCodeZenAuth(): UseOpenCodeZenAuthReturn {
  const [apiKey, setLocalApiKey] = useState<string | null>(() => getStoredApiKey())
  const [selectedModel, setLocalSelectedModel] = useState<string>(() =>
    getStoredSelectedModel(),
  )
  const [customModelEnabled, setLocalCustomModelEnabled] = useState<boolean>(() =>
    getStoredCustomModelEnabled(),
  )

  useEffect(() => {
    const syncState = () => {
      setLocalApiKey(getStoredApiKey())
      setLocalSelectedModel(getStoredSelectedModel())
      setLocalCustomModelEnabled(getStoredCustomModelEnabled())
    }

    const unsubscribe = onAuthChange(syncState)
    return () => unsubscribe()
  }, [])

  const setApiKey = useCallback((key: string) => {
    setStoredApiKey(key)
    setLocalApiKey(getStoredApiKey())
  }, [])

  const setSelectedModel = useCallback((model: string) => {
    setStoredSelectedModel(model || DEFAULT_OPENCODE_ZEN_MODEL)
    setLocalSelectedModel(model || DEFAULT_OPENCODE_ZEN_MODEL)
  }, [])

  const setCustomModelEnabled = useCallback((enabled: boolean) => {
    setStoredCustomModelEnabled(enabled)
    setLocalCustomModelEnabled(enabled)
  }, [])

  const signOut = useCallback(() => {
    clearStoredApiKey()
    setLocalApiKey(null)
  }, [])

  return {
    apiKey,
    isAuthenticated: Boolean(apiKey),
    selectedModel,
    customModelEnabled,
    setApiKey,
    setSelectedModel,
    setCustomModelEnabled,
    signOut,
  }
}
