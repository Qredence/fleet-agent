import { useQuery } from '@tanstack/react-query'
import {
  OPENROUTER_PROFILE_ID,
  OPENROUTER_BASE_URL,
  OPENCODE_ZEN_PROFILE_ID,
  OPENCODE_ZEN_BASE_URL,
} from '@/lib/providers'

export interface ProviderModel {
  id: string
  name: string
  description?: string
  contextLength?: number
}

export interface UseProviderModelsOptions {
  providerId: string
  baseUrl?: string
  apiKey?: string | null
  enabled?: boolean
}

// A 64-bit FNV-1a fingerprint distinguishes credentials in the query cache
// without exposing the raw key in query keys or devtools.
function apiKeyFingerprint(apiKey?: string | null): string | null {
  if (!apiKey) return null
  let hash = 0xcbf29ce484222325n
  for (let i = 0; i < apiKey.length; i++) {
    hash = BigInt.asUintN(64, (hash ^ BigInt(apiKey.charCodeAt(i))) * 0x100000001b3n)
  }
  return hash.toString(16).padStart(16, '0')
}

/**
 * Fetches available models from the active LLM provider.
 * Only models successfully returned by the provider API are returned.
 */
export function useProviderModels({
  providerId,
  baseUrl,
  apiKey,
  enabled = true,
}: UseProviderModelsOptions) {
  return useQuery({
    queryKey: ['provider-models', providerId, baseUrl, apiKeyFingerprint(apiKey)],
    queryFn: async ({ signal }): Promise<ProviderModel[]> => {
      let url = ''
      const headers: Record<string, string> = {
        Accept: 'application/json',
      }

      if (providerId === OPENROUTER_PROFILE_ID) {
        url = `${OPENROUTER_BASE_URL}/models`
        if (apiKey) {
          headers['Authorization'] = `Bearer ${apiKey}`
        }
      } else if (providerId === OPENCODE_ZEN_PROFILE_ID) {
        url = `${OPENCODE_ZEN_BASE_URL}/models`
        if (apiKey) {
          headers['Authorization'] = `Bearer ${apiKey}`
        }
      } else if (baseUrl) {
        url = `${baseUrl.replace(/\/+$/, '')}/models`
        if (apiKey) {
          headers['Authorization'] = `Bearer ${apiKey}`
        }
      } else {
        return []
      }

      const res = await fetch(url, { headers, signal })
      if (!res.ok) {
        throw new Error(`Failed to fetch models from ${providerId}: HTTP ${res.status}`)
      }

      const json = await res.json()
      const rawList = Array.isArray(json)
        ? json
        : Array.isArray(json?.data)
          ? json.data
          : []

      const models: ProviderModel[] = []
      for (const item of rawList) {
        if (!item || typeof item !== 'object') continue
        const id = String(item.id || item.name || '').trim()
        if (!id) continue
        const name = String(item.name || id).trim()
        models.push({
          id,
          name,
          description: typeof item.description === 'string' ? item.description : undefined,
          contextLength: typeof item.context_length === 'number' ? item.context_length : undefined,
        })
      }

      return models
    },
    enabled,
    staleTime: 5 * 60 * 1000,
    retry: 1,
  })
}
