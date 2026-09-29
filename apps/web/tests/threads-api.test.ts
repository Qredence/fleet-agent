import { describe, expect, it } from 'vitest'

import {
  UnsupportedThreadBootstrapSchemaError,
  validateThreadBootstrap,
} from '@/features/threads/threads-api'

describe('thread bootstrap contract validation', () => {
  it('rejects an unknown bootstrap schema version', () => {
    expect(() =>
      validateThreadBootstrap({ schemaVersion: 99 }),
    ).toThrow(UnsupportedThreadBootstrapSchemaError)
  })

  it('accepts the v1 legacy flat-message compatibility shape', () => {
    expect(
      validateThreadBootstrap({
        schemaVersion: 1,
        thread: {},
        messages: [],
        agentState: null,
        latestRun: null,
      }).schemaVersion,
    ).toBe(1)
  })

  it('accepts both known message formats', () => {
    const bootstrap = validateThreadBootstrap({
      schemaVersion: 1,
      thread: {},
      messages: [],
      messageRepository: {
        headId: 'm2',
        messages: [
          { id: 'm1', parentId: null, format: 'ag-ui/v1', content: {} },
          { id: 'm2', parentId: 'm1', format: 'aui/v0', content: {} },
        ],
      },
      agentState: null,
      latestRun: null,
    })
    expect(
      bootstrap.messageRepository?.messages.map((entry) => entry.format),
    ).toEqual(['ag-ui/v1', 'aui/v0'])
  })

  // The schema types `format` as a plain string (the server passes persisted
  // values through), so this validator is the gate that keeps an unknown
  // format from reaching decodeEntry.
  it('rejects an unknown message format', () => {
    expect(() =>
      validateThreadBootstrap({
        schemaVersion: 1,
        thread: {},
        messages: [],
        messageRepository: {
          headId: null,
          messages: [
            { id: 'm1', parentId: null, format: 'legacy/v9', content: {} },
          ],
        },
        agentState: null,
        latestRun: null,
      }),
    ).toThrow('Unsupported thread message format.')
  })
})
