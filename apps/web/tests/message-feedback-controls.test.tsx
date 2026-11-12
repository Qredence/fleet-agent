import { beforeEach, afterEach, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { FeedbackThreadContext, MessageFeedbackControls } from '@/features/agent-runtime/message-feedback-controls'
import { queryClient } from '@/lib/query-client'
vi.mock('@assistant-ui/react', () => ({ useAuiState: (select: (state: unknown) => unknown) => select({ message: { id: 'assistant', status: { type: 'complete' } } }) }))
beforeEach(() => queryClient.clear())
afterEach(() => { cleanup(); queryClient.clear(); vi.unstubAllGlobals() })
it('saves, restores and clears feedback through the server resource', async () => {
  const stored: Record<string, { messageId: string; type: 'positive' | 'negative' }> = {}
  vi.stubGlobal('fetch', vi.fn(async (_url: string, init?: RequestInit) => {
    if (init?.method === 'PUT') {
      const body = JSON.parse(String(init.body))
      stored.assistant = body
      return new Response(JSON.stringify(body))
    }
    if (init?.method === 'DELETE') { delete stored.assistant; return new Response(null, { status: 204 }) }
    return new Response(JSON.stringify(stored))
  }))
  const view = render(<FeedbackThreadContext.Provider value="thread"><MessageFeedbackControls /></FeedbackThreadContext.Provider>)
  fireEvent.click(screen.getByRole('button', { name: 'Good response' }))
  await screen.findByRole('button', { name: 'Clear feedback' })
  expect(screen.getByRole('button', { name: 'Good response' })).toHaveAttribute('aria-pressed', 'true')
  view.unmount()
  render(<FeedbackThreadContext.Provider value="thread"><MessageFeedbackControls /></FeedbackThreadContext.Provider>)
  await screen.findByRole('button', { name: 'Clear feedback' })
  fireEvent.click(screen.getByRole('button', { name: 'Clear feedback' }))
  await waitFor(() => expect(screen.queryByRole('button', { name: 'Clear feedback' })).not.toBeInTheDocument())
  expect(stored.assistant).toBeUndefined()
})
