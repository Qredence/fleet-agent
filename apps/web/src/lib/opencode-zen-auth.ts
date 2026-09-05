/**
 * OpenCode Zen authentication and model preferences module.
 *
 * OpenCode Zen (https://opencode.ai/zen) is an OpenAI-compatible gateway that
 * aggregates curated open and partner models behind a single Bearer-token API
 * key. The browser keeps the key and the per-profile model selection in
 * localStorage; the value is sent to the Fleet Agent `/api/agent` endpoint as
 * the generic `X-LLM-Key` + `X-LLM-Base-Url` + `X-LLM-Model` headers together
 * with the active provider profile, and is never logged server-side.
 */

export const STORAGE_KEY = 'opencode_zen_api_key'
export const MODEL_STORAGE_KEY = 'opencode_zen_selected_model'
export const CUSTOM_MODEL_ENABLED_KEY = 'opencode_zen_custom_model_enabled'

export const DEFAULT_OPENCODE_ZEN_MODEL = 'muse-spark-1.3-contributor-free'

/**
 * Curated list of OpenCode Zen models surfaced in the settings dialog.
 *
 * The ids are the exact identifiers returned by
 * `GET https://opencode.ai/zen/v1/models`. Keep this list in sync with the
 * public OpenCode Zen catalog; users can still type any model id manually
 * via the custom-model field.
 */
export const POPULAR_OPENCODE_ZEN_MODELS = [
  {
    id: 'muse-spark-1.3-contributor-free',
    label: 'Muse Spark 1.3 (Contributor Free)',
  },
  { id: 'muse-spark-1.2', label: 'Muse Spark 1.2' },
  { id: 'muse-spark-1.2-contributor-free', label: 'Muse Spark 1.2 (Contributor Free)' },
  { id: 'claude-opus-4-8', label: 'Claude Opus 4.8' },
  { id: 'claude-sonnet-4-6', label: 'Claude Sonnet 4.6' },
  { id: 'claude-haiku-4-5', label: 'Claude Haiku 4.5' },
  { id: 'gpt-5.5', label: 'GPT 5.5' },
  { id: 'gpt-5.4', label: 'GPT 5.4' },
  { id: 'gemini-3.1-pro', label: 'Gemini 3.1 Pro' },
  { id: 'gemini-3.5-flash', label: 'Gemini 3.5 Flash' },
  { id: 'deepseek-v4-pro', label: 'DeepSeek V4 Pro' },
  { id: 'qwen3.6-plus', label: 'Qwen 3.6 Plus' },
] as const

type AuthListener = () => void
const listeners = new Set<AuthListener>()

/**
 * Subscribes to auth and settings changes in this tab and across tabs.
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

// Cross-tab sync: other tabs update when the key or model changes.
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
 * Returns the stored OpenCode Zen API key, or null if not configured.
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
 * Stores the OpenCode Zen API key in localStorage and notifies subscribers.
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
 * Clears the stored OpenCode Zen API key and notifies subscribers.
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
 * Returns the selected model override, defaulting to the curator-picked
 * `muse-spark-1.3-contributor-free` model.
 */
export const getSelectedModel = (): string => {
  if (typeof window === 'undefined') return DEFAULT_OPENCODE_ZEN_MODEL
  try {
    return localStorage.getItem(MODEL_STORAGE_KEY) || DEFAULT_OPENCODE_ZEN_MODEL
  } catch {
    return DEFAULT_OPENCODE_ZEN_MODEL
  }
}

/**
 * Stores the selected model override and notifies subscribers.
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
 * Returns true when the custom model override should be sent on the wire.
 * When false, the server-side default model is used.
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
 * Enables or disables the custom model override.
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
 * Returns standard OpenCode Zen request headers (attribution + bearer).
 * Use only for direct calls to the OpenCode Zen API; never send these to
 * the Fleet Agent generic API surface.
 */
export function getOpenCodeZenHeaders(
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
  }

  return headers
}
