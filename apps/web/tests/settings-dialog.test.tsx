import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { render, screen, cleanup } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import type { ComponentProps } from 'react'
import userEvent from '@testing-library/user-event'
import { SettingsDialog } from '@/features/providers/settings/settings-dialog'
import * as openrouterAuth from '@/features/providers/openrouter-auth'
import {
  getActiveProviderId,
  getAgentProviderHeaders,
  getProfiles,
  loadProviderStore,
  PROVIDERS_STORAGE_KEY,
  SERVER_DEFAULT_ID,
} from '@/features/providers/providers-store'

function renderDialog(props: ComponentProps<typeof SettingsDialog>) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  return render(
    <QueryClientProvider client={queryClient}>
      <SettingsDialog {...props} />
    </QueryClientProvider>,
  )
}

describe('SettingsDialog', () => {
  beforeEach(() => {
    localStorage.clear()
    sessionStorage.clear()
    vi.restoreAllMocks()
    vi.stubGlobal(
      'fetch',
      vi.fn().mockImplementation((url: string) => {
        if (String(url).includes('/models')) {
          return Promise.resolve({
            ok: true,
            status: 200,
            json: async () => ({
              data: [
                {
                  id: 'anthropic/claude-3.5-sonnet',
                  name: 'Claude 3.5 Sonnet',
                },
                { id: 'openai/gpt-4o-mini', name: 'GPT-4o mini' },
              ],
            }),
          })
        }
        return Promise.resolve({
          ok: true,
          status: 200,
          json: async () => ({}),
        })
      }),
    )
  })

  afterEach(() => {
    cleanup()
  })

  it('renders disconnected state when no API key is present', () => {
    renderDialog({ open: true, onOpenChange: vi.fn() })

    expect(screen.getByText(/workspace settings/i)).toBeInTheDocument()
    // Both OpenRouter and OpenCode Zen start in the disconnected state.
    expect(screen.getAllByText('Disconnected').length).toBeGreaterThanOrEqual(2)
    expect(
      screen.getByRole('button', { name: /sign in with openrouter/i }),
    ).toBeInTheDocument()
    expect(
      screen.getByRole('button', { name: /or paste api key manually/i }),
    ).toBeInTheDocument()
    expect(
      screen.getByRole('button', { name: /add opencode zen api key/i }),
    ).toBeInTheDocument()
  })

  it('switches settings sections from the sidebar and compact selector', async () => {
    const user = userEvent.setup()
    renderDialog({ open: true, onOpenChange: vi.fn() })

    await user.click(screen.getByRole('button', { name: 'Models' }))
    expect(
      screen.getByRole('region', { name: 'models settings' }),
    ).toBeInTheDocument()
    expect(
      await screen.findByRole('button', { name: /claude 3\.5 sonnet/i }),
    ).toBeInTheDocument()

    await user.selectOptions(
      screen.getByRole('combobox', { name: 'Settings section' }),
      'appearance',
    )
    expect(
      screen.getByRole('region', { name: 'appearance settings' }),
    ).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'System' })).toBeInTheDocument()
  })

  it('allows manual API key entry', async () => {
    const user = userEvent.setup()
    renderDialog({ open: true, onOpenChange: vi.fn() })

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

    renderDialog({ open: true, onOpenChange: vi.fn() })

    // OpenRouter is now connected; OpenCode Zen stays disconnected.
    expect(screen.getAllByText('Connected').length).toBe(1)
    expect(screen.getAllByText('Disconnected').length).toBe(1)
    expect(screen.getByText(/sk-or-v1••••••••cdef/i)).toBeInTheDocument()
    expect(
      screen.getByText(/app attribution configured/i),
    ).toBeInTheDocument()

    const disconnectButton = screen.getByRole('button', { name: /disconnect/i })
    await user.click(disconnectButton)

    expect(openrouterAuth.getApiKey()).toBeNull()
  })

  it('toggles custom model selection and selects from fetched models', async () => {
    const user = userEvent.setup()
    renderDialog({ open: true, onOpenChange: vi.fn() })

    await user.click(screen.getByRole('button', { name: 'Models' }))
    const claudeButton = await screen.findByRole('button', {
      name: /claude 3.5 sonnet/i,
    })
    await user.click(claudeButton)

    expect(openrouterAuth.getSelectedModel()).toBe('anthropic/claude-3.5-sonnet')
  })

  it('adds a custom provider through the settings form and activates it', async () => {
    const user = userEvent.setup()
    renderDialog({ open: true, onOpenChange: vi.fn() })

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
    // OpenRouter + OpenCode Zen presets + the newly added custom profile.
    expect(profiles).toHaveLength(3)
    const custom = profiles.find((p) => p.name === 'Modal Gateway')
    expect(custom).toMatchObject({
      name: 'Modal Gateway',
      baseUrl: 'https://fleet-proxy.modal.run/v1',
      apiKey: 'sk-modal-key',
      modelId: 'openai/gpt-4o',
      responseFormat: 'json_tool_calls',
      messagesFormat: 'system_role',
    })
    expect(getActiveProviderId()).toBe(custom?.id)
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

    renderDialog({ open: true, onOpenChange: vi.fn() })

    expect(getActiveProviderId()).toBe('profile-modal')

    await user.click(screen.getByRole('button', { name: /delete modal gateway/i }))

    // The two built-in presets (OpenRouter + OpenCode Zen) are protected and
    // re-appear in the profile list when missing from localStorage.
    expect(getProfiles()).toHaveLength(2)
    expect(getActiveProviderId()).toBe(SERVER_DEFAULT_ID)
    expect(getAgentProviderHeaders()).toEqual({})
  })

  it('activates the server default provider from the settings dialog', async () => {
    const user = userEvent.setup()
    openrouterAuth.setApiKey('sk-or-v1-9876543210abcdef')
    renderDialog({ open: true, onOpenChange: vi.fn() })

    // The migrated OpenRouter key makes OpenRouter the active provider.
    expect(getActiveProviderId()).toBe('openrouter')

    await user.click(
      screen.getByRole('button', { name: /server default/i }),
    )

    expect(getActiveProviderId()).toBe(SERVER_DEFAULT_ID)
    expect(getAgentProviderHeaders()).toEqual({})
  })
})
