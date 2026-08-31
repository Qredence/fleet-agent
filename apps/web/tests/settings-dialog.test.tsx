import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { render, screen, cleanup } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { SettingsDialog } from '@/components/settings/settings-dialog'
import * as openrouterAuth from '@/lib/openrouter-auth'
import {
  getActiveProviderId,
  getAgentProviderHeaders,
  getProfiles,
  loadProviderStore,
  PROVIDERS_STORAGE_KEY,
  SERVER_DEFAULT_ID,
} from '@/lib/providers'

describe('SettingsDialog', () => {
  beforeEach(() => {
    localStorage.clear()
    sessionStorage.clear()
    vi.restoreAllMocks()
  })

  afterEach(() => {
    cleanup()
  })

  it('renders disconnected state when no API key is present', () => {
    render(<SettingsDialog open={true} onOpenChange={vi.fn()} />)

    expect(screen.getByText(/workspace settings/i)).toBeInTheDocument()
    expect(screen.getByText('Disconnected')).toBeInTheDocument()
    expect(
      screen.getByRole('button', { name: /sign in with openrouter/i }),
    ).toBeInTheDocument()
    expect(
      screen.getByRole('button', { name: /or paste api key manually/i }),
    ).toBeInTheDocument()
  })

  it('allows manual API key entry', async () => {
    const user = userEvent.setup()
    render(<SettingsDialog open={true} onOpenChange={vi.fn()} />)

    const toggleButton = screen.getByRole('button', {
      name: /or paste api key manually/i,
    })
    await user.click(toggleButton)

    const input = screen.getByPlaceholderText('sk-or-v1-...')
    await user.type(input, 'sk-or-v1-testmanualkey1234')

    const saveButton = screen.getByRole('button', { name: /save key/i })
    await user.click(saveButton)

    expect(openrouterAuth.getApiKey()).toBe('sk-or-v1-testmanualkey1234')
  })

  it('renders connected state when API key is present and allows disconnecting', async () => {
    const user = userEvent.setup()
    openrouterAuth.setApiKey('sk-or-v1-9876543210abcdef')

    render(<SettingsDialog open={true} onOpenChange={vi.fn()} />)

    expect(screen.getByText('Connected')).toBeInTheDocument()
    expect(screen.getByText(/sk-or-v1••••••••cdef/i)).toBeInTheDocument()
    expect(
      screen.getByText(/app attribution configured/i),
    ).toBeInTheDocument()

    const disconnectButton = screen.getByRole('button', { name: /disconnect/i })
    await user.click(disconnectButton)

    expect(openrouterAuth.getApiKey()).toBeNull()
  })

  it('toggles custom model selection and selects popular models', async () => {
    const user = userEvent.setup()
    render(<SettingsDialog open={true} onOpenChange={vi.fn()} />)

    const claudeButton = screen.getByRole('button', {
      name: /claude 3.5 sonnet/i,
    })
    await user.click(claudeButton)

    expect(openrouterAuth.getSelectedModel()).toBe('anthropic/claude-3.5-sonnet')
  })

  it('adds a custom provider through the settings form and activates it', async () => {
    const user = userEvent.setup()
    render(<SettingsDialog open={true} onOpenChange={vi.fn()} />)

    await user.click(screen.getByRole('button', { name: /add provider/i }))

    await user.type(screen.getByLabelText(/^provider name/i), 'Modal Gateway')
    await user.type(
      screen.getByLabelText(/^base url/i),
      'https://fleet-proxy.modal.run/v1',
    )
    await user.type(screen.getByLabelText(/^api key/i), 'sk-modal-key')
    await user.type(screen.getByLabelText(/^model id/i), 'openai/gpt-4o')

    await user.click(screen.getByRole('button', { name: /json tool calls/i }))

    await user.click(screen.getByRole('button', { name: /save provider/i }))

    const profiles = getProfiles()
    expect(profiles).toHaveLength(2)
    expect(profiles[1]).toMatchObject({
      name: 'Modal Gateway',
      baseUrl: 'https://fleet-proxy.modal.run/v1',
      apiKey: 'sk-modal-key',
      modelId: 'openai/gpt-4o',
      responseFormat: 'json_tool_calls',
      messagesFormat: 'system_role',
    })
    expect(getActiveProviderId()).toBe(profiles[1].id)
    expect(getAgentProviderHeaders()['X-LLM-Base-Url']).toBe(
      'https://fleet-proxy.modal.run/v1',
    )
  })

  it('falls back to the server default when the active provider is removed', async () => {
    const user = userEvent.setup()
    localStorage.setItem(
      PROVIDERS_STORAGE_KEY,
      JSON.stringify({
        version: 1,
        profiles: [
          {
            id: 'openrouter',
            name: 'OpenRouter',
            baseUrl: 'https://openrouter.ai/api/v1',
            chatCompletionFormat: 'openai-chat-completions',
            responseFormat: 'native_function_calling',
            messagesFormat: 'system_role',
          },
          {
            id: 'profile-modal',
            name: 'Modal Gateway',
            baseUrl: 'https://fleet-proxy.modal.run/v1',
            apiKey: 'sk-modal-key',
            chatCompletionFormat: 'openai-chat-completions',
            responseFormat: 'native_function_calling',
            messagesFormat: 'system_role',
          },
        ],
        activeProviderId: 'profile-modal',
      }),
    )
    loadProviderStore()

    render(<SettingsDialog open={true} onOpenChange={vi.fn()} />)

    expect(getActiveProviderId()).toBe('profile-modal')

    await user.click(screen.getByRole('button', { name: /delete modal gateway/i }))

    expect(getProfiles()).toHaveLength(1)
    expect(getActiveProviderId()).toBe(SERVER_DEFAULT_ID)
    expect(getAgentProviderHeaders()).toEqual({})
  })

  it('activates the server default provider from the settings dialog', async () => {
    const user = userEvent.setup()
    openrouterAuth.setApiKey('sk-or-v1-9876543210abcdef')
    render(<SettingsDialog open={true} onOpenChange={vi.fn()} />)

    // The migrated OpenRouter key makes OpenRouter the active provider.
    expect(getActiveProviderId()).toBe('openrouter')

    await user.click(
      screen.getByRole('button', { name: /server default/i }),
    )

    expect(getActiveProviderId()).toBe(SERVER_DEFAULT_ID)
    expect(getAgentProviderHeaders()).toEqual({})
  })
})
