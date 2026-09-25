import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it } from 'vitest'

import {
  AssistantRuntimeProvider,
  CompositeAttachmentAdapter,
  ComposerPrimitive,
  SimpleImageAttachmentAdapter,
  SimpleTextAttachmentAdapter,
  useLocalRuntime,
  type AttachmentAdapter,
  type ChatModelAdapter,
} from '@assistant-ui/react'

import {
  ComposerModelPicker,
  ComposerPreferencesProvider,
  ComposerTriggerPopovers,
  type ComposerWorkspaceContext,
} from '@/components/assistant-ui/composer-elements'
import {
  ComposerAddAttachment,
  ComposerAttachments,
} from '@/components/assistant-ui/attachment'
import { Thread } from '@/components/assistant-ui/thread'
import { PROVIDERS_STORAGE_KEY } from '@/lib/providers'

const noOpAdapter: ChatModelAdapter = {
  async *run() {},
}

const attachmentAdapter = new CompositeAttachmentAdapter([
  new SimpleImageAttachmentAdapter(),
  new SimpleTextAttachmentAdapter(),
])

const workspaceContext: ComposerWorkspaceContext = {
  agentLabel: 'Fleet Agent',
  projectLabel: 'Workspace',
  threadLabel: 'First thread',
  projectId: 'project_1',
  threadId: 'thread_a',
}

function RuntimeComposer() {
  const runtime = useLocalRuntime(noOpAdapter)
  return (
    <AssistantRuntimeProvider runtime={runtime}>
      <ComposerPreferencesProvider>
        <Thread workspaceContext={workspaceContext} />
      </ComposerPreferencesProvider>
    </AssistantRuntimeProvider>
  )
}

function RuntimeInputComposer() {
  const runtime = useLocalRuntime(noOpAdapter)
  return (
    <AssistantRuntimeProvider runtime={runtime}>
      <ComposerPreferencesProvider>
        <ComposerPrimitive.Root>
          <ComposerPrimitive.Input aria-label="Message input" />
          <ComposerPrimitive.Send type="submit">Send</ComposerPrimitive.Send>
        </ComposerPrimitive.Root>
      </ComposerPreferencesProvider>
    </AssistantRuntimeProvider>
  )
}

function AttachmentRuntimeComposer({
  adapter = attachmentAdapter,
}: {
  adapter?: AttachmentAdapter
}) {
  const runtime = useLocalRuntime(noOpAdapter, {
    adapters: { attachments: adapter },
  })

  return (
    <AssistantRuntimeProvider runtime={runtime}>
      <ComposerPrimitive.Root>
        <ComposerPrimitive.AttachmentDropzone data-testid="attachment-dropzone">
          <ComposerAddAttachment />
          <ComposerAttachments />
        </ComposerPrimitive.AttachmentDropzone>
      </ComposerPrimitive.Root>
    </AssistantRuntimeProvider>
  )
}

afterEach(() => {
  cleanup()
  // The composer reads providers and keys from localStorage; clear it so each
  // test starts from the shipped defaults instead of the previous test's state.
  localStorage.clear()
})

