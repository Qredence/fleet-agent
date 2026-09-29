/**
 * OpenRouter OAuth PKCE Authentication Module
 *
 * Implements the OAuth PKCE flow for OpenRouter:
 * - Ephemeral code verifier stored in sessionStorage
 * - Code challenge computed via SHA-256 (S256 method)
 * - Exchange code for user API key without backend client secret
 * - Cross-tab synchronization via localStorage and storage events
 *
 * The localStorage-backed key/model state is shared with the other BYOK
 * providers through `local-storage-auth`; this module owns the OpenRouter
 * storage keys, catalog, and OAuth flow.
 */

import providerContract from '@fleet-agent/contracts/provider.json'

import { createLocalStorageAuth } from '@/features/providers/local-storage-auth'

export const STORAGE_KEY = 'openrouter_api_key'
export const VERIFIER_KEY = 'openrouter_code_verifier'
export const MODEL_STORAGE_KEY = 'openrouter_selected_model'
export const CUSTOM_MODEL_ENABLED_KEY = 'openrouter_custom_model_enabled'

export const DEFAULT_OPENROUTER_MODEL = 'openai/gpt-4o-mini'
export const POPULAR_OPENROUTER_MODELS = [
  { id: 'openai/gpt-4o-mini', label: 'GPT-4o mini (OpenAI)' },
  { id: 'anthropic/claude-3.5-sonnet', label: 'Claude 3.5 Sonnet (Anthropic)' },
  { id: 'deepseek/deepseek-r1', label: 'DeepSeek R1' },
  { id: 'deepseek/deepseek-chat', label: 'DeepSeek V3' },
  { id: 'meta-llama/llama-3.3-70b-instruct', label: 'Llama 3.3 70B (Meta)' },
  { id: 'google/gemini-3.1-flash-lite', label: 'Gemini 3.1 Flash Lite (Google)' },
  { id: 'google/gemini-2.5-flash', label: 'Gemini 2.5 Flash (Google)' },
  { id: 'qwen/qwen-2.5-72b-instruct', label: 'Qwen 2.5 72B (Alibaba)' },
] as const

const OPENROUTER_OAUTH_AUTHORIZE_URL = 'https://openrouter.ai/auth'

const auth = createLocalStorageAuth({
  storageKey: STORAGE_KEY,
  modelStorageKey: MODEL_STORAGE_KEY,
  customModelEnabledKey: CUSTOM_MODEL_ENABLED_KEY,
  defaultModel: DEFAULT_OPENROUTER_MODEL,
})

/**
 * Subscribes to auth and settings changes in this tab and across tabs.
 *
 * @param fn - Listener function called when auth state changes
 * @returns Unsubscribe function
 */
export const onAuthChange = (fn: () => void): (() => void) => auth.onAuthChange(fn)

/**
 * Returns the stored OpenRouter API key, or null if not authenticated.
 */
export const getApiKey = (): string | null => auth.getApiKey()

/**
 * Stores the OpenRouter API key in localStorage and notifies all subscribers.
 */
export const setApiKey = (key: string): void => auth.setApiKey(key)

/**
 * Clears the OpenRouter API key from localStorage and notifies all subscribers.
 */
export const clearApiKey = (): void => auth.clearApiKey()

/**
 * Gets the selected model override for OpenRouter.
 */
export const getSelectedModel = (): string => auth.getSelectedModel()

/**
 * Sets the selected model override for OpenRouter.
 */
export const setSelectedModel = (model: string): void => auth.setSelectedModel(model)

/**
 * Checks whether custom model selection is enabled.
 */
export const isCustomModelEnabled = (): boolean => auth.isCustomModelEnabled()

/**
 * Enables or disables custom model selection.
 */
export const setCustomModelEnabled = (enabled: boolean): void =>
  auth.setCustomModelEnabled(enabled)

/**
 * Guard: only process ?code= if we initiated an OAuth flow in this tab.
 */
export const hasOAuthCallbackPending = (): boolean => {
  if (typeof window === 'undefined') return false
  try {
    return sessionStorage.getItem(VERIFIER_KEY) !== null
  } catch {
    return false
  }
}

/**
 * Generates a cryptographically secure 32-byte base64url code verifier.
 */
