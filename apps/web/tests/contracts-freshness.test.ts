import { readFile } from 'node:fs/promises'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

import { compileFromFile } from 'json-schema-to-typescript'
import { describe, expect, it } from 'vitest'

const here = dirname(fileURLToPath(import.meta.url))
const schemaPath = resolve(
  here,
  '../../../packages/contracts/agent-workspace-state.schema.json',
)
const generatedPath = resolve(here, '../src/contracts/generated.ts')

describe('generated contracts', () => {
  it('src/contracts/generated.ts matches the schema (run pnpm contracts:sync)', async () => {
    const [expected, actual] = await Promise.all([
      compileFromFile(schemaPath),
      readFile(generatedPath, 'utf-8'),
    ])
    expect(actual.trimEnd()).toBe(expected.trimEnd())
  })
})
