import { afterEach, expect, it, vi } from 'vitest'
import { cleanup, render, screen } from '@testing-library/react'
import { RunSaveNotice } from '@/features/agent-runtime/run-save-notice'
const { state } = vi.hoisted(() => ({ state: { value: {} as Record<string, unknown> } }))
vi.mock('@/features/agent-runtime/ag-ui-presence', () => ({ useHasAgUiRuntime: () => true }))
vi.mock('@assistant-ui/react-ag-ui', () => ({ useAgUiState: () => state.value }))
afterEach(cleanup)
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
