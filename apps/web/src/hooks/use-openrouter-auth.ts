import { useEffect, useState, useCallback, useTransition } from 'react'
import {
  getApiKey,
  setApiKey as setStoredApiKey,
  clearApiKey as clearStoredApiKey,
  getSelectedModel as getStoredSelectedModel,
  setSelectedModel as setStoredSelectedModel,
  isCustomModelEnabled as getStoredCustomModelEnabled,
  setCustomModelEnabled as setStoredCustomModelEnabled,
  hasOAuthCallbackPending,
  finalizeOAuthCallback,
  initiateOAuth,
  onAuthChange,
  DEFAULT_OPENROUTER_MODEL,
} from '@/lib/openrouter-auth'

export interface UseOpenRouterAuthOptions {
  /**
   * If true, checks the current URL for a `?code=` query parameter and processes
   * the OAuth exchange if an OAuth request is pending in this session.
   * Defaults to false (only the root handler should pass true).
   */
  autoHandleCallback?: boolean
}

export interface UseOpenRouterAuthReturn {
  apiKey: string | null
  isAuthenticated: boolean
  isLoading: boolean
  error: string | null
  selectedModel: string
  customModelEnabled: boolean
  signIn: (callbackUrl?: string) => Promise<void>
  signOut: () => void
  setApiKey: (key: string) => void
  setSelectedModel: (model: string) => void
  setCustomModelEnabled: (enabled: boolean) => void
  clearError: () => void
}

/**
 * React hook for interacting with OpenRouter OAuth authentication and settings.
 *
 * Automatically synchronizes across components and tabs via storage events.
 */
export function useOpenRouterAuth(
  options: UseOpenRouterAuthOptions = {},
): UseOpenRouterAuthReturn {
  const { autoHandleCallback = false } = options
  const [apiKey, setLocalApiKey] = useState<string | null>(() => getApiKey())
  const [selectedModel, setLocalSelectedModel] = useState<string>(() =>
    getStoredSelectedModel(),
  )
  const [customModelEnabled, setLocalCustomModelEnabled] = useState<boolean>(() =>
    getStoredCustomModelEnabled(),
  )
  const [isLoading, setIsLoading] = useState<boolean>(false)
  const [error, setError] = useState<string | null>(null)
  const [, startTransition] = useTransition()

  // Sync state with storage and auth listeners
  useEffect(() => {
    const syncState = () => {
      startTransition(() => {
        setLocalApiKey(getApiKey())
        setLocalSelectedModel(getStoredSelectedModel())
        setLocalCustomModelEnabled(getStoredCustomModelEnabled())
      })
    }

    const unsubscribe = onAuthChange(syncState)
    return () => unsubscribe()
  }, [])

  // Auto-handle OAuth callback if requested
  useEffect(() => {
    // Gate exclusively on environment and session state: the redirect URL
    // is read and validated inside finalizeOAuthCallback, next to the PKCE
    // verifier check, so no URL-controlled value decides whether the
    // sensitive exchange runs.
    if (!autoHandleCallback || typeof window === 'undefined') return
    if (!hasOAuthCallbackPending()) return

    let cancelled = false
    setIsLoading(true)
    setError(null)

    finalizeOAuthCallback()
      .then((newKey) => {
        if (cancelled) return
        setIsLoading(false)
        if (newKey === null) return
        // Clean the URL by removing ?code= from the query string
        const newParams = new URLSearchParams(window.location.search)
        newParams.delete('code')
        const query = newParams.toString()
        const cleanUrl = `${window.location.pathname}${query ? `?${query}` : ''}${window.location.hash}`
        window.history.replaceState({}, document.title, cleanUrl)

        setLocalApiKey(newKey)
      })
      .catch((err) => {
        if (cancelled) return
        const message =
          err instanceof Error
            ? err.message
            : 'Failed to complete OpenRouter authorization'
        setError(message)
        setIsLoading(false)
      })

    return () => {
      cancelled = true
    }
  }, [autoHandleCallback])

  const signIn = useCallback(async (callbackUrl?: string) => {
    setIsLoading(true)
    setError(null)
    try {
      await initiateOAuth(callbackUrl)
    } catch (err) {
      const message =
        err instanceof Error ? err.message : 'Failed to initiate OpenRouter OAuth'
      setError(message)
      setIsLoading(false)
    }
  }, [])

  const signOut = useCallback(() => {
    clearStoredApiKey()
    setLocalApiKey(null)
    setError(null)
  }, [])

  const setApiKey = useCallback((key: string) => {
    setStoredApiKey(key)
    setLocalApiKey(key)
    setError(null)
  }, [])

  const setSelectedModel = useCallback((model: string) => {
    setStoredSelectedModel(model || DEFAULT_OPENROUTER_MODEL)
    setLocalSelectedModel(model || DEFAULT_OPENROUTER_MODEL)
  }, [])

  const setCustomModelEnabled = useCallback((enabled: boolean) => {
    setStoredCustomModelEnabled(enabled)
    setLocalCustomModelEnabled(enabled)
  }, [])

  const clearError = useCallback(() => {
    setError(null)
  }, [])

  return {
    apiKey,
    isAuthenticated: Boolean(apiKey),
    isLoading,
    error,
    selectedModel,
    customModelEnabled,
    signIn,
    signOut,
    setApiKey,
    setSelectedModel,
    setCustomModelEnabled,
    clearError,
  }
}
