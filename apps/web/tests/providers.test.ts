import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'

import {
  getApiKey,
  getSelectedModel,
  isCustomModelEnabled,
  setApiKey,
  setCustomModelEnabled,
  setSelectedModel,
  STORAGE_KEY,
} from '@/lib/openrouter-auth'
import {
  getApiKey as getOpenCodeZenApiKey,
  setApiKey as setOpenCodeZenApiKey,
  setSelectedModel as setOpenCodeZenSelectedModel,
  setCustomModelEnabled as setOpenCodeZenCustomModelEnabled,
  clearApiKey as clearOpenCodeZenApiKey,
  STORAGE_KEY as OPENCODE_ZEN_STORAGE_KEY,
} from '@/lib/opencode-zen-auth'
import {
  getActiveProfile,
  getActiveProviderId,
  getAgentProviderHeaders,
  getProfiles,
  loadProviderStore,
  OPENROUTER_BASE_URL,
  OPENROUTER_PROFILE_ID,
  OPENCODE_ZEN_BASE_URL,
  OPENCODE_ZEN_PROFILE_ID,
  PROVIDERS_STORAGE_KEY,
  removeProfile,
  SERVER_DEFAULT_ID,
  setActiveProviderId,
  upsertProfile,
} from '@/lib/providers'

