import { useQuery } from '@tanstack/react-query'

import { listThreads } from '@/features/threads/threads-api'

export function useThreads(projectId: string | undefined) {
  return useQuery({
    queryKey: ['projects', projectId, 'threads'],
    queryFn: () => listThreads(projectId!),
    enabled: Boolean(projectId),
  })
}
