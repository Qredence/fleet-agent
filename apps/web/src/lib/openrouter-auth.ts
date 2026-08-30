/**
 * OpenRouter OAuth PKCE Authentication Module
 *
 * Implements the OAuth PKCE flow for OpenRouter:
 * - Ephemeral code verifier stored in sessionStorage
 * - Code challenge computed via SHA-256 (S256 method)
 * - Exchange code for user API key without backend client secret
 * - Cross-tab synchronization via localStorage and storage events
 * - OpenRouter app attribution headers (HTTP-Referer and X-Title)
 */

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
  { id: 'google/gemini-2.5-flash', label: 'Gemini 2.5 Flash (Google)' },
  { id: 'qwen/qwen-2.5-72b-instruct', label: 'Qwen 2.5 72B (Alibaba)' },
] as const

type AuthListener = () => void
const listeners = new Set<AuthListener>()

/**
 * Subscribes to auth and settings changes in this tab and across tabs.
 *
 * @param fn - Listener function called when auth state changes
 * @returns Unsubscribe function
 */
export const onAuthChange = (fn: AuthListener): (() => void) => {
  listeners.add(fn)
  return () => {
    listeners.delete(fn)
  }
}

const notify = () => {
  listeners.forEach((fn) => {
    try {
      fn()
    } catch {
      // Ignore listener errors
    }
  })
}

// Cross-tab sync: other tabs update when user signs in or out
if (typeof window !== 'undefined') {
  window.addEventListener('storage', (event) => {
    if (
      event.key === STORAGE_KEY ||
      event.key === MODEL_STORAGE_KEY ||
      event.key === CUSTOM_MODEL_ENABLED_KEY
    ) {
      notify()
    }
  })
}

/**
 * Returns the stored OpenRouter API key, or null if not authenticated.
 */
export const getApiKey = (): string | null => {
  if (typeof window === 'undefined') return null
  try {
    return localStorage.getItem(STORAGE_KEY)
  } catch {
    return null
  }
}

/**
 * Stores the OpenRouter API key in localStorage and notifies all subscribers.
 */
export const setApiKey = (key: string): void => {
  if (typeof window === 'undefined') return
  try {
    localStorage.setItem(STORAGE_KEY, key.trim())
    notify()
  } catch {
    // Ignore storage write failures
  }
}

/**
 * Clears the OpenRouter API key from localStorage and notifies all subscribers.
 */
export const clearApiKey = (): void => {
  if (typeof window === 'undefined') return
  try {
    localStorage.removeItem(STORAGE_KEY)
    notify()
  } catch {
    // Ignore storage remove failures
  }
}

/**
 * Gets the selected model override for OpenRouter.
 */
export const getSelectedModel = (): string => {
  if (typeof window === 'undefined') return DEFAULT_OPENROUTER_MODEL
  try {
    return (
      localStorage.getItem(MODEL_STORAGE_KEY) || DEFAULT_OPENROUTER_MODEL
    )
  } catch {
    return DEFAULT_OPENROUTER_MODEL
  }
}

/**
 * Sets the selected model override for OpenRouter.
 */
export const setSelectedModel = (model: string): void => {
  if (typeof window === 'undefined') return
  try {
    localStorage.setItem(MODEL_STORAGE_KEY, model.trim())
    notify()
  } catch {
    // Ignore
  }
}

/**
 * Checks whether custom model selection is enabled.
 */
export const isCustomModelEnabled = (): boolean => {
  if (typeof window === 'undefined') return false
  try {
    return localStorage.getItem(CUSTOM_MODEL_ENABLED_KEY) === 'true'
  } catch {
    return false
  }
}

/**
 * Enables or disables custom model selection.
 */
export const setCustomModelEnabled = (enabled: boolean): void => {
  if (typeof window === 'undefined') return
  try {
    localStorage.setItem(CUSTOM_MODEL_ENABLED_KEY, enabled ? 'true' : 'false')
    notify()
  } catch {
    // Ignore
  }
}

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

  window.location.href = `https://openrouter.ai/auth?${params.toString()}`
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

  const response = await fetch('https://openrouter.ai/api/v1/auth/keys', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      code,
      code_verifier: verifier,
      code_challenge_method: 'S256',
    }),
  })

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
 * Returns standard OpenRouter headers including full app attribution.
 *
 * @param apiKey - Optional explicit API key override
 */
export function getOpenRouterHeaders(
  apiKey?: string | null,
): Record<string, string> {
  const key = apiKey ?? getApiKey()
  const origin =
    typeof window !== 'undefined' && window.location.origin
      ? window.location.origin
      : 'https://fleet-agent.local'

  const headers: Record<string, string> = {
    'HTTP-Referer': origin,
    'X-Title': 'Fleet Agent',
  }

  if (key) {
    headers['Authorization'] = `Bearer ${key}`
    headers['X-OpenRouter-Key'] = key
  }

  return headers
}

/**
 * Returns only the headers accepted by Fleet Agent's /api/agent endpoint.
 * Provider authorization and attribution headers must never be sent to the
 * generic Fleet API resources.
 */
export function getOpenRouterAgentHeaders(
  apiKey?: string | null,
  model?: string | null,
): Record<string, string> {
  const key = apiKey ?? getApiKey()
  const headers: Record<string, string> = {}
  if (!key) return headers
  headers['X-OpenRouter-Key'] = key
  if (model?.trim()) headers['X-OpenRouter-Model'] = model.trim()
  return headers
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
