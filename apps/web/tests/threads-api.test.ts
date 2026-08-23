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
})
