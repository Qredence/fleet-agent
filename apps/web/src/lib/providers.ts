/**
 * Provider profile registry for browser-owned (BYOK) LLM providers.
 *
 * Profiles live in localStorage and are sent per run as `X-LLM-*` headers on
 * the agent POST only — never to other Fleet API resources, and never logged
 * server-side. The OpenRouter preset keeps its OAuth-managed key and model in
 * `openrouter-auth` storage; this module owns the selection and the wire-format
 * settings (naming follows DSPy's normalized LM API: LMRequest/LMResponse,
 * typed messages).
 */

import {
  getApiKey as getOpenRouterApiKey,
  getSelectedModel as getOpenRouterSelectedModel,
  isCustomModelEnabled as isOpenRouterCustomModelEnabled,
} from '@/lib/openrouter-auth'
import {
  getApiKey as getOpenCodeZenApiKey,
  getSelectedModel as getOpenCodeZenSelectedModel,
  isCustomModelEnabled as isOpenCodeZenCustomModelEnabled,
} from '@/lib/opencode-zen-auth'

export const PROVIDERS_STORAGE_KEY = 'fleet_providers_v1'
export const OPENROUTER_PROFILE_ID = 'openrouter'
export const OPENROUTER_BASE_URL = 'https://openrouter.ai/api/v1'
export const OPENCODE_ZEN_PROFILE_ID = 'opencode-zen'
export const OPENCODE_ZEN_BASE_URL = 'https://opencode.ai/zen/v1'
export const SERVER_DEFAULT_ID = 'server'

export type ChatCompletionFormat = 'openai-chat-completions'
export type ResponseFormat = 'native_function_calling' | 'json_tool_calls'
export type MessagesFormat = 'system_role' | 'developer_role'

export interface ProviderProfile {
  id: string
  name: string
  /** OpenAI-compatible chat completions endpoint (SSRF-validated server-side). */
  baseUrl?: string
  /** Browser-owned key; leaves the browser only as the X-LLM-Key agent header. */
  apiKey?: string
  modelId?: string
  chatCompletionFormat: ChatCompletionFormat
  responseFormat: ResponseFormat
  messagesFormat: MessagesFormat
}

export interface ProviderStore {
  version: 1
  profiles: ProviderProfile[]
  /** SERVER_DEFAULT_ID, OPENROUTER_PROFILE_ID, or a custom profile id. */
  activeProviderId: string
}

type ProvidersListener = () => void
const listeners = new Set<ProvidersListener>()

