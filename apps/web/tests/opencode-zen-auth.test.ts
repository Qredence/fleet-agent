import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'

import {
  STORAGE_KEY,
  MODEL_STORAGE_KEY,
  CUSTOM_MODEL_ENABLED_KEY,
  DEFAULT_OPENCODE_ZEN_MODEL,
  POPULAR_OPENCODE_ZEN_MODELS,
  getApiKey,
  setApiKey,
  clearApiKey,
  getSelectedModel,
  setSelectedModel,
  isCustomModelEnabled,
  setCustomModelEnabled,
  getOpenCodeZenHeaders,
  onAuthChange,
} from '@/lib/opencode-zen-auth'

describe('opencode-zen-auth module', () => {
  beforeEach(() => {
    localStorage.clear()
    vi.restoreAllMocks()
  })

  afterEach(() => {
    localStorage.clear()
  })

  describe('Key storage & masking', () => {
    it('returns null when no API key is configured', () => {
      expect(getApiKey()).toBeNull()
    })

    it('stores and retrieves the API key', () => {
      setApiKey('zen-test-key-1234')
      expect(getApiKey()).toBe('zen-test-key-1234')
      expect(localStorage.getItem(STORAGE_KEY)).toBe('zen-test-key-1234')
    })

    it('clears the API key', () => {
      setApiKey('zen-test-key-1234')
      clearApiKey()
      expect(getApiKey()).toBeNull()
      expect(localStorage.getItem(STORAGE_KEY)).toBeNull()
    })

    it('trims whitespace when storing the key', () => {
      setApiKey('   zen-test-key-1234  ')
      expect(getApiKey()).toBe('zen-test-key-1234')
    })

    it('notifies subscribers on auth changes', () => {
      const listener = vi.fn()
      const unsubscribe = onAuthChange(listener)

      setApiKey('zen-test-key-1234')
      expect(listener).toHaveBeenCalledTimes(1)

      clearApiKey()
      expect(listener).toHaveBeenCalledTimes(2)

      unsubscribe()
      setApiKey('zen-test-key-5678')
      expect(listener).toHaveBeenCalledTimes(2)
    })
  })

  describe('Model preferences', () => {
    it('returns the curated default model when none is selected', () => {
      expect(getSelectedModel()).toBe(DEFAULT_OPENCODE_ZEN_MODEL)
      expect(DEFAULT_OPENCODE_ZEN_MODEL).toBe('muse-spark-1.3-contributor-free')
    })

    it('stores and retrieves the selected model', () => {
      setSelectedModel('claude-opus-4-8')
      expect(getSelectedModel()).toBe('claude-opus-4-8')
      expect(localStorage.getItem(MODEL_STORAGE_KEY)).toBe('claude-opus-4-8')
    })

    it('manages the custom-model-enabled toggle', () => {
      expect(isCustomModelEnabled()).toBe(false)
      setCustomModelEnabled(true)
      expect(isCustomModelEnabled()).toBe(true)
      expect(localStorage.getItem(CUSTOM_MODEL_ENABLED_KEY)).toBe('true')
      setCustomModelEnabled(false)
      expect(isCustomModelEnabled()).toBe(false)
    })

    it('includes the requested model in the popular list', () => {
      const ids = POPULAR_OPENCODE_ZEN_MODELS.map((model) => model.id)
      expect(ids).toContain('muse-spark-1.3-contributor-free')
      expect(ids).toContain('claude-opus-4-8')
    })
  })

  describe('Attribution headers', () => {
    it('returns the app attribution header even without a key', () => {
      const headers = getOpenCodeZenHeaders()
      expect(headers['HTTP-Referer']).toBeTruthy()
      expect(headers['X-Title']).toBe('Fleet Agent')
      expect(headers['Authorization']).toBeUndefined()
    })

    it('adds the Bearer token when a key is provided', () => {
      const headers = getOpenCodeZenHeaders('zen-test-key-1234')
      expect(headers['Authorization']).toBe('Bearer zen-test-key-1234')
    })

    it('reads the key from storage when no override is passed', () => {
      setApiKey('zen-test-key-5678')
      const headers = getOpenCodeZenHeaders()
      expect(headers['Authorization']).toBe('Bearer zen-test-key-5678')
    })
  })
})