describe('composer preferences', () => {
  it('selects the run model route from the settings store while effort, speed, and access stay session-only', async () => {
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
            id: 'modal-gw',
            name: 'Modal Gateway',
            baseUrl: 'https://fleet-proxy.modal.run/v1',
            apiKey: 'sk-test',
            modelId: 'zai-org/GLM-5.3-Flash',
            chatCompletionFormat: 'openai-chat-completions',
            responseFormat: 'json_tool_calls',
            messagesFormat: 'developer_role',
          },
        ],
        activeProviderId: 'server',
      }),
    )
    localStorage.setItem('openrouter_api_key', 'sk-test-openrouter')

    const user = userEvent.setup()
    render(
      <ComposerPreferencesProvider>
        <ComposerModelPicker />
      </ComposerPreferencesProvider>,
    )

    const getModelTrigger = () =>
      screen.getByRole('button', { name: 'Model and reasoning preferences' })
    expect(getModelTrigger()).toHaveTextContent('Server default model')

    await user.click(getModelTrigger())
    expect(await screen.findByText('Model')).toBeInTheDocument()
    expect(screen.queryByText(/^Provider$/)).not.toBeInTheDocument()
    expect(
      await screen.findByRole('menuitemradio', {
        name: /server default model.*server configuration/i,
      }),
    ).toBeInTheDocument()
    expect(
      screen.getByRole('menuitemradio', {
        name: /GPT-4o mini \(OpenAI\).*openai\/gpt-4o-mini.*via OpenRouter/i,
      }),
    ).toBeInTheDocument()
    // OpenCode Zen has no API key configured, so its models must not appear
    expect(
      screen.queryByRole('menuitemradio', {
        name: /via OpenCode Zen/i,
      }),
    ).not.toBeInTheDocument()
    expect(
      screen.getByRole('menuitemradio', {
        name: /zai-org\/GLM-5\.3-Flash.*via modal gateway/i,
      }),
    ).toBeInTheDocument()
    // A profile that pins a model id always sends that id, so no second
    // "default model" row may claim to route the provider default.
    expect(
      screen.queryByRole('menuitemradio', {
        name: /modal gateway default model/i,
      }),
    ).not.toBeInTheDocument()

    await user.click(
      screen.getByRole('menuitemradio', {
        name: /GPT-4o mini \(OpenAI\).*openai\/gpt-4o-mini.*via OpenRouter/i,
      }),
    )
    expect(getModelTrigger()).toHaveTextContent('GPT-4o mini (OpenAI)')

    const openRouterStored = JSON.parse(
      localStorage.getItem(PROVIDERS_STORAGE_KEY) ?? '{}',
    ) as { activeProviderId?: string }
    expect(openRouterStored.activeProviderId).toBe('openrouter')
    expect(localStorage.getItem('openrouter_selected_model')).toBe(
      'openai/gpt-4o-mini',
    )

    await user.click(
      await screen.findByRole('menuitemradio', {
        name: /zai-org\/GLM-5\.3-Flash.*via modal gateway/i,
      }),
    )
    expect(getModelTrigger()).toHaveTextContent('zai-org/GLM-5.3-Flash')

    const stored = JSON.parse(
      localStorage.getItem(PROVIDERS_STORAGE_KEY) ?? '{}',
    ) as { activeProviderId?: string }
    expect(stored.activeProviderId).toBe('modal-gw')

    // Reasoning effort is controlled via the assistant-ui element
    await user.click(await screen.findByRole('radio', { name: /^Low/ }))
    expect(
      screen.getByRole('radio', { name: /^Low/ }),
    ).toHaveAttribute('aria-checked', 'true')
    expect(getModelTrigger()).toHaveTextContent('zai-org/GLM-5.3-Flash')

    // Fast mode and Access are removed from the menu
    expect(screen.queryByText(/fast mode/i)).not.toBeInTheDocument()
    expect(screen.queryByText(/^Access$/i)).not.toBeInTheDocument()

    await user.keyboard('{Escape}')
    await waitFor(() => {
      expect(getModelTrigger()).toHaveAttribute('aria-expanded', 'false')
    })
    expect(getModelTrigger()).toHaveFocus()
  })

  it('does not mark an unconfigured provider model as the effective route', async () => {
    localStorage.removeItem('openrouter_api_key')
    localStorage.removeItem('opencode_zen_api_key')
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
        ],
        activeProviderId: 'openrouter',
      }),
    )

    render(
      <ComposerPreferencesProvider>
        <ComposerModelPicker />
      </ComposerPreferencesProvider>,
    )

    const trigger = screen.getByRole('button', {
      name: 'Model and reasoning preferences',
    })
    expect(trigger).toHaveTextContent('Server default model')

    expect(trigger).toHaveAttribute('data-unconfigured', 'true')

    const user = userEvent.setup()
    await user.click(trigger)
    expect(
      await screen.findByText(/OpenRouter has no API key yet/i),
    ).toBeInTheDocument()
    // Unconfigured OpenRouter models do not appear; only functional models appear
    expect(
      screen.queryByRole('menuitemradio', {
        name: /via OpenRouter/i,
      }),
    ).not.toBeInTheDocument()
    expect(
      screen.getByRole('menuitemradio', {
        name: /Server default model/i,
      }),
    ).toBeInTheDocument()

    // The composer names the fallback and keeps the stored choice, so a key
    // added later resumes the provider the user picked.
    const stored = JSON.parse(
      localStorage.getItem(PROVIDERS_STORAGE_KEY) ?? '{}',
    ) as { activeProviderId?: string }
    expect(stored.activeProviderId).toBe('openrouter')
  })

  it('keeps local preferences when the thread-specific Composer remounts', async () => {
    const user = userEvent.setup()
    function PickerView({ viewKey }: { viewKey: string }) {
      return (
        <div key={viewKey}>
          <ComposerModelPicker />
        </div>
      )
    }

    const view = render(
      <ComposerPreferencesProvider>
        <PickerView viewKey="thread-a" />
      </ComposerPreferencesProvider>,
    )

    const getModelTrigger = () =>
      screen.getByRole('button', { name: 'Model and reasoning preferences' })

    await user.click(getModelTrigger())
    await user.click(
      await screen.findByRole('radio', { name: /^Low/ }),
    )
    expect(
      screen.getByRole('radio', { name: /^Low/ }),
    ).toHaveAttribute('aria-checked', 'true')
    await user.keyboard('{Escape}')
    await waitFor(() => {
      expect(getModelTrigger()).toHaveAttribute('aria-expanded', 'false')
    })

    view.rerender(
      <ComposerPreferencesProvider>
        <PickerView viewKey="thread-b" />
      </ComposerPreferencesProvider>,
    )

    await user.click(getModelTrigger())
    expect(
      await screen.findByRole('radio', { name: /^Low/ }),
    ).toHaveAttribute('aria-checked', 'true')
    expect(getModelTrigger()).toHaveTextContent('Server default model')
  })
})