export function generateCodeVerifier(): string {
  const bytes = new Uint8Array(32)
  crypto.getRandomValues(bytes)
  const binary = Array.from(bytes, (byte) => String.fromCharCode(byte)).join('')
  return btoa(binary)
    .replace(/\+/g, '-')
    .replace(/\//g, '_')
    .replace(/=+$/, '')
}

/**
 * Computes the S256 challenge for a given code verifier.
 */
export async function computeS256Challenge(verifier: string): Promise<string> {
  const digest = await crypto.subtle.digest(
    'SHA-256',
    new TextEncoder().encode(verifier),
  )
  const bytes = new Uint8Array(digest)
  const binary = Array.from(bytes, (byte) => String.fromCharCode(byte)).join('')
  return btoa(binary)
    .replace(/\+/g, '-')
    .replace(/\//g, '_')
    .replace(/=+$/, '')
}

/**
 * Initiates the OpenRouter OAuth PKCE flow by redirecting the browser to OpenRouter.
 *
 * @param callbackUrl - Optional custom callback URL (defaults to current origin + pathname)
 */
export async function initiateOAuth(callbackUrl?: string): Promise<void> {
  if (typeof window === 'undefined') return

  const verifier = generateCodeVerifier()
  try {
    sessionStorage.setItem(VERIFIER_KEY, verifier)
  } catch {
    throw new Error('Unable to store OAuth verifier in sessionStorage')
  }

  const challenge = await computeS256Challenge(verifier)
  const url = callbackUrl ?? `${window.location.origin}${window.location.pathname}`

  const params = new URLSearchParams({
    callback_url: url,
    code_challenge: challenge,
    code_challenge_method: 'S256',
  })

  window.location.href = `${OPENROUTER_OAUTH_AUTHORIZE_URL}?${params.toString()}`
}

/**
 * Handles the redirect back from OpenRouter by exchanging the code for an API key.
 *
 * @param code - The authorization code from the callback query parameter
 */
export async function handleOAuthCallback(code: string): Promise<string> {
  if (typeof window === 'undefined') {
    throw new Error('OAuth callback must be handled in a browser environment')
  }

  const verifier = sessionStorage.getItem(VERIFIER_KEY)
  if (!verifier) {
    throw new Error('Missing code verifier in sessionStorage')
  }

  // Remove the verifier as it is a one-time secret
  sessionStorage.removeItem(VERIFIER_KEY)

  const response = await fetch(
    `${providerContract.openRouter.apiBaseUrl}/auth/keys`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        code,
        code_verifier: verifier,
        code_challenge_method: 'S256',
      }),
    },
  )

  if (!response.ok) {
    throw new Error(`Key exchange failed with status ${response.status}`)
  }

  const data = (await response.json()) as { key?: string }
  if (!data?.key) {
    throw new Error('Invalid response from OpenRouter: missing API key')
  }

  setApiKey(data.key)
  return data.key
}

/**
 * Completes a pending OAuth callback using the current URL.
 *
 * Reads the one-time authorization code from the redirect query string and
 * exchanges it for an API key via handleOAuthCallback. All URL handling and
 * validation lives here, next to the PKCE verifier check, so callers gate
 * the flow on session state alone. Returns null when there is nothing to
 * complete (no pending verifier or no code in the URL); a denied or
 * abandoned flow also clears its stale verifier so the session is not
 * left mid-flow.
 */
export async function finalizeOAuthCallback(): Promise<string | null> {
  if (typeof window === 'undefined') return null
  if (!hasOAuthCallbackPending()) return null

  const code = new URLSearchParams(window.location.search).get('code')
  if (!code) {
    // Denied or abandoned flow: the verifier is single-use and cannot
    // complete a later exchange, so drop it now.
    sessionStorage.removeItem(VERIFIER_KEY)
    return null
  }
  return handleOAuthCallback(code)
}

/**
 * Masks an API key for safe display (e.g., sk-or-v1-••••••••4a8f).
 */
export function maskApiKey(key: string | null | undefined): string {
  if (!key) return ''
  const trimmed = key.trim()
  if (trimmed.length <= 12) return '••••••••'
  const prefix = trimmed.slice(0, 8)
  const suffix = trimmed.slice(-4)
  return `${prefix}••••••••${suffix}`
}
