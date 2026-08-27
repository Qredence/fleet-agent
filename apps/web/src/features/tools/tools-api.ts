import { apiFetch } from '@/lib/api-client'

export interface ToolCatalogEntry {
  name: string
  description: string
  read_only: boolean
  idempotent: boolean
  parallelizable: boolean
  timeout_seconds: number
}

export interface ToolCatalogResponse {
  tools: ToolCatalogEntry[]
}

/**
 * Fetches the available tool catalog entries.
 *
 * @returns The tool catalog entries returned by the API.
 */
export function fetchTools(): Promise<ToolCatalogEntry[]> {
  return apiFetch<ToolCatalogResponse>('/api/tools').then(
    (payload) => payload.tools,
  )
}
