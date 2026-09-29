import { describe, expect, it } from 'vitest'

import providerJson from '@fleet-agent/contracts/provider.json'
import terminationReasons from '@fleet-agent/contracts/termination-reasons.json'

import { TERMINATION_LABELS } from '@/features/process-panel/run-metrics'
import type {
  MessagesFormat,
  ResponseFormat,
} from '@/features/providers/providers-store'

/**
 * Static TypeScript unions cannot be derived from JSON at compile time, so
 * these tests pin the hand-written unions and label maps to the canonical
 * contract files in packages/contracts.
 */
describe('contract constants', () => {
  it('provider format unions match provider.json', () => {
    // The JSON import widens to string[], so the known literals are pinned
    // here; a value added to provider.json without updating this test fails.
    const responseFormats: ResponseFormat[] = [
      'native_function_calling',
      'json_tool_calls',
    ]
    const messagesFormats: MessagesFormat[] = ['system_role', 'developer_role']
    expect([...providerJson.responseFormats].sort()).toEqual(
      [...responseFormats].sort(),
    )
    expect([...providerJson.messagesFormats].sort()).toEqual(
      [...messagesFormats].sort(),
    )
  })

  it('termination label keys match termination-reasons.json', () => {
    expect(Object.keys(TERMINATION_LABELS).sort()).toEqual(
      [...terminationReasons].sort(),
    )
  })
})
