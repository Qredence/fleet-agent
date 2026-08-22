import { useQuery } from '@tanstack/react-query'

import { listProjects } from '@/features/projects/projects-api'

export function useProjects() {
  return useQuery({ queryKey: ['projects'], queryFn: listProjects })
}
