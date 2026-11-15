const MIME_TOKEN_RE = /^[a-z0-9][a-z0-9.!#$&^_-]*\/[a-z0-9][a-z0-9.!#$&^_-]*$/i
const SAFE_BASE64_RE = /^[A-Za-z0-9+/=\s]+$/
const ARTIFACT_DOWNLOAD_PATH_RE = /^\/api\/artifacts\/[A-Za-z0-9_-]+$/

function hasControlChar(value: string): boolean {
  for (let i = 0; i < value.length; i += 1) {
    const code = value.charCodeAt(i)
    if (code <= 0x1f || code === 0x7f) return true
  }
  return false
}

/**
 * Safe raster image MIME types for `data:` URIs.
 * Explicitly excludes `image/svg+xml` and HTML/XML formats that can execute scripts.
 */
export const SAFE_IMAGE_MIME_TYPES: ReadonlySet<string> = new Set([
  'image/png',
  'image/jpeg',
  'image/jpg',
  'image/gif',
  'image/webp',
  'image/avif',
  'image/bmp',
  'image/x-icon',
  'image/vnd.microsoft.icon',
])

/**
 * Safe MIME types allowed for downloadable `data:` / `base64` file payloads.
 * Explicitly excludes active document types (`text/html`, `image/svg+xml`, XHTML, JS, XML).
 */
export const SAFE_DOWNLOAD_MIME_TYPES: ReadonlySet<string> = new Set([
  ...SAFE_IMAGE_MIME_TYPES,
  'text/plain',
  'text/csv',
  'text/tab-separated-values',
  'text/markdown',
  'application/pdf',
  'application/json',
  'application/zip',
  'application/gzip',
  'application/octet-stream',
  'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
  'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
  'application/vnd.openxmlformats-officedocument.presentationml.presentation',
  'audio/mpeg',
  'audio/ogg',
  'audio/wav',
  'audio/webm',
  'video/mp4',
  'video/webm',
])

function trimSafeString(raw: string | undefined | null): string | null {
  if (typeof raw !== 'string') return null
  const trimmed = raw.trim()
  if (!trimmed || hasControlChar(trimmed)) return null
  return trimmed
}

function isSafeRootRelativePath(trimmed: string): boolean {
  if (!trimmed.startsWith('/')) return false
  if (trimmed.startsWith('//') || trimmed.startsWith('/\\') || trimmed.includes('\\')) {
    return false
  }
  try {
    const parsed = new URL(trimmed, 'https://relative.invalid')
    return parsed.origin === 'https://relative.invalid'
  } catch {
    return false
  }
}

export function sanitizeMimeType(
  rawMime: string | undefined | null,
  allowedMimes: ReadonlySet<string> = SAFE_DOWNLOAD_MIME_TYPES,
): string | null {
  const trimmed = trimSafeString(rawMime)
  if (!trimmed) return null
  const baseMime = trimmed.split(';', 1)[0]?.trim().toLowerCase() ?? ''
  if (!MIME_TOKEN_RE.test(baseMime)) return null
  return allowedMimes.has(baseMime) ? baseMime : null
}

/**
 * Validates and normalizes `http:` / `https:` URLs without embedded credentials.
 * When `resolveRelative` is true, relative URLs are resolved against the current origin.
 */
export function sanitizeHttpUrl(
  rawUrl: string | undefined | null,
  options?: { resolveRelative?: boolean },
): string | null {
  const trimmed = trimSafeString(rawUrl)
  if (!trimmed) return null
  try {
    const base =
      options?.resolveRelative && typeof window !== 'undefined'
        ? window.location.origin
        : options?.resolveRelative
          ? 'https://localhost'
          : undefined
    const parsed = base ? new URL(trimmed, base) : new URL(trimmed)
    if (
      (parsed.protocol !== 'http:' && parsed.protocol !== 'https:') ||
      parsed.username ||
      parsed.password
    ) {
      return null
    }
    return parsed.href
  } catch {
    return null
  }
}

/**
 * Sanitizes navigation `<a href>` URLs: allows `http:`/`https:` (and optionally single-leading-slash
 * internal paths like `/settings/tools` when `allowRelative` is enabled).
 */
export function sanitizeNavigationUrl(
  rawUrl: string | undefined | null,
  options?: { allowRelative?: boolean },
): string | null {
  const trimmed = trimSafeString(rawUrl)
  if (!trimmed) return null
  if (options?.allowRelative && isSafeRootRelativePath(trimmed)) {
    return trimmed
  }
  return sanitizeHttpUrl(trimmed)
}

/**
 * Validates `data:` URIs against an explicit MIME allowlist (excluding SVG and HTML).
 */
export function sanitizeDataUri(
  rawUri: string | undefined | null,
  allowedMimes: ReadonlySet<string> = SAFE_IMAGE_MIME_TYPES,
): string | null {
  const trimmed = trimSafeString(rawUri)
  if (!trimmed || !/^data:/i.test(trimmed)) return null

  const commaIndex = trimmed.indexOf(',')
  if (commaIndex === -1) return null

  const header = trimmed.slice(5, commaIndex)
  const payload = trimmed.slice(commaIndex + 1)
  if (!header) return null

  const parts = header.split(';')
  const rawMime = parts[0]?.trim()
  const safeMime = sanitizeMimeType(rawMime, allowedMimes)
  if (!safeMime) return null

  const seenBase64 = parts.slice(1).some((part) => part.trim().toLowerCase() === 'base64')
  for (let i = 1; i < parts.length; i++) {
    const param = parts[i]?.trim() ?? ''
    if (!param) return null
    if (param.toLowerCase() === 'base64') {
      if (i !== parts.length - 1) return null
      continue
    }
    if (!/^[a-z0-9._-]+=[a-z0-9._"+-]+$/i.test(param)) {
      return null
    }
  }

  if (seenBase64 && !SAFE_BASE64_RE.test(payload)) {
    return null
  }

  return trimmed
}

/**
 * Builds a safe `data:` download URI from raw base64 data after enforcing `allowedMimes`.
 */
export function buildSafeBase64DataUri(
  base64Data: string,
  rawMimeType: string,
  allowedMimes: ReadonlySet<string> = SAFE_DOWNLOAD_MIME_TYPES,
): string | null {
  const safeMime = sanitizeMimeType(rawMimeType, allowedMimes)
  if (!safeMime) return null
  if (typeof base64Data !== 'string' || !SAFE_BASE64_RE.test(base64Data)) return null
  const compact = base64Data.replace(/\s+/g, '')
  return `data:${safeMime};base64,${compact}`
}

/**
 * Sanitizes `<img>` `src` values and image action sources: allows `http:`, `https:`, `blob:`,
 * root-relative `/...` asset paths, and allowlisted raster `data:` URIs (no SVG or HTML).
 */
export function sanitizeImageSrc(rawSrc: string | undefined | null): string | null {
  const trimmed = trimSafeString(rawSrc)
  if (!trimmed) return null
  if (/^data:/i.test(trimmed)) {
    return sanitizeDataUri(trimmed, SAFE_IMAGE_MIME_TYPES)
  }
  if (/^blob:/i.test(trimmed)) {
    try {
      const parsed = new URL(trimmed)
      return parsed.protocol === 'blob:' ? parsed.href : null
    } catch {
      return null
    }
  }
  if (isSafeRootRelativePath(trimmed)) {
    return trimmed
  }
  return sanitizeHttpUrl(trimmed)
}

/**
 * Sanitizes downloadable `http:`, `https:`, or `blob:` URLs (no credentials, no active schemes).
 */
export function sanitizeDownloadUrl(rawUrl: string | undefined | null): string | null {
  const trimmed = trimSafeString(rawUrl)
  if (!trimmed) return null
  if (/^blob:/i.test(trimmed)) {
    try {
      const parsed = new URL(trimmed)
      return parsed.protocol === 'blob:' ? parsed.href : null
    } catch {
      return null
    }
  }
  return sanitizeHttpUrl(trimmed)
}

/**
 * Strict check for Fleet Agent backend artifact routes (`/api/artifacts/:id`).
 */
export function isSafeArtifactDownloadUrl(url: string | undefined | null): url is string {
  return typeof url === 'string' && ARTIFACT_DOWNLOAD_PATH_RE.test(url)
}
