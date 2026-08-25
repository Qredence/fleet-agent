import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import {
  AssistantRuntimeProvider,
  MessagePrimitive,
  ThreadPrimitive,
  useLocalRuntime,
  type ChatModelAdapter,
  type ThreadMessageLike,
} from '@assistant-ui/react'

import { InlineAgentDataUIRegistration } from '@/features/agent-runtime/inline-agent-data-ui'

const noOpAdapter: ChatModelAdapter = {
  async *run() {},
}

function Runtime({
  message,
}: {
  message: ThreadMessageLike
}) {
  const runtime = useLocalRuntime(noOpAdapter, {
    initialMessages: [message],
  })
  return (
    <AssistantRuntimeProvider runtime={runtime}>
      <InlineAgentDataUIRegistration />
      <ThreadPrimitive.Messages
        components={{
          Message: () => (
            <MessagePrimitive.Root>
              <MessagePrimitive.Parts />
            </MessagePrimitive.Root>
          ),
        }}
      />
    </AssistantRuntimeProvider>
  )
}

describe('inline assistant-ui agent surfaces', () => {
  it('renders a safe progress projection with skipped critique and mixed research states', async () => {
    render(
      <Runtime
        message={{
          role: 'assistant',
          content: [
            {
              type: 'data',
              name: 'agent-progress',
              data: {
                schemaVersion: 1,
                steps: [
                  { id: 'planning', label: 'Planning', status: 'completed' },
                  { id: 'research', label: 'Parallel research', status: 'running' },
                  { id: 'critique', label: 'Verification', status: 'skipped' },
                  { id: 'synthesis', label: 'Synthesis', status: 'pending' },
                ],
                activeIndex: 1,
                tools: [
                  { id: 'r1', name: 'research', target: 'Docs', state: 'done' },
                  { id: 'r2', name: 'research', target: 'Web', state: 'failed' },
                ],
              },
            },
          ],
          status: { type: 'complete', reason: 'stop' },
        }}
      />,
    )

    expect(await screen.findByText('Parallel research')).toBeInTheDocument()
    expect(screen.getByText('Verification')).toBeInTheDocument()
    expect(screen.getByText('Parallel research tasks')).toBeInTheDocument()
    expect(screen.getByText('1 failed')).toBeInTheDocument()
  })

  it('renders web search, sources, and report projections from versioned data', async () => {
    render(
      <Runtime
        message={{
          role: 'assistant',
          content: [
            {
              type: 'data',
              name: 'web-search',
              data: {
                schemaVersion: 1,
                query: 'DSPy Parallel',
                results: [{ title: 'DSPy docs', domain: 'dspy.ai' }],
                visibleResults: 1,
                searching: false,
                cycle: 1,
              },
            },
            {
              type: 'data',
              name: 'sources',
              data: {
                schemaVersion: 1,
                sources: [{ title: 'DSPy docs', domain: 'dspy.ai' }],
              },
            },
            {
              type: 'data',
              name: 'research-report',
              data: {
                schemaVersion: 1,
                title: 'Research report',
                sections: [
                  {
                    id: 'research',
                    heading: 'Research evidence',
                    state: 'done',
                    sources: 1,
                  },
                ],
                sourcesRead: 1,
              },
            },
          ],
          status: { type: 'complete', reason: 'stop' },
        }}
      />,
    )

    expect(await screen.findByText('DSPy Parallel')).toBeInTheDocument()
    expect(screen.getByText('Read 1 source')).toBeInTheDocument()
    expect(screen.getByText('Sources')).toBeInTheDocument()
    expect(screen.getByText('Research report')).toBeInTheDocument()
  })

  it('does not render unversioned data payloads', async () => {
    render(
      <Runtime
        message={{
          role: 'assistant',
          content: [
            {
              type: 'data',
              name: 'agent-progress',
              data: { steps: [{ label: 'raw prompt should not render' }] },
            },
          ],
          status: { type: 'complete', reason: 'stop' },
        }}
      />,
    )

    expect(screen.queryByText('raw prompt should not render')).not.toBeInTheDocument()
  })
})