describe('composer context and trigger popovers', () => {
  it('labels the context budget as an estimate based on visible runtime state', () => {
    render(<RuntimeComposer />)

    expect(
      screen.getByRole('button', { name: 'Estimated context usage' }),
    ).toBeInTheDocument()
    expect(screen.getByText('Estimated context')).toBeInTheDocument()
    expect(
      screen.getByText(/visible messages and registered tools/i),
    ).toBeInTheDocument()
  })

  it('keeps the runtime composer surface compact while retaining local controls in the model menu', async () => {
    const user = userEvent.setup()
    render(<RuntimeComposer />)

    expect(screen.getByPlaceholderText('Ask anything')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Add attachment' })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Access mode' })).not.toBeInTheDocument()

    await user.click(
      screen.getByRole('button', { name: 'Model and reasoning preferences' }),
    )
    expect(await screen.findByText('Reasoning effort')).toBeInTheDocument()
    expect(screen.queryByText(/^Access$/)).not.toBeInTheDocument()
    expect(screen.queryByText(/fast mode/i)).not.toBeInTheDocument()
  })

  it('filters and inserts slash commands with keyboard navigation and restores focus', async () => {
    const user = userEvent.setup()
    render(<RuntimeComposer />)

    const input = screen.getByRole('textbox', { name: 'Message input' })
    await user.type(input, '/opt')

    const slashList = await screen.findByRole('listbox', { name: 'Slash commands' })
    expect(within(slashList).getByRole('option', { name: /\/optimize/i })).toBeInTheDocument()
    await waitFor(() => {
      expect(within(slashList).getAllByRole('option')).toHaveLength(1)
    })

    await user.keyboard('{Enter}')
    expect(input).toHaveValue('/optimize ')
    expect(input).toHaveFocus()

    await user.clear(input)
    await user.type(input, '/')
    await waitFor(() => {
      expect(
        within(screen.getByRole('listbox', { name: 'Slash commands' })).getAllByRole(
          'option',
        ),
      ).toHaveLength(4)
    })
    await user.keyboard('{ArrowDown}{Enter}')
    expect(input).toHaveValue('/report ')

    await user.clear(input)
    await user.type(input, '/op')
    expect(screen.getByRole('option', { name: /\/optimize/i })).toBeInTheDocument()
    await user.keyboard('{Escape}')
    expect(screen.queryByRole('listbox', { name: 'Slash commands' })).not.toBeInTheDocument()
    expect(input).toHaveFocus()
  })

  it('filters and inserts the active agent, project, and thread mentions', async () => {
    const user = userEvent.setup()
    render(<RuntimeComposer />)

    const input = screen.getByRole('textbox', { name: 'Message input' })

    await user.type(input, '@fle')
    expect(screen.getByRole('option', { name: /Fleet Agent/i })).toBeInTheDocument()
    await user.keyboard('{Enter}')
    expect(input).toHaveValue('@Fleet Agent ')

    await user.clear(input)
    await user.type(input, '@work')
    expect(screen.getByRole('option', { name: /Workspace/i })).toBeInTheDocument()
    await user.keyboard('{Enter}')
    expect(input).toHaveValue('@Workspace ')

    await user.clear(input)
    await user.type(input, '@first')
    expect(screen.getByRole('option', { name: /First thread/i })).toBeInTheDocument()
    await user.keyboard('{Enter}')
    expect(input).toHaveValue('@First thread ')
  })

  it('uses the runtime input for newline and submit behavior', async () => {
    const user = userEvent.setup()
    render(<RuntimeInputComposer />)

    const input = screen.getByRole('textbox', { name: 'Message input' })
    await user.type(input, 'hello')
    await user.keyboard('{Shift>}{Enter}{/Shift}')
    expect(input).toHaveValue('hello\n')

    await user.keyboard('{Enter}')
    await waitFor(() => expect(input).toHaveValue(''))
  })
})

