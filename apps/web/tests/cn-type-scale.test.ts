import { readFile } from 'node:fs/promises'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

import { describe, expect, it } from 'vitest'

import { cn, typeScale } from '@/lib/utils'

const here = dirname(fileURLToPath(import.meta.url))
const indexCss = resolve(here, '../src/index.css')

// Tailwind defines these itself; every other `--text-*` token is ours.
const TAILWIND_TEXT_TOKENS = new Set(['xs', 'sm', 'base', 'lg', 'xl', '2xl', '3xl'])

/** Split a class string into tokens without assuming single spaces. */
const tokens = (value: string) => value.split(/\s+/).filter(Boolean)

/**
 * Build an arbitrary size from parts. This file is linted by the same
 * no-arbitrary-text-size rule the app uses, so the legacy strings under test
 * are assembled rather than written out as literals.
 */
const arb = (value: string) => `text-${'['}${value}]`

describe('cn and the named type scale', () => {
  // The app composes size and color through cn() constantly. Tailwind-merge
  // resolves `text-<word>` as a color unless the word is a known font size, so
  // an unregistered token silently loses its size. These pin the registration
  // in src/lib/utils.ts: dropping a name there must fail here, loudly.
  it('keeps a size and a color when the color comes second', () => {
    expect(tokens(cn('text-body', 'text-muted-foreground'))).toEqual(
      expect.arrayContaining(['text-body', 'text-muted-foreground']),
    )
  })

  it('keeps a size and a color when the color comes second (meta)', () => {
    expect(tokens(cn('text-meta', 'text-foreground'))).toEqual(
      expect.arrayContaining(['text-meta', 'text-foreground']),
    )
  })

  it('does not drop the size when a color is appended to a class string', () => {
    // The exact regression: without registration this returned only the color.
    const merged = cn('text-meta text-muted-foreground', 'text-body')

    expect(tokens(merged)).toContain('text-body')
    expect(tokens(merged)).toContain('text-muted-foreground')
    expect(tokens(merged)).not.toContain('text-meta')
  })

  it('keeps size and color independent on every token', () => {
    for (const name of typeScale) {
      const merged = tokens(cn(`text-${name}`, 'text-destructive'))

      expect(merged, `text-${name}`).toContain(`text-${name}`)
      expect(merged, `text-${name}`).toContain('text-destructive')
    }
  })

  it('resolves conflicting sizes with the later one winning', () => {
    expect(tokens(cn('text-body', 'text-meta'))).toEqual(['text-meta'])
    expect(tokens(cn('text-meta', 'text-body'))).toEqual(['text-body'])
  })

  it('still merges an arbitrary value as before', () => {
    // The pre-migration path keeps working: an arbitrary size replaces the
    // previous size, and a size never swallows a color.
    expect(tokens(cn(arb('13px'), arb('11px')))).toEqual([arb('11px')])
    expect(tokens(cn(arb('13px'), 'text-muted-foreground'))).toEqual(
      expect.arrayContaining([arb('13px'), 'text-muted-foreground']),
    )
    expect(tokens(cn('text-body', arb('11px')))).toEqual([arb('11px')])
  })
})

describe('type scale tokens', () => {
  it('lists exactly the --text-* tokens declared in index.css', async () => {
    const css = await readFile(indexCss, 'utf-8')
    const declared = [...css.matchAll(/--text-([\w-]+)\s*:/g)]
      .map((match) => match[1])
      .filter((name) => !TAILWIND_TEXT_TOKENS.has(name))

    // Both directions: a token added to CSS but not to typeScale would be
    // dropped by cn(), and a name only in typeScale is dead weight.
    expect(new Set(declared)).toEqual(new Set(typeScale))
  })

  it('declares each token once so a duplicate cannot shadow another', async () => {
    const css = await readFile(indexCss, 'utf-8')
    const declared = [...css.matchAll(/--text-([\w-]+)\s*:/g)]
      .map((match) => match[1])
      .filter((name) => !TAILWIND_TEXT_TOKENS.has(name))

    expect(declared.length).toBe(new Set(declared).size)
  })
})
