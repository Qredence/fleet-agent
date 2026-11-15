import { afterEach, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import {
  AssistantRuntimeProvider,
  useLocalRuntime,
  type ChatModelAdapter,
} from '@assistant-ui/react'
import { RunSaveNotice, UnsavedAnswer } from '@/features/agent-runtime/run-save-notice'
const { state } = vi.hoisted(() => ({ state: { value: {} as Record<string, unknown> } }))
vi.mock('@/features/agent-runtime/ag-ui-presence', () => ({ useHasAgUiRuntime: () => true }))
vi.mock('@assistant-ui/react-ag-ui', () => ({ useAgUiState: () => state.value }))
afterEach(() => {
  cleanup()
  vi.useRealTimers()
  vi.restoreAllMocks()
})

const noOpAdapter: ChatModelAdapter = { async *run() {} }

function UnsavedHarness() {
  const runtime = useLocalRuntime(noOpAdapter, {
    initialMessages: [
      { role: 'assistant', content: [{ type: 'text', text: 'Answer text' }] },
    ],
  })
  return (
    <AssistantRuntimeProvider runtime={runtime}>
      <UnsavedAnswer />
    </AssistantRuntimeProvider>
  )
}

it('renders an empty initial AG-UI state safely', () => {
  state.value = {}
  expect(render(<RunSaveNotice />).container).toBeEmptyDOMElement()
})
it('separates partial evidence from a successful durable save', () => {
  state.value = { run: { status: 'completed', saveStatus: 'saved', evidenceStatus: 'partial' } }
  render(<RunSaveNotice />)
  expect(screen.getByText('Saved')).toBeInTheDocument()
  expect(screen.getByText('Evidence collection stopped early.')).toBeInTheDocument()
})
it('attaches download link before click, defers revokeObjectURL, and handles clipboard errors', () => {
  vi.useFakeTimers()
  const create = vi.spyOn(URL, 'createObjectURL').mockReturnValue('blob:answer')
  const revoke = vi.spyOn(URL, 'revokeObjectURL').mockImplementation(() => {})
  const click = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(function (this: HTMLAnchorElement) {
    expect(this.isConnected).toBe(true)
  })
  const writeText = vi.fn().mockRejectedValue(new Error('denied'))
  Object.defineProperty(navigator, 'clipboard', {
    configurable: true,
    value: { writeText },
  })

  render(<UnsavedHarness />)
  fireEvent.click(screen.getByRole('button', { name: 'Copy answer' }))
  expect(writeText).toHaveBeenCalledWith('Answer text')

  fireEvent.click(screen.getByRole('button', { name: 'Download Markdown' }))
  expect(create).toHaveBeenCalledTimes(1)
  expect(click).toHaveBeenCalledTimes(1)
  expect(revoke).not.toHaveBeenCalled()
  vi.runAllTimers()
  expect(revoke).toHaveBeenCalledWith('blob:answer')
})