describe('composer attachments', () => {
  it('supports picker, drop, preview metadata, removal, and accessible upload states', async () => {
    const user = userEvent.setup()
    render(<AttachmentRuntimeComposer />)

    const addAttachment = screen.getByRole('button', { name: 'Add attachment' })
    await user.click(addAttachment)

    const picker = await waitFor(() => {
      const input = document.querySelector<HTMLInputElement>('input[type="file"]')
      expect(input).toBeInTheDocument()
      return input as HTMLInputElement
    })
    await user.upload(
      picker,
      new File(['hello'], 'notes.md', { type: 'text/markdown' }),
    )

    const documentAttachment = await screen.findByRole('button', {
      name: 'Document attachment',
    })
    await user.hover(documentAttachment)
    expect(await screen.findByText('notes.md')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Remove notes.md' })).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: 'Remove notes.md' }))
    await waitFor(() => {
      expect(screen.queryByRole('button', { name: 'Document attachment' })).not.toBeInTheDocument()
    })

    const dropzone = screen.getByTestId('attachment-dropzone')
    fireEvent.drop(dropzone, {
      dataTransfer: {
        files: [new File([new Uint8Array([137, 80, 78, 71])], 'pixel.png', { type: 'image/png' })],
        types: ['Files'],
      },
    })
    expect(await screen.findByRole('button', { name: 'Image attachment' })).toBeInTheDocument()
  })

  it('announces local attachment progress and adapter errors without upload persistence', async () => {
    const user = userEvent.setup()
    let finishUpload!: () => void
    const adapter: AttachmentAdapter = {
      accept: 'text/plain',
      async *add({ file }) {
        yield {
          id: 'pending-error-attachment',
          type: 'document',
          name: file.name,
          contentType: file.type,
          file,
          status: { type: 'running', reason: 'uploading', progress: 42 },
        }
        await new Promise<void>((resolve) => {
          finishUpload = resolve
        })
        throw new Error('Local attachment processing failed')
      },
      async remove() {},
      async send(attachment) {
        return { ...attachment, status: { type: 'complete' }, content: [] }
      },
    }

    render(<AttachmentRuntimeComposer adapter={adapter} />)
    await user.click(screen.getByRole('button', { name: 'Add attachment' }))
    const picker = await waitFor(() =>
      document.querySelector<HTMLInputElement>('input[type="file"]'),
    )
    const uploadPromise = user.upload(
      picker!,
      new File(['hello'], 'broken.txt', { type: 'text/plain' }),
    )

    await waitFor(() =>
      expect(screen.getByRole('status')).toHaveTextContent(
        'broken.txt is uploading.',
      ),
    )
    finishUpload()
    await uploadPromise
    await waitFor(() =>
      expect(screen.getByRole('alert')).toHaveTextContent(
        'broken.txt: Local attachment processing failed',
      ),
    )
    expect(
      screen.getByRole('button', { name: 'Document attachment, upload failed' }),
    ).toBeInTheDocument()
  })
})

describe('ComposerTriggerPopovers', () => {
  it('can be mounted inside the assistant-ui popover root with a plain-text formatter', () => {
    function BareComposer() {
      const runtime = useLocalRuntime(noOpAdapter)
      return (
        <AssistantRuntimeProvider runtime={runtime}>
          <ComposerPrimitive.Unstable_TriggerPopoverRoot>
            <ComposerPrimitive.Root>
              <ComposerTriggerPopovers workspaceContext={workspaceContext} />
              <ComposerPrimitive.Input aria-label="Message input" />
            </ComposerPrimitive.Root>
          </ComposerPrimitive.Unstable_TriggerPopoverRoot>
        </AssistantRuntimeProvider>
      )
    }

    render(<BareComposer />)
    expect(screen.getByRole('textbox', { name: 'Message input' })).toBeInTheDocument()
  })
})