/** Subscribes to provider selection/profile changes in this tab and others. */
export const onProvidersChange = (fn: ProvidersListener): (() => void) => {
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

if (typeof window !== 'undefined') {
  window.addEventListener('storage', (event) => {
    if (event.key === PROVIDERS_STORAGE_KEY) {
      notify()
    }
  })
}

const openRouterProfile = (): ProviderProfile => ({
  id: OPENROUTER_PROFILE_ID,
  name: 'OpenRouter',
  baseUrl: OPENROUTER_BASE_URL,
  chatCompletionFormat: 'openai-chat-completions',
  responseFormat: 'native_function_calling',
  messagesFormat: 'system_role',
})

const openCodeZenProfile = (): ProviderProfile => ({
  id: OPENCODE_ZEN_PROFILE_ID,
  name: 'OpenCode Zen',
  baseUrl: OPENCODE_ZEN_BASE_URL,
  chatCompletionFormat: 'openai-chat-completions',
  responseFormat: 'native_function_calling',
  messagesFormat: 'system_role',
})

const defaultStore = (): ProviderStore => ({
  version: 1,
  profiles: [openRouterProfile(), openCodeZenProfile()],
  activeProviderId:
    typeof window !== 'undefined' && getOpenRouterApiKey()
      ? OPENROUTER_PROFILE_ID
      : SERVER_DEFAULT_ID,
})

const isValidStore = (value: unknown): value is ProviderStore => {
  if (typeof value !== 'object' || value === null) return false
  const store = value as Partial<ProviderStore>
  return (
    store.version === 1 &&
    Array.isArray(store.profiles) &&
    typeof store.activeProviderId === 'string' &&
    store.profiles.every(
      (profile) =>
        typeof profile === 'object' &&
        profile !== null &&
        typeof profile.id === 'string' &&
        typeof profile.name === 'string' &&
        typeof profile.chatCompletionFormat === 'string' &&
        (profile.responseFormat === 'native_function_calling' ||
          profile.responseFormat === 'json_tool_calls') &&
        (profile.messagesFormat === 'system_role' ||
          profile.messagesFormat === 'developer_role'),
    )
  )
}

/** Loads the provider store, migrating legacy OpenRouter storage on first use. */
export function loadProviderStore(): ProviderStore {
  if (typeof window === 'undefined') return defaultStore()
  try {
    const raw = localStorage.getItem(PROVIDERS_STORAGE_KEY)
    if (raw === null) {
      const store = defaultStore()
      localStorage.setItem(PROVIDERS_STORAGE_KEY, JSON.stringify(store))
      return store
    }
    const parsed: unknown = JSON.parse(raw)
    if (isValidStore(parsed)) return parsed
  } catch {
    // Corrupt storage falls through to a fresh store
  }
  return defaultStore()
}

function saveProviderStore(store: ProviderStore): void {
  if (typeof window === 'undefined') return
  try {
    localStorage.setItem(PROVIDERS_STORAGE_KEY, JSON.stringify(store))
    notify()
  } catch {
    // Ignore storage write failures
  }
}

/** All registered profiles, always including the built-in presets. */
export function getProfiles(): ProviderProfile[] {
  const store = loadProviderStore()
  let profiles = store.profiles
  if (!profiles.some((profile) => profile.id === OPENROUTER_PROFILE_ID)) {
    profiles = [openRouterProfile(), ...profiles]
  }
  if (!profiles.some((profile) => profile.id === OPENCODE_ZEN_PROFILE_ID)) {
    profiles = [...profiles, openCodeZenProfile()]
  }
  return profiles
}

export function getActiveProviderId(): string {
  const store = loadProviderStore()
  const ids = new Set(getProfiles().map((profile) => profile.id))
  ids.add(SERVER_DEFAULT_ID)
  return ids.has(store.activeProviderId)
    ? store.activeProviderId
    : SERVER_DEFAULT_ID
}

export function getActiveProfile(): ProviderProfile | null {
  const activeId = getActiveProviderId()
  if (activeId === SERVER_DEFAULT_ID) return null
  return getProfiles().find((profile) => profile.id === activeId) ?? null
}

export function setActiveProviderId(id: string): void {
  const store = loadProviderStore()
  const ids = new Set(getProfiles().map((profile) => profile.id))
  ids.add(SERVER_DEFAULT_ID)
  if (!ids.has(id)) return
  saveProviderStore({ ...store, activeProviderId: id })
}

/**
 * Adds or replaces a profile by id. The OpenRouter and OpenCode Zen presets
 * are protected: their canonical id, name, and base URL are preserved so
 * browser-saved overrides can refresh only the editable fields.
 */
export function upsertProfile(profile: ProviderProfile): void {
  const store = loadProviderStore()
  let profiles: ProviderProfile[]
  if (
    profile.id === OPENROUTER_PROFILE_ID ||
    profile.id === OPENCODE_ZEN_PROFILE_ID
  ) {
    const preset = buildPresetProfile(profile.id, profile)
    profiles = store.profiles.some((existing) => existing.id === profile.id)
      ? store.profiles.map((existing) =>
          existing.id === profile.id ? preset : existing,
        )
      : [preset, ...store.profiles]
  } else if (store.profiles.some((existing) => existing.id === profile.id)) {
    profiles = store.profiles.map((existing) =>
      existing.id === profile.id ? profile : existing,
    )
  } else {
    profiles = [...store.profiles, profile]
  }
  saveProviderStore({ ...store, profiles })
}

/**
 * Builds the canonical preset profile for a built-in provider id. User
 * overrides flow through `apiKey` (OpenCode Zen), `modelId` (where the
 * preset defers to a separate model-selection module), and the wire-format
 * fields; everything else is forced from the registry so a stored override
 * can never repoint the preset at a foreign base URL.
 */
function buildPresetProfile(
  id: typeof OPENROUTER_PROFILE_ID | typeof OPENCODE_ZEN_PROFILE_ID,
  override: ProviderProfile,
): ProviderProfile {
  if (id === OPENROUTER_PROFILE_ID) {
    return {
      ...openRouterProfile(),
      apiKey: override.apiKey,
      modelId: override.modelId,
      responseFormat: override.responseFormat,
      messagesFormat: override.messagesFormat,
    }
  }
  return {
    ...openCodeZenProfile(),
    apiKey: override.apiKey,
    modelId: override.modelId,
    responseFormat: override.responseFormat,
    messagesFormat: override.messagesFormat,
  }
}

/**
 * Removes a custom profile; deleting the active one falls back to server.
 * Built-in preset profiles (OpenRouter, OpenCode Zen) cannot be removed:
 * they are owned by the registry and re-appear in `getProfiles()` when
 * missing, so removing them is a no-op.
 */
export function removeProfile(id: string): void {
  if (id === OPENROUTER_PROFILE_ID || id === OPENCODE_ZEN_PROFILE_ID) return
  const store = loadProviderStore()
  const profiles = store.profiles.filter((profile) => profile.id !== id)
  const activeProviderId =
    store.activeProviderId === id ? SERVER_DEFAULT_ID : store.activeProviderId
  saveProviderStore({ ...store, profiles, activeProviderId })
}

/** Agent-POST-only provider headers for the active profile. */
export function getAgentProviderHeaders(): Record<string, string> {
  const profile = getActiveProfile()
  if (profile === null) return {}

  if (profile.id === OPENROUTER_PROFILE_ID) {
    const key = getOpenRouterApiKey()
    if (!key) return {}
    const headers: Record<string, string> = {
      'X-LLM-Key': key,
      'X-LLM-Base-Url': OPENROUTER_BASE_URL,
      'X-LLM-Response-Format': profile.responseFormat,
      'X-LLM-Messages-Format': profile.messagesFormat,
    }
    if (isOpenRouterCustomModelEnabled()) {
      const model = getOpenRouterSelectedModel()
      if (model.trim()) headers['X-LLM-Model'] = model.trim()
    }
    return headers
  }

  if (profile.id === OPENCODE_ZEN_PROFILE_ID) {
    const key = getOpenCodeZenApiKey()
    if (!key) return {}
    const headers: Record<string, string> = {
      'X-LLM-Key': key,
      'X-LLM-Base-Url': OPENCODE_ZEN_BASE_URL,
      'X-LLM-Response-Format': profile.responseFormat,
      'X-LLM-Messages-Format': profile.messagesFormat,
    }
    if (isOpenCodeZenCustomModelEnabled()) {
      const model = getOpenCodeZenSelectedModel()
      if (model.trim()) headers['X-LLM-Model'] = model.trim()
    }
    return headers
  }

  if (!profile.apiKey?.trim() || !profile.baseUrl?.trim()) return {}
  const headers: Record<string, string> = {
    'X-LLM-Key': profile.apiKey.trim(),
    'X-LLM-Base-Url': profile.baseUrl.trim(),
    'X-LLM-Response-Format': profile.responseFormat,
    'X-LLM-Messages-Format': profile.messagesFormat,
  }
  if (profile.modelId?.trim()) headers['X-LLM-Model'] = profile.modelId.trim()
  return headers
}
