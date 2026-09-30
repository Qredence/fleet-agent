import { readFile } from 'node:fs/promises'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

import { compileFromFile } from 'json-schema-to-typescript'
import { describe, expect, it } from 'vitest'

const here = dirname(fileURLToPath(import.meta.url))
const contractsDir = resolve(here, '../../../packages/contracts')

const cases = [
  {
    schema: `${contractsDir}/agent-capabilities.schema.json`,
    generated: resolve(here, '../src/contracts/agent-capabilities.ts'),
  },
  {
    schema: `${contractsDir}/agent-workspace-state.schema.json`,
    generated: resolve(here, '../src/contracts/generated.ts'),
  },
  {
    schema: `${contractsDir}/thread-bootstrap.schema.json`,
    generated: resolve(here, '../src/contracts/thread-bootstrap.ts'),
  },
] as const

describe('generated contracts', () => {
  it.each(cases)(
    '$generated matches the schema (run pnpm contracts:sync)',
    async ({ schema, generated }) => {
      const [expected, actual] = await Promise.all([
        compileFromFile(schema),
        readFile(generated, 'utf-8'),
      ])
      expect(actual.trimEnd()).toBe(expected.trimEnd())
    },
  )
})
