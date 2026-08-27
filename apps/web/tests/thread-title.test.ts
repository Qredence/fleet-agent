import { describe, expect, it } from 'vitest'

import {
  DEFAULT_THREAD_TITLE,
  deriveThreadTitle,
  getUserMessageText,
} from '@/features/threads/thread-title'

describe('thread title derivation', () => {
  it('falls back for empty or whitespace-only queries', () => {
    expect(deriveThreadTitle('')).toBe(DEFAULT_THREAD_TITLE)
    expect(deriveThreadTitle('  \n\t  ')).toBe(DEFAULT_THREAD_TITLE)
  })

  it('collapses whitespace and uses the first visible line', () => {
    expect(
      deriveThreadTitle('  Explain   the   surface system  \nA second line'),
    ).toBe('Explain the surface system')
  })

  it('truncates long titles to 48 characters including the ellipsis', () => {
    const title = deriveThreadTitle(
      'Explain how the nested workspace substrates should behave on mobile',
    )

    expect(title).toHaveLength(48)
    expect(title.endsWith('…')).toBe(true)
  })
})

describe('visible user message text', () => {
  it('extracts text parts while ignoring non-visible attachments', () => {
    expect(
      getUserMessageText({
        id: 'user-1',
        role: 'user',
        content: [
          { type: 'text', text: 'First line' },
          { type: 'image', image: 'data:image/png;base64,ignored' },
          { type: 'text', text: 'Second line' },
          { type: 'file', filename: 'notes.txt' },
        ],
      } as never),
    ).toBe('First line\nSecond line')
  })
})
