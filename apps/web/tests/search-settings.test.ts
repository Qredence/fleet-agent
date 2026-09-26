import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import {
  getSearchApiKey,
  setSearchApiKey,
  clearSearchApiKey,
  getSearchProvider,
  setSearchProvider,
  maskSearchApiKey,
  getSearchHeaders,
  onSearchSettingsChange,
  SEARCH_API_KEY_STORAGE_KEY,
  SEARCH_PROVIDER_STORAGE_KEY,
} from '@/lib/search-settings'
import { getAgentProviderHeaders } from '@/lib/providers'

describe('search-settings module', () => {
  beforeEach(() => {
    localStorage.clear()
    sessionStorage.clear()
    vi.restoreAllMocks()
  })

  afterEach(() => {
    localStorage.clear()
    sessionStorage.clear()
  })

  describe('Key storage and retrieval', () => {
    it('returns null when no search key is stored', () => {
      expect(getSearchApiKey()).toBeNull()
    })

    it('stores, retrieves, and clears the search API key', () => {
      setSearchApiKey('tvly-1234567890abcdef')
      expect(getSearchApiKey()).toBe('tvly-1234567890abcdef')
      expect(localStorage.getItem(SEARCH_API_KEY_STORAGE_KEY)).toBe('tvly-1234567890abcdef')

      clearSearchApiKey()
      expect(getSearchApiKey()).toBeNull()
      expect(localStorage.getItem(SEARCH_API_KEY_STORAGE_KEY)).toBeNull()
    })

    it('defaults search provider to tavily', () => {
      expect(getSearchProvider()).toBe('tavily')
      setSearchProvider('tavily')
      expect(localStorage.getItem(SEARCH_PROVIDER_STORAGE_KEY)).toBe('tavily')
    })
  })

  describe('maskSearchApiKey', () => {
    it('masks middle characters of API key', () => {
      expect(maskSearchApiKey(null)).toBe('')
      expect(maskSearchApiKey('')).toBe('')
      expect(maskSearchApiKey('short')).toBe('••••••••')
      expect(maskSearchApiKey('tvly-testkey1234567890')).toBe('tvly-••••••••7890')
    })
  })

  describe('getSearchHeaders', () => {
    it('returns empty headers when no key is configured', () => {
      expect(getSearchHeaders()).toEqual({})
    })

    it('returns X-Search-Key and X-Search-Provider when key is configured', () => {
      setSearchApiKey('tvly-mysecretkey')
      expect(getSearchHeaders()).toEqual({
        'X-Search-Key': 'tvly-mysecretkey',
        'X-Search-Provider': 'tavily',
      })
    })

    it('integrates into getAgentProviderHeaders', () => {
      setSearchApiKey('tvly-agentsearchkey')
      const headers = getAgentProviderHeaders()
      expect(headers['X-Search-Key']).toBe('tvly-agentsearchkey')
      expect(headers['X-Search-Provider']).toBe('tavily')
    })
  })

  describe('onSearchSettingsChange event listener', () => {
    it('fires listener when search settings change', () => {
      const listener = vi.fn()
      const unsubscribe = onSearchSettingsChange(listener)

      setSearchApiKey('tvly-newkey')
      expect(listener).toHaveBeenCalledWith({
        apiKey: 'tvly-newkey',
        provider: 'tavily',
      })

      clearSearchApiKey()
      expect(listener).toHaveBeenCalledWith({
        apiKey: null,
        provider: 'tavily',
      })

      unsubscribe()
      setSearchApiKey('tvly-ignored')
      expect(listener).toHaveBeenCalledTimes(2)
    })
  })
})
