import { apiFetch } from '@/lib/api-client'

export interface ToolCatalogEntry {
  name: string
  description: string
  capability:
    | 'retrieval'
    | 'utility'
    | 'artifact'
    | 'workspace_read'
    | 'workspace_write'
    | 'shell'
  read_only: boolean
  idempotent: boolean
  parallelizable: boolean
  timeout_seconds: number
  requires_approval: boolean
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
