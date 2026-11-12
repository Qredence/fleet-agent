import { describe, expect, it } from 'vitest'
import { cardData } from '@/features/agent-runtime/card-contract'

describe('shared inline card validation', () => {
  const card = { schemaVersion: 2, kind: 'sources', runId: 'run-a', messageId: 'message-a', data: { sources: [{ sourceId: 'source-a', title: 'Evidence', domain: 'example.com' }] } }
  it('retains stable references in current and bounded legacy cards', () => {
    expect(cardData(card, 'sources')?.sources).toEqual(card.data.sources)
    expect(cardData({ schemaVersion: 1, sources: card.data.sources }, 'sources')?.sources).toEqual(card.data.sources)
  })
  it('rejects unknown versions, kinds, and unbounded data', () => {
    expect(cardData({ ...card, schemaVersion: 99 }, 'sources')).toBeNull()
    expect(cardData({ ...card, kind: 'execute-react' }, 'execute-react')).toBeNull()
    expect(cardData({ ...card, data: { sources: Array(20).fill(card.data.sources[0]) } }, 'sources')).toBeNull()
  })
})
