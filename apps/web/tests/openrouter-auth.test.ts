import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import {
  generateCodeVerifier,
  computeS256Challenge,
  hasOAuthCallbackPending,
  getApiKey,
  setApiKey,
  clearApiKey,
  maskApiKey,
  getOpenRouterHeaders,
  getOpenRouterAgentHeaders,
  getSelectedModel,
  setSelectedModel,
  isCustomModelEnabled,
  setCustomModelEnabled,
  initiateOAuth,
  handleOAuthCallback,
  onAuthChange,
  STORAGE_KEY,
  VERIFIER_KEY,
  DEFAULT_OPENROUTER_MODEL,
} from '@/lib/openrouter-auth'

describe('openrouter-auth module', () => {
  beforeEach(() => {
    localStorage.clear()
    sessionStorage.clear()
    vi.restoreAllMocks()
  })

  afterEach(() => {
    localStorage.clear()
    sessionStorage.clear()
  })

  describe('PKCE generation', () => {
    it('generates a 43-character base64url code verifier without +, /, or =', () => {
      const verifier = generateCodeVerifier()
      expect(verifier).toBeTypeOf('string')
      expect(verifier.length).toBe(43)
      expect(verifier).not.toMatch(/[+/=]/)
      expect(verifier).toMatch(/^[A-Za-z0-9_-]+$/)
    })

    it('computes S256 challenge correctly from verifier', async () => {
      const verifier = 'test_code_verifier_1234567890_abcdefghijklmnop'
      const challenge = await computeS256Challenge(verifier)
      expect(challenge).toBeTypeOf('string')
      expect(challenge.length).toBeGreaterThan(20)
      expect(challenge).not.toMatch(/[+/=]/)
      expect(challenge).toMatch(/^[A-Za-z0-9_-]+$/)
    })
  })

  describe('Key storage & masking', () => {
    it('stores, retrieves, and clears API key', () => {
      expect(getApiKey()).toBeNull()

      setApiKey('sk-or-v1-abcdef123456')
      expect(getApiKey()).toBe('sk-or-v1-abcdef123456')
      expect(localStorage.getItem(STORAGE_KEY)).toBe('sk-or-v1-abcdef123456')

      clearApiKey()
      expect(getApiKey()).toBeNull()
      expect(localStorage.getItem(STORAGE_KEY)).toBeNull()
    })

    it('masks API keys safely', () => {
      expect(maskApiKey(null)).toBe('')
      expect(maskApiKey('')).toBe('')
      expect(maskApiKey('short')).toBe('••••••••')
      expect(maskApiKey('sk-or-v1-1234567890abcdef')).toBe('sk-or-v1••••••••cdef')
    })

    it('notifies subscribers on auth changes', () => {
      const listener = vi.fn()
      const unsubscribe = onAuthChange(listener)

      setApiKey('sk-or-test')
      expect(listener).toHaveBeenCalledTimes(1)

      clearApiKey()
      expect(listener).toHaveBeenCalledTimes(2)

      unsubscribe()
      setApiKey('sk-or-test-2')
      expect(listener).toHaveBeenCalledTimes(2)
    })
  })

  describe('Model preferences', () => {
    it('returns default model when none is configured', () => {
      expect(getSelectedModel()).toBe(DEFAULT_OPENROUTER_MODEL)
    })

    it('stores and retrieves selected model', () => {
      setSelectedModel('anthropic/claude-3.5-sonnet')
      expect(getSelectedModel()).toBe('anthropic/claude-3.5-sonnet')
    })

    it('manages custom model enabled toggle', () => {
      expect(isCustomModelEnabled()).toBe(false)
      setCustomModelEnabled(true)
      expect(isCustomModelEnabled()).toBe(true)
      setCustomModelEnabled(false)
      expect(isCustomModelEnabled()).toBe(false)
    })
  })

  describe('OAuth Flow & Key Exchange', () => {
    it('detects pending OAuth callback only when verifier exists in sessionStorage', () => {
      expect(hasOAuthCallbackPending()).toBe(false)

      sessionStorage.setItem(VERIFIER_KEY, 'dummy_verifier')
      expect(hasOAuthCallbackPending()).toBe(true)

      sessionStorage.removeItem(VERIFIER_KEY)
      expect(hasOAuthCallbackPending()).toBe(false)
    })

    it('stores verifier in sessionStorage and redirects to OpenRouter on initiateOAuth', async () => {
      const originalLocation = window.location
      // @ts-expect-error mocking window.location
      delete window.location
      window.location = {
        ...originalLocation,
        origin: 'http://localhost:5173',
        pathname: '/projects/test',
        href: '',
      }

      await initiateOAuth()

      const storedVerifier = sessionStorage.getItem(VERIFIER_KEY)
      expect(storedVerifier).toBeTruthy()
      expect(storedVerifier?.length).toBe(43)

      expect(window.location.href).toContain('https://openrouter.ai/auth?')
      expect(window.location.href).toContain('callback_url=http%3A%2F%2Flocalhost%3A5173%2Fprojects%2Ftest')
      expect(window.location.href).toContain('code_challenge_method=S256')
      expect(window.location.href).toContain('code_challenge=')

      window.location = originalLocation
    })

    it('exchanges code for API key and removes verifier on handleOAuthCallback', async () => {
      sessionStorage.setItem(VERIFIER_KEY, 'my_test_verifier')

      const mockFetch = vi.fn().mockResolvedValue({
        ok: true,
        status: 200,
        json: async () => ({ key: 'sk-or-v1-received-key-999' }),
      })
      globalThis.fetch = mockFetch

      const key = await handleOAuthCallback('sample_auth_code')

      expect(key).toBe('sk-or-v1-received-key-999')
      expect(getApiKey()).toBe('sk-or-v1-received-key-999')
      expect(sessionStorage.getItem(VERIFIER_KEY)).toBeNull()

      expect(mockFetch).toHaveBeenCalledWith(
        'https://openrouter.ai/api/v1/auth/keys',
        expect.objectContaining({
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            code: 'sample_auth_code',
            code_verifier: 'my_test_verifier',
            code_challenge_method: 'S256',
          }),
        }),
      )
    })

    it('throws error when code verifier is missing in handleOAuthCallback', async () => {
      sessionStorage.removeItem(VERIFIER_KEY)

      await expect(handleOAuthCallback('code_without_verifier')).rejects.toThrow(
        'Missing code verifier in sessionStorage',
      )
    })

    it('throws error when key exchange API fails', async () => {
      sessionStorage.setItem(VERIFIER_KEY, 'my_test_verifier')

      globalThis.fetch = vi.fn().mockResolvedValue({
        ok: false,
        status: 400,
        json: async () => ({ error: 'invalid_code' }),
      })

      await expect(handleOAuthCallback('invalid_code')).rejects.toThrow(
        'Key exchange failed with status 400',
      )
    })
  })

  describe('Attribution Headers', () => {
    it('returns standard headers including HTTP-Referer and X-Title', () => {
      const headers = getOpenRouterHeaders('sk-or-test-key')
      expect(headers['HTTP-Referer']).toBeTruthy()
      expect(headers['X-Title']).toBe('Fleet Agent')
      expect(headers['Authorization']).toBe('Bearer sk-or-test-key')
      expect(headers['X-OpenRouter-Key']).toBe('sk-or-test-key')
    })

    it('only creates agent-scoped headers when a key is present', () => {
      expect(getOpenRouterAgentHeaders(null, 'anthropic/claude')).toEqual({})
      expect(
        getOpenRouterAgentHeaders('sk-or-test-key', 'anthropic/claude'),
      ).toEqual({
        'X-OpenRouter-Key': 'sk-or-test-key',
        'X-OpenRouter-Model': 'anthropic/claude',
      })
    })
  })
})