describe('providers store', () => {
  beforeEach(() => {
    localStorage.clear()
    vi.restoreAllMocks()
  })

  afterEach(() => {
    localStorage.clear()
  })

  it('migrates a legacy OpenRouter key into an active OpenRouter profile', () => {
    setApiKey('sk-or-v1-legacykey123456')

    const store = loadProviderStore()

    expect(store.version).toBe(1)
    expect(store.activeProviderId).toBe(OPENROUTER_PROFILE_ID)
    // The default store ships the OpenRouter and OpenCode Zen presets
    // side-by-side; users see both on first load.
    expect(store.profiles).toEqual([
      expect.objectContaining({
        id: OPENROUTER_PROFILE_ID,
        name: 'OpenRouter',
        baseUrl: OPENROUTER_BASE_URL,
        responseFormat: 'native_function_calling',
        messagesFormat: 'system_role',
      }),
      expect.objectContaining({
        id: 'opencode-zen',
        name: 'OpenCode Zen',
        baseUrl: 'https://opencode.ai/zen/v1',
        responseFormat: 'native_function_calling',
        messagesFormat: 'system_role',
      }),
    ])
  })

  it('defaults to the server provider without a legacy key', () => {
    const store = loadProviderStore()

    expect(store.activeProviderId).toBe(SERVER_DEFAULT_ID)
  })

  it('returns no headers for the server default provider', () => {
    setApiKey('sk-or-v1-legacykey123456')

    expect(getActiveProviderId()).toBe(OPENROUTER_PROFILE_ID)
    setActiveProviderId(SERVER_DEFAULT_ID)

    expect(getAgentProviderHeaders()).toEqual({})
    expect(getActiveProfile()).toBeNull()
  })

  it('builds OpenRouter headers with the OAuth key and gated model', () => {
    setApiKey('sk-or-v1-legacykey123456')
    setSelectedModel('anthropic/claude-3.5-sonnet')
    setCustomModelEnabled(false)

    expect(getAgentProviderHeaders()).toEqual({
      'X-LLM-Key': 'sk-or-v1-legacykey123456',
      'X-LLM-Base-Url': OPENROUTER_BASE_URL,
      'X-LLM-Response-Format': 'native_function_calling',
      'X-LLM-Messages-Format': 'system_role',
    })

    setCustomModelEnabled(true)

    expect(getAgentProviderHeaders()).toEqual({
      'X-LLM-Key': 'sk-or-v1-legacykey123456',
      'X-LLM-Base-Url': OPENROUTER_BASE_URL,
      'X-LLM-Response-Format': 'native_function_calling',
      'X-LLM-Messages-Format': 'system_role',
      'X-LLM-Model': 'anthropic/claude-3.5-sonnet',
    })
  })

  it('sends no OpenRouter headers without a signed-in key', () => {
    loadProviderStore()
    setActiveProviderId(OPENROUTER_PROFILE_ID)
    expect(getApiKey()).toBeNull()

    expect(getAgentProviderHeaders()).toEqual({})
  })

  it('builds headers for a custom provider profile', () => {
    loadProviderStore()
    upsertProfile({
      id: 'profile-modal',
      name: 'Modal Gateway',
      baseUrl: 'https://fleet-proxy.modal.run/v1',
      apiKey: 'sk-modal-browser-key',
      modelId: 'openai/gpt-4o',
      chatCompletionFormat: 'openai-chat-completions',
      responseFormat: 'json_tool_calls',
      messagesFormat: 'developer_role',
    })
    setActiveProviderId('profile-modal')

    expect(getAgentProviderHeaders()).toEqual({
      'X-LLM-Key': 'sk-modal-browser-key',
      'X-LLM-Base-Url': 'https://fleet-proxy.modal.run/v1',
      'X-LLM-Model': 'openai/gpt-4o',
      'X-LLM-Response-Format': 'json_tool_calls',
      'X-LLM-Messages-Format': 'developer_role',
    })
  })

  it('skips incomplete custom profiles instead of sending partial credentials', () => {
    loadProviderStore()
    upsertProfile({
      id: 'profile-incomplete',
      name: 'Incomplete',
      chatCompletionFormat: 'openai-chat-completions',
      responseFormat: 'native_function_calling',
      messagesFormat: 'system_role',
    })
    setActiveProviderId('profile-incomplete')

    expect(getAgentProviderHeaders()).toEqual({})
  })

  it('updates and removes custom profiles, restoring the server default when active', () => {
    loadProviderStore()
    upsertProfile({
      id: 'profile-one',
      name: 'Gateway One',
      baseUrl: 'https://one.example/v1',
      apiKey: 'sk-one',
      chatCompletionFormat: 'openai-chat-completions',
      responseFormat: 'native_function_calling',
      messagesFormat: 'system_role',
    })
    upsertProfile({
      id: 'profile-one',
      name: 'Gateway One Renamed',
      baseUrl: 'https://one.example/v2',
      apiKey: 'sk-one',
      chatCompletionFormat: 'openai-chat-completions',
      responseFormat: 'json_tool_calls',
      messagesFormat: 'system_role',
    })
    setActiveProviderId('profile-one')

    const profiles = getProfiles()
    // OpenRouter preset + OpenCode Zen preset + one custom.
    expect(profiles).toHaveLength(3)
    const custom = profiles.find((p) => p.id === 'profile-one')
    expect(custom).toMatchObject({
      name: 'Gateway One Renamed',
      baseUrl: 'https://one.example/v2',
      responseFormat: 'json_tool_calls',
    })

    removeProfile('profile-one')

    expect(getProfiles()).toHaveLength(2)
    expect(getActiveProviderId()).toBe(SERVER_DEFAULT_ID)
  })

  it('protects the OpenRouter preset from removal and unknown active ids', () => {
    loadProviderStore()

    removeProfile(OPENROUTER_PROFILE_ID)
    expect(getProfiles().map((p) => p.id)).toContain(OPENROUTER_PROFILE_ID)

    setActiveProviderId('does-not-exist')
    expect(getActiveProviderId()).toBe(SERVER_DEFAULT_ID)

    // Custom models stay untouched by provider selection.
    expect(isCustomModelEnabled()).toBe(false)
    expect(getSelectedModel()).toBe('openai/gpt-4o-mini')
  })

  it('reinitializes from corrupt storage without throwing', () => {
    localStorage.setItem(PROVIDERS_STORAGE_KEY, '{not json')

    const store = loadProviderStore()
    expect(store.version).toBe(1)
    expect(store.activeProviderId).toBe(SERVER_DEFAULT_ID)
  })

  it('keeps the legacy OpenRouter storage out of the provider store', () => {
    setApiKey('sk-or-v1-legacykey123456')
    loadProviderStore()

    const raw = localStorage.getItem(PROVIDERS_STORAGE_KEY)
    expect(raw).not.toContain('sk-or-v1-legacykey123456')
    expect(localStorage.getItem(STORAGE_KEY)).toBe('sk-or-v1-legacykey123456')
  })

  describe('OpenCode Zen preset', () => {
    it('exposes the OpenCode Zen preset alongside OpenRouter', () => {
      const profiles = getProfiles()
      const ids = profiles.map((p) => p.id)
      expect(ids).toContain(OPENROUTER_PROFILE_ID)
      expect(ids).toContain(OPENCODE_ZEN_PROFILE_ID)
    })

    it('builds agent headers for the OpenCode Zen preset', () => {
      setOpenCodeZenApiKey('zen-browser-key-1234')
      setOpenCodeZenCustomModelEnabled(true)
      setOpenCodeZenSelectedModel('muse-spark-1.3-contributor-free')
      setActiveProviderId(OPENCODE_ZEN_PROFILE_ID)

      expect(getAgentProviderHeaders()).toEqual({
        'X-LLM-Key': 'zen-browser-key-1234',
        'X-LLM-Base-Url': OPENCODE_ZEN_BASE_URL,
        'X-LLM-Response-Format': 'native_function_calling',
        'X-LLM-Messages-Format': 'system_role',
        'X-LLM-Model': 'muse-spark-1.3-contributor-free',
      })

      // The browser key never leaves storage; it must not appear in the
      // generic Fleet provider registry.
      const raw = localStorage.getItem(PROVIDERS_STORAGE_KEY)
      expect(raw).not.toContain('zen-browser-key-1234')
      expect(localStorage.getItem(OPENCODE_ZEN_STORAGE_KEY)).toBe(
        'zen-browser-key-1234',
      )
    })

    it('omits the model override when the custom-model toggle is off', () => {
      setOpenCodeZenApiKey('zen-browser-key-1234')
      setOpenCodeZenCustomModelEnabled(false)
      setOpenCodeZenSelectedModel('claude-opus-4-8')
      setActiveProviderId(OPENCODE_ZEN_PROFILE_ID)

      const headers = getAgentProviderHeaders()
      expect(headers).not.toHaveProperty('X-LLM-Model')
      expect(headers['X-LLM-Base-Url']).toBe(OPENCODE_ZEN_BASE_URL)
    })

    it('returns no OpenCode Zen headers without a key', () => {
      clearOpenCodeZenApiKey()
      setActiveProviderId(OPENCODE_ZEN_PROFILE_ID)
      expect(getOpenCodeZenApiKey()).toBeNull()
      expect(getAgentProviderHeaders()).toEqual({})
    })

    it('protects the OpenCode Zen preset from removal and from foreign base URLs', () => {
      loadProviderStore()

      removeProfile(OPENCODE_ZEN_PROFILE_ID)
      expect(getProfiles().map((p) => p.id)).toContain(OPENCODE_ZEN_PROFILE_ID)

      // A malicious override cannot repoint the preset at a different base URL.
      upsertProfile({
        id: OPENCODE_ZEN_PROFILE_ID,
        name: 'OpenCode Zen',
        baseUrl: 'https://attacker.example/v1',
        apiKey: 'stolen',
        chatCompletionFormat: 'openai-chat-completions',
        responseFormat: 'native_function_calling',
        messagesFormat: 'system_role',
      })

      const preset = getProfiles().find((p) => p.id === OPENCODE_ZEN_PROFILE_ID)
      expect(preset?.baseUrl).toBe(OPENCODE_ZEN_BASE_URL)
    })
  })
})
