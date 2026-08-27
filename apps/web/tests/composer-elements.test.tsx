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
  ComposerAccessPicker,
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
      <Thread workspaceContext={workspaceContext} />
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

afterEach(cleanup)

describe('composer preferences', () => {
  it('keeps model, effort, speed, and access changes local to the composer session', async () => {
    const user = userEvent.setup()
    render(
      <ComposerPreferencesProvider>
        <ComposerModelPicker />
        <ComposerAccessPicker />
      </ComposerPreferencesProvider>,
    )

    const getModelTrigger = () =>
      screen.getByRole('button', { name: 'Model and reasoning preferences' })
    expect(getModelTrigger()).toHaveTextContent('5.6 Luna High')
    expect(screen.getByRole('button', { name: 'Access mode' })).toHaveTextContent(
      'Full access',
    )

    await user.click(getModelTrigger())
    await user.click(
      await screen.findByRole('menuitemradio', { name: /openai\/gpt-4o-mini/i }),
    )
    expect(getModelTrigger()).toHaveTextContent('GPT-4o mini High')
    await user.click(await screen.findByRole('menuitemradio', { name: /^Low/ }))
    expect(getModelTrigger()).toHaveTextContent('GPT-4o mini Low')

    await user.click(await screen.findByRole('menuitem', { name: /fast mode/i }))
    expect(getModelTrigger()).toHaveTextContent('(Standard)')

    const accessTrigger = screen.getByRole('button', { name: 'Access mode' })
    await user.click(accessTrigger)
    await user.click(
      await screen.findByRole('menuitemradio', { name: /read-only/i }),
    )
    expect(accessTrigger).toHaveTextContent('Read-only')
    expect(screen.getByText(/not sent to the agent/i)).toBeInTheDocument()
    await user.keyboard('{Escape}')
    await waitFor(() => {
      expect(
        screen.queryByText(/not sent to the agent/i),
      ).not.toBeInTheDocument()
    })
    expect(accessTrigger).toHaveFocus()
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
