import type { ExportedMessageRepositoryItem } from '@assistant-ui/react'

export const DEFAULT_THREAD_TITLE = 'New conversation'
const MAX_THREAD_TITLE_LENGTH = 48

/**
 * Derives a concise thread title from the first visible line of a query.
 *
 * @param query - The query from which to derive the title
 * @returns The normalized and truncated title, or `New conversation` when the query has no visible content
 */
export function deriveThreadTitle(query: string): string {
  const firstVisibleLine = query
    .split(/\r?\n/)
    .map((line) => line.replace(/\s+/g, ' ').trim())
    .find(Boolean)

  if (!firstVisibleLine) return DEFAULT_THREAD_TITLE
  if (firstVisibleLine.length <= MAX_THREAD_TITLE_LENGTH) return firstVisibleLine

  return `${firstVisibleLine.slice(0, MAX_THREAD_TITLE_LENGTH - 1).trimEnd()}…`
}

/**
 * Determines whether a value is a non-null, non-array object.
 *
 * @param value - The value to inspect
 * @returns `true` if the value is a record, `false` otherwise.
 */
function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

/**
 * Extracts visible text from a user message.
 *
 * @returns The message's text parts joined with newline characters, or an empty string when the message is not a user message or has no array content.
 */
export function getUserMessageText(
  message: ExportedMessageRepositoryItem['message'],
): string {
  if (message.role !== 'user' || !Array.isArray(message.content)) return ''

  return message.content
    .filter(isRecord)
    .filter((part) => part.type === 'text' && typeof part.text === 'string')
    .map((part) => part.text as string)
    .join('\n')
}
