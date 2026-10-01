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

import providerContract from '@fleet-agent/contracts/provider.json'

import {
  getApiKey as getOpenRouterApiKey,
  onAuthChange as onOpenRouterAuthChange,
  getSelectedModel as getOpenRouterSelectedModel,
  isCustomModelEnabled as isOpenRouterCustomModelEnabled,
} from '@/features/providers/openrouter-auth'
import {
  getApiKey as getOpenCodeZenApiKey,
  onAuthChange as onOpenCodeZenAuthChange,
  getSelectedModel as getOpenCodeZenSelectedModel,
  isCustomModelEnabled as isOpenCodeZenCustomModelEnabled,
} from '@/features/providers/opencode-zen-auth'

export const PROVIDERS_STORAGE_KEY = 'fleet_providers_v1'
export const OPENROUTER_PROFILE_ID = 'openrouter'
export const OPENROUTER_BASE_URL = providerContract.openRouter.apiBaseUrl
export const OPENCODE_ZEN_PROFILE_ID = 'opencode-zen'
export const OPENCODE_ZEN_BASE_URL = providerContract.openCodeZen.apiBaseUrl

export type ChatCompletionFormat = 'openai-chat-completions'
// These unions are static TypeScript types; a contract test keeps them in sync
// with the canonical lists in packages/contracts/provider.json.
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
  /** Explicit browser selection; null means setup is required. */
  activeProviderId: string | null
}

type ProvidersListener = () => void
const listeners = new Set<ProvidersListener>()

/** Subscribes to provider selection/profile changes in this tab and others. */
export const onProvidersChange = (fn: ProvidersListener): (() => void) => {
  listeners.add(fn)
  const unsubscribeOpenRouter = onOpenRouterAuthChange(fn)
  const unsubscribeOpenCodeZen = onOpenCodeZenAuthChange(fn)
  return () => {
    listeners.delete(fn)
    unsubscribeOpenRouter()
    unsubscribeOpenCodeZen()
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
    if (event.key === null || event.key === PROVIDERS_STORAGE_KEY) {
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
  activeProviderId: null,
})

type StoredProviderStore = Omit<ProviderStore, 'activeProviderId'> & { activeProviderId?: unknown }

const isValidStore = (value: unknown): value is StoredProviderStore => {
  if (typeof value !== 'object' || value === null) return false
  const store = value as Partial<ProviderStore>
  return (
    store.version === 1 &&
    Array.isArray(store.profiles) &&
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

/** Loads profiles and normalizes legacy or invalid selections without discarding credentials. */
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
    if (isValidStore(parsed)) {
      const validIds = new Set([
        OPENROUTER_PROFILE_ID,
        OPENCODE_ZEN_PROFILE_ID,
        ...parsed.profiles.map((profile) => profile.id),
      ])
      const activeProviderId =
        typeof parsed.activeProviderId === 'string' &&
        parsed.activeProviderId !== 'server' &&
        validIds.has(parsed.activeProviderId)
          ? parsed.activeProviderId
          : null
      const store: ProviderStore = { ...parsed, activeProviderId }
      if (activeProviderId !== parsed.activeProviderId) {
        try {
          localStorage.setItem(PROVIDERS_STORAGE_KEY, JSON.stringify(store))
        } catch {
          // Keep the normalized profiles usable even when storage is read-only.
        }
      }
      return store
    }
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

export function getActiveProviderId(): string | null {
  return loadProviderStore().activeProviderId
}

export function getActiveProfile(): ProviderProfile | null {
  return getProfiles().find((profile) => profile.id === getActiveProviderId()) ?? null
}

export function setActiveProviderId(id: string | null): void {
  const store = loadProviderStore()
  if (id !== null && !getProfiles().some((profile) => profile.id === id)) return
  saveProviderStore({ ...store, activeProviderId: id })
}

export interface ProviderReadiness {
  ready: boolean
  message: string
}

/** Shared readiness for selectors, composers, and every browser agent POST. */
export function getProviderReadiness(
  id: string | null = getActiveProviderId(),
): ProviderReadiness {
  const profile = getProfiles().find((entry) => entry.id === id)
  if (!profile) {
    return {
      ready: false,
      message: 'Choose a provider in Settings → Providers before sending a message.',
    }
  }
  const key = profile.id === OPENROUTER_PROFILE_ID
    ? getOpenRouterApiKey()
    : profile.id === OPENCODE_ZEN_PROFILE_ID
      ? getOpenCodeZenApiKey()
      : profile.apiKey
  if (!key?.trim() || !profile.baseUrl?.trim()) {
    return {
      ready: false,
      message: `${profile.name} needs setup. Add an API key and endpoint in Settings → Providers.`,
    }
  }
  return { ready: true, message: '' }
}

export class ProviderNotReadyError extends Error {
  constructor(message: string) {
    super(message)
    this.name = 'ProviderNotReadyError'
  }
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
 * Removes a custom profile; deleting the active one clears selection.
 * Built-in preset profiles (OpenRouter, OpenCode Zen) cannot be removed:
 * they are owned by the registry and re-appear in `getProfiles()` when
 * missing, so removing them is a no-op.
 */
export function removeProfile(id: string): void {
  if (id === OPENROUTER_PROFILE_ID || id === OPENCODE_ZEN_PROFILE_ID) return
  const store = loadProviderStore()
  const profiles = store.profiles.filter((profile) => profile.id !== id)
  const activeProviderId =
    store.activeProviderId === id ? null : store.activeProviderId
  saveProviderStore({ ...store, profiles, activeProviderId })
}

/** Agent-POST-only provider headers for the active profile. */
export function getAgentProviderHeaders(): Record<string, string> {
  const readiness = getProviderReadiness()
  if (!readiness.ready) throw new ProviderNotReadyError(readiness.message)
  const profile = getActiveProfile()!

  if (profile.id === OPENROUTER_PROFILE_ID) {
    const key = getOpenRouterApiKey()
    if (!key) throw new ProviderNotReadyError(getProviderReadiness().message)
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
    if (!key) throw new ProviderNotReadyError(getProviderReadiness().message)
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

  const headers: Record<string, string> = {
    'X-LLM-Key': profile.apiKey!.trim(),
    'X-LLM-Base-Url': profile.baseUrl!.trim(),
    'X-LLM-Response-Format': profile.responseFormat,
    'X-LLM-Messages-Format': profile.messagesFormat,
  }
  if (profile.modelId?.trim()) headers['X-LLM-Model'] = profile.modelId.trim()
  return headers
}
