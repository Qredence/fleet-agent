import { describe, expect, it } from 'vitest'
import { attachmentAdapter } from '@/features/agent-runtime/agent-runtime-provider'
import { supportsTextFile } from '@/features/agent-runtime/text-attachments'

describe('text-attachments', () => {
  it('keeps text files and rejects images from every attachment entry path', async () => {
    expect(attachmentAdapter.accept).not.toContain('image/')
    const text = new File(['Known evidence'], 'notes.txt', { type: 'text/plain' })
    const pending = await attachmentAdapter.add({ file: text })
    if (!('id' in pending)) throw new Error('Expected a pending text attachment')
    const completed = await attachmentAdapter.send(pending)
    expect(completed.type).toBe('document')
    expect(completed.content).toEqual([
      {
        type: 'text',
        text: '<attachment name="notes.txt">\nKnown evidence\n</attachment>',
      },
    ])
    // Picker, clipboard paste, and drop all enter the same runtime adapter.
    for (const name of ['picked.png', 'pasted.png', 'dropped.png']) {
      expect(() =>
        attachmentAdapter.add({
          file: new File(['image'], name, { type: 'image/png' }),
        }),
      ).toThrow(/matching adapter/)
    }
  })

  it('strips MIME parameters and falls back to explicit text extensions when type is empty', async () => {
    const parameterized = new File(['hello'], 'notes.txt', {
      type: 'text/plain; charset=utf-8',
    })
    expect(supportsTextFile(parameterized)).toBe(true)
    await expect(attachmentAdapter.add({ file: parameterized })).resolves.toMatchObject(
      { name: 'notes.txt', type: 'document' },
    )

    const emptyTypeMarkdown = new File(['# Heading'], 'README.md', { type: '' })
    expect(supportsTextFile(emptyTypeMarkdown)).toBe(true)
    await expect(
      attachmentAdapter.add({ file: emptyTypeMarkdown }),
    ).resolves.toMatchObject({ name: 'README.md', type: 'document' })

    const unknownEmpty = new File(['binary'], 'archive.bin', { type: '' })
    expect(supportsTextFile(unknownEmpty)).toBe(false)
    expect(() => attachmentAdapter.add({ file: unknownEmpty })).toThrow(
      /matching adapter/,
    )

    // Non-empty non-text MIME must still be rejected even with a .txt extension.
    const spoofed = new File(['img'], 'photo.txt', { type: 'image/png' })
    expect(supportsTextFile(spoofed)).toBe(false)
    expect(() => attachmentAdapter.add({ file: spoofed })).toThrow(
      /matching adapter/,
    )
  })
})
