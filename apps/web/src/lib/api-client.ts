/**
 * API origin, normalized without a trailing slash because every caller appends
 * a path that already starts with `/`. Operators paste origins with and
 * without the slash — including Amp's own `PUBLIC_URL` — and `//api/projects`
 * is not a path any server or proxy recognizes.
 */
export const API_BASE_URL: string = (
  import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000'
).replace(/\/+$/, '')
export const API_KEY: string | undefined = import.meta.env.VITE_API_KEY || undefined

export class ApiError extends Error {
  readonly status: number

  constructor(status: number, message: string) {
    super(message)
    this.name = 'ApiError'
    this.status = status
  }
}

export async function apiFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    ...init,
    headers: {
      Accept: 'application/json',
      ...(API_KEY ? { 'X-API-Key': API_KEY } : {}),
      ...init?.headers,
    },
  })

  if (!response.ok) {
    throw new ApiError(response.status, `API request failed: ${response.status}`)
  }

  if (response.status === 204 || response.headers.get('content-length') === '0') {
    return undefined as T
  }

  return response.json() as Promise<T>
}

export async function apiFetchText(path: string, init?: RequestInit): Promise<string> {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    ...init,
    headers: {
      Accept: 'text/plain, text/markdown;q=0.9',
      ...(API_KEY ? { 'X-API-Key': API_KEY } : {}),
      ...init?.headers,
    },
  })

  if (!response.ok) {
    throw new ApiError(response.status, `API request failed: ${response.status}`)
  }

  return response.text()
}

/**
 * Convenience wrapper for JSON-body mutations (POST, PUT, PATCH, etc.).
 * Automatically sets `Content-Type: application/json` and serializes the body.
 */
export function apiJsonFetch<T>(
  path: string,
  method: string,
  body: unknown,
  init?: RequestInit,
): Promise<T> {
  const { headers: extraHeaders, ...rest } = init ?? {}
  return apiFetch<T>(path, {
    ...rest,
    method,
    headers: { 'Content-Type': 'application/json', ...extraHeaders },
    body: JSON.stringify(body),
  })
}
