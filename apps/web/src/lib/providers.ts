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
  getApiKey,
  getSelectedModel,
  isCustomModelEnabled,
} from '@/lib/openrouter-auth'

export const PROVIDERS_STORAGE_KEY = 'fleet_providers_v1'
export const OPENROUTER_PROFILE_ID = 'openrouter'
export const OPENROUTER_BASE_URL = 'https://openrouter.ai/api/v1'
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

const defaultStore = (): ProviderStore => ({
  version: 1,
  profiles: [openRouterProfile()],
  activeProviderId:
    typeof window !== 'undefined' && getApiKey()
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

/** All registered profiles, always including the OpenRouter preset. */
export function getProfiles(): ProviderProfile[] {
  const store = loadProviderStore()
  if (store.profiles.some((profile) => profile.id === OPENROUTER_PROFILE_ID)) {
    return store.profiles
  }
  return [openRouterProfile(), ...store.profiles]
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

/** Adds or replaces a profile by id; the OpenRouter preset is kept single. */
export function upsertProfile(profile: ProviderProfile): void {
  const store = loadProviderStore()
  const profiles =
    profile.id === OPENROUTER_PROFILE_ID
      ? store.profiles.some((existing) => existing.id === OPENROUTER_PROFILE_ID)
        ? store.profiles.map((existing) =>
            existing.id === OPENROUTER_PROFILE_ID
              ? { ...existing, ...profile, id: OPENROUTER_PROFILE_ID }
              : existing,
          )
        : [profile, ...store.profiles]
      : store.profiles.some((existing) => existing.id === profile.id)
        ? store.profiles.map((existing) =>
            existing.id === profile.id ? profile : existing,
          )
        : [...store.profiles, profile]
  saveProviderStore({ ...store, profiles })
}

/** Removes a custom profile; deleting the active one falls back to server. */
export function removeProfile(id: string): void {
  if (id === OPENROUTER_PROFILE_ID) return
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
    const key = getApiKey()
    if (!key) return {}
    const headers: Record<string, string> = {
      'X-LLM-Key': key,
      'X-LLM-Base-Url': OPENROUTER_BASE_URL,
      'X-LLM-Response-Format': profile.responseFormat,
      'X-LLM-Messages-Format': profile.messagesFormat,
    }
    if (isCustomModelEnabled()) {
      const model = getSelectedModel()
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
