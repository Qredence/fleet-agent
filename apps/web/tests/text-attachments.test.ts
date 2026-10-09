import { expect, it } from 'vitest'
import { attachmentAdapter } from '@/features/agent-runtime/agent-runtime-provider'
it('keeps text files and rejects images from every attachment entry path', async () => {
  expect(attachmentAdapter.accept).not.toContain('image/')
  const text = new File(['Known evidence'], 'notes.txt', { type: 'text/plain' })
  const pending = await attachmentAdapter.add({ file: text })
  if (!('id' in pending)) throw new Error('Expected a pending text attachment')
  const completed = await attachmentAdapter.send(pending)
  expect(completed.type).toBe('document')
  expect(completed.content).toEqual([{ type: 'text', text: '<attachment name=notes.txt>\nKnown evidence\n</attachment>' }])
  // Picker, clipboard paste, and drop all enter the same runtime adapter.
  for (const name of ['picked.png', 'pasted.png', 'dropped.png']) {
    expect(() => attachmentAdapter.add({ file: new File(['image'], name, { type: 'image/png' }) })).toThrow(/matching adapter/)
  }
})
