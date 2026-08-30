import { afterEach, describe, expect, it, vi } from 'vitest'

const fetchBootstrapMock = vi.fn()
const persistThreadHeadMock = vi.fn()
const persistThreadMessageMock = vi.fn()
const invalidateThreadBootstrapMock = vi.fn()

vi.mock('@/features/threads/threads-api', () => ({
  fetchBootstrap: (...args: unknown[]) => fetchBootstrapMock(...args),
  persistThreadHead: (...args: unknown[]) => persistThreadHeadMock(...args),
  persistThreadMessage: (...args: unknown[]) => persistThreadMessageMock(...args),
  invalidateThreadBootstrap: (...args: unknown[]) =>
    invalidateThreadBootstrapMock(...args),
}))

import {
  buildHistoryAdapter,
  persistThreadHeadWithRetry,
  waitForThreadHistoryWrites,
} from '@/features/threads/assistant-thread-adapter'

afterEach(() => {
  vi.clearAllMocks()
})

describe('assistant-ui history adapter', () => {
  it('notifies title enrichment only after an accepted user message write', async () => {
    const onUserMessagePersisted = vi.fn()
    persistThreadMessageMock.mockResolvedValue({ id: 'user-1' })
    invalidateThreadBootstrapMock.mockResolvedValue(undefined)
    const adapter = buildHistoryAdapter(
      'thread-1',
      {
        schemaVersion: 1,
        thread: {} as never,
        messageRepository: { headId: null, messages: [] },
        messages: [],
        agentState: null,
        latestRun: null,
      },
      { onUserMessagePersisted },
    )
    const message = {
      id: 'user-1',
      role: 'user',
      content: [{ type: 'text', text: 'Explain the project' }],
    }

    await adapter.append({ message, parentId: null } as never)

    expect(persistThreadMessageMock).toHaveBeenCalledBefore(
      invalidateThreadBootstrapMock,
    )
    expect(onUserMessagePersisted).toHaveBeenCalledWith(message)
  })

  it('does not invoke title enrichment for assistant messages', async () => {
    const onUserMessagePersisted = vi.fn()
    persistThreadMessageMock.mockResolvedValue({ id: 'assistant-1' })
    invalidateThreadBootstrapMock.mockResolvedValue(undefined)
    const adapter = buildHistoryAdapter(
      'thread-1',
      {
        schemaVersion: 1,
        thread: {} as never,
        messageRepository: { headId: null, messages: [] },
        messages: [],
        agentState: null,
        latestRun: null,
      },
      { onUserMessagePersisted },
    )

    await adapter.append({
      parentId: 'user-1',
      message: {
        id: 'assistant-1',
        role: 'assistant',
        content: [{ type: 'text', text: 'The answer' }],
      },
    } as never)

    expect(onUserMessagePersisted).not.toHaveBeenCalled()
  })

  it('restores legacy flat messages as one linear sequence', async () => {
    const bootstrap = {
      schemaVersion: 1 as const,
      thread: {} as never,
      messages: [
        { id: 'user-1', role: 'user', content: 'First question' },
        { id: 'assistant-1', role: 'assistant', content: 'First answer' },
        { id: 'user-2', role: 'user', content: 'Second question' },
      ],
      agentState: null,
      latestRun: null,
    }

    const repository = await buildHistoryAdapter('thread-1', bootstrap).load()

    expect(repository.headId).toBe('user-2')
    expect(repository.messages.map(({ message }) => message.id)).toEqual([
      'user-1',
      'assistant-1',
      'user-2',
    ])
    expect(repository.messages.map(({ parentId }) => parentId)).toEqual([
      null,
      'user-1',
      'assistant-1',
    ])
    expect(repository.messages.map(({ message }) => message.role)).toEqual([
      'user',
      'assistant',
      'user',
    ])
  })

  it('consumes a failed write barrier so a later send is not permanently blocked', async () => {
    persistThreadMessageMock.mockRejectedValueOnce(new Error('offline'))
    const adapter = buildHistoryAdapter('thread-1', {
      schemaVersion: 1,
      thread: {} as never,
      messageRepository: { headId: null, messages: [] },
      messages: [],
      agentState: null,
      latestRun: null,
    })

    await expect(
      adapter.append({
        parentId: null,
        message: {
          id: 'user-1',
          role: 'user',
          content: 'hello',
        },
      } as never),
    ).rejects.toThrow('offline')
    await expect(waitForThreadHistoryWrites('thread-1')).rejects.toThrow(
      'offline',
    )
    await expect(waitForThreadHistoryWrites('thread-1')).resolves.toBeUndefined()
  })

  it('keeps reasoning hidden when decoding ag-ui/v1 messages', async () => {
    const repository = await buildHistoryAdapter('thread-1', {
      schemaVersion: 1,
      thread: {} as never,
      messageRepository: {
        headId: 'assistant-1',
        messages: [
          {
            id: 'assistant-1',
            parentId: null,
            format: 'ag-ui/v1',
            content: {
              id: 'assistant-1',
              role: 'assistant',
              content: [
                { type: 'reasoning', text: 'private thought' },
                { type: 'text', text: 'Public answer' },
              ],
            },
          },
        ],
      },
      messages: [],
      agentState: null,
      latestRun: null,
    }).load()
    const content = repository.messages[0]?.message.content

    expect(content).toEqual([{ type: 'text', text: 'Public answer' }])
    expect(content).not.toContainEqual(
      expect.objectContaining({ type: 'reasoning' }),
    )
  })

  it('strips reasoning parts when decoding exact aui/v0 messages', async () => {
    const bootstrap = {
      schemaVersion: 1 as const,
      thread: {} as never,
      messageRepository: {
        headId: 'assistant-1',
        messages: [
          {
            id: 'assistant-1',
            parentId: null,
            format: 'aui/v0' as const,
            content: {
              id: 'assistant-1',
              role: 'assistant',
              content: [
                { type: 'reasoning', text: 'private thought' },
                { type: 'text', text: 'Public answer' },
              ],
            },
          },
        ],
      },
      messages: [],
      agentState: null,
      latestRun: null,
    }

    const repository = await buildHistoryAdapter('thread-1', bootstrap).load()
    const [message] = repository.messages
    const content = message?.message.content

    expect(Array.isArray(content)).toBe(true)
    expect(content).toEqual([{ type: 'text', text: 'Public answer' }])
    expect(content).not.toContainEqual(
      expect.objectContaining({ type: 'reasoning' }),
    )
  })

  it('abandons an older head retry when a newer branch head is selected', async () => {
    const controllerA = new AbortController()
    let generation = 1
    persistThreadHeadMock.mockRejectedValue(new Error('transient 409'))

    const retryA = persistThreadHeadWithRetry('thread-1', 'head-a', {
      signal: controllerA.signal,
      isCurrent: () => generation === 1,
      retryDelayMs: 100,
      maxRetries: 3,
    })

    await vi.waitFor(() => {
      expect(persistThreadHeadMock).toHaveBeenCalledTimes(1)
    })
    generation = 2
    controllerA.abort()

    await expect(retryA).resolves.toBe(false)
    expect(persistThreadHeadMock).toHaveBeenCalledTimes(1)

    persistThreadHeadMock.mockResolvedValue({ headId: 'head-b' })
    const controllerB = new AbortController()
    await expect(
      persistThreadHeadWithRetry('thread-1', 'head-b', {
        signal: controllerB.signal,
        isCurrent: () => generation === 2,
        retryDelayMs: 0,
        maxRetries: 1,
      }),
    ).resolves.toBe(true)
    expect(persistThreadHeadMock).toHaveBeenCalledTimes(2)
    expect(persistThreadHeadMock.mock.calls[1]?.[2]).toEqual({
      signal: controllerB.signal,
    })
  })
})
