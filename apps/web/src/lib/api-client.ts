/** HTTP client for the Fleet API. Origin and key come from `lib/env`. */

import { API_BASE_URL, API_KEY } from "@/lib/env";

export class ApiError extends Error {
  readonly status: number;

  constructor(status: number, message: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

function buildApiHeaders(
  defaults: Record<string, string>,
  extraHeaders?: HeadersInit,
): Record<string, string> {
  const result: Record<string, string> = {};
  const keysByLower = new Map<string, string>();
  const setHeader = (key: string, value: string) => {
    const lower = key.toLowerCase();
    const prevKey = keysByLower.get(lower);
    if (prevKey && prevKey !== key) {
      delete result[prevKey];
    }
    keysByLower.set(lower, key);
    result[key] = value;
  };

  for (const [key, value] of Object.entries(defaults)) {
    setHeader(key, value);
  }
  if (API_KEY) {
    setHeader("X-API-Key", API_KEY);
  }
  if (extraHeaders) {
    const normalized = new Headers(extraHeaders);
    if (!(extraHeaders instanceof Headers) && !Array.isArray(extraHeaders)) {
      for (const key of Object.keys(extraHeaders)) {
        const value = normalized.get(key);
        if (value !== null) {
          setHeader(key, value);
        }
      }
    } else {
      normalized.forEach((value, key) => {
        setHeader(key, value);
      });
    }
  }
  return result;
}

export async function apiFetch<T>(
  path: string,
  init?: RequestInit,
): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    ...init,
    headers: buildApiHeaders({ Accept: "application/json" }, init?.headers),
  });

  if (!response.ok) {
    throw new ApiError(
      response.status,
      `API request failed: ${response.status}`,
    );
  }

  if (
    response.status === 204 ||
    response.headers.get("content-length") === "0"
  ) {
    return undefined as T;
  }

  return response.json() as Promise<T>;
}

export async function apiFetchText(
  path: string,
  init?: RequestInit,
): Promise<string> {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    ...init,
    headers: buildApiHeaders(
      { Accept: "text/plain, text/markdown;q=0.9" },
      init?.headers,
    ),
  });

  if (!response.ok) {
    throw new ApiError(
      response.status,
      `API request failed: ${response.status}`,
    );
  }

  return response.text();
}

/** Binary resources use the same authentication boundary as REST and previews. */
export async function apiFetchBlob(path: string): Promise<Blob> {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    headers: buildApiHeaders({}),
  });
  if (!response.ok) {
    throw new ApiError(
      response.status,
      `API request failed: ${response.status}`,
    );
  }
  return response.blob();
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
  const { headers: extraHeaders, ...rest } = init ?? {};
  return apiFetch<T>(path, {
    ...rest,
    method,
    headers: buildApiHeaders(
      { Accept: "application/json", "Content-Type": "application/json" },
      extraHeaders,
    ),
    body: JSON.stringify(body),
  });
}
