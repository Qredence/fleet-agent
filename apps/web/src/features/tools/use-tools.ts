import { useQuery } from '@tanstack/react-query'

import { fetchTools } from '@/features/tools/tools-api'

/**
 * Fetches and provides the tools query state and data.
 */
export function useTools() {
  return useQuery({
    queryKey: ['tools'],
    queryFn: fetchTools,
  })
}
