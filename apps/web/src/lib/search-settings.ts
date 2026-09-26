/**
 * Search provider configuration for browser-owned (BYOK) search API keys.
 *
 * Keys live exclusively in the browser's localStorage and are forwarded per agent run
 * via `X-Search-*` request headers (e.g. `X-Search-Key`, `X-Search-Provider`).
 * They are never saved to the database and never logged server-side.
 */

export const SEARCH_API_KEY_STORAGE_KEY = 'fleet_agent_search_api_key'
export const SEARCH_PROVIDER_STORAGE_KEY = 'fleet_agent_search_provider'

export type SearchProvider = 'tavily'

export interface SearchProviderInfo {
  id: SearchProvider
  name: string
  description: string
  website: string
  docsUrl: string
  keyPrefix?: string
}

export const SEARCH_PROVIDERS: Record<SearchProvider, SearchProviderInfo> = {
  tavily: {
    id: 'tavily',
    name: 'Tavily Search',
    description:
      'Search engine optimized for AI agents and LLMs. Delivers fast, real-time, curated web search and extraction results.',
    website: 'https://tavily.com',
    docsUrl: 'https://docs.tavily.com',
    keyPrefix: 'tvly-',
  },
}

export const DEFAULT_SEARCH_PROVIDER: SearchProvider = 'tavily'

export interface SearchSettingsState {
  apiKey: string | null
  provider: SearchProvider
}

type SearchSettingsListener = (state: SearchSettingsState) => void
const listeners = new Set<SearchSettingsListener>()

/**
 * Subscribes to search settings changes in this tab and across tabs.
 *
 * @param fn - Listener function called when search settings change
 * @returns Unsubscribe function
 */
export const onSearchSettingsChange = (
  fn: SearchSettingsListener,
): (() => void) => {
  listeners.add(fn)
  return () => {
    listeners.delete(fn)
  }
}

const notify = () => {
  const state: SearchSettingsState = {
    apiKey: getSearchApiKey(),
    provider: getSearchProvider(),
  }
  listeners.forEach((fn) => {
    try {
      fn(state)
    } catch {
      // Ignore listener errors
    }
  })
}

if (typeof window !== 'undefined') {
  window.addEventListener('storage', (event) => {
    if (
      event.key === SEARCH_API_KEY_STORAGE_KEY ||
      event.key === SEARCH_PROVIDER_STORAGE_KEY
    ) {
      notify()
    }
  })
}

/**
 * Returns the stored search API key, or null if not configured.
 */
export const getSearchApiKey = (): string | null => {
  if (typeof window === 'undefined') return null
  try {
    return localStorage.getItem(SEARCH_API_KEY_STORAGE_KEY)
  } catch {
    return null
  }
}

/**
 * Stores the search API key in localStorage and notifies all subscribers.
 */
export const setSearchApiKey = (key: string): void => {
  if (typeof window === 'undefined') return
  try {
    localStorage.setItem(SEARCH_API_KEY_STORAGE_KEY, key.trim())
    notify()
  } catch {
    // Ignore storage write failures
  }
}

/**
 * Clears the search API key from localStorage and notifies all subscribers.
 */
export const clearSearchApiKey = (): void => {
  if (typeof window === 'undefined') return
  try {
    localStorage.removeItem(SEARCH_API_KEY_STORAGE_KEY)
    notify()
  } catch {
    // Ignore storage remove failures
  }
}

/**
 * Gets the selected search provider (defaults to 'tavily').
 */
export const getSearchProvider = (): SearchProvider => {
  if (typeof window === 'undefined') return DEFAULT_SEARCH_PROVIDER
  try {
    const stored = localStorage.getItem(SEARCH_PROVIDER_STORAGE_KEY)
    if (stored === 'tavily') return stored
    return DEFAULT_SEARCH_PROVIDER
  } catch {
    return DEFAULT_SEARCH_PROVIDER
  }
}

/**
 * Sets the selected search provider.
 */
export const setSearchProvider = (provider: SearchProvider): void => {
  if (typeof window === 'undefined') return
  try {
    localStorage.setItem(SEARCH_PROVIDER_STORAGE_KEY, provider)
    notify()
  } catch {
    // Ignore storage write failures
  }
}

/**
 * Generates search provider headers for agent requests.
 */
export const getSearchHeaders = (): Record<string, string> => {
  const key = getSearchApiKey()
  if (!key || !key.trim()) return {}
  const provider = getSearchProvider()
  return {
    'X-Search-Key': key.trim(),
    'X-Search-Provider': provider,
  }
}

/**
 * Masks a search API key for safe display (e.g., tvly-••••••••4a8f).
 */
export function maskSearchApiKey(key: string | null | undefined): string {
  if (!key) return ''
  const trimmed = key.trim()
  if (trimmed.length <= 8) return '••••••••'
  const prefix = trimmed.slice(0, 5)
  const suffix = trimmed.slice(-4)
  return `${prefix}••••••••${suffix}`
}
