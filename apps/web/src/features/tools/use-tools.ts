import { useQuery } from '@tanstack/react-query'

import { fetchTools } from '@/features/tools/tools-api'

export function useTools() {
  return useQuery({
    queryKey: ['tools'],
    queryFn: fetchTools,
  })
}
