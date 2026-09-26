import { apiFetch, apiJsonFetch } from '@/lib/api-client'

export interface ProjectOut {
  id: string
  name: string
  createdAt: string
  updatedAt: string
}

export function listProjects(): Promise<ProjectOut[]> {
  return apiFetch<ProjectOut[]>('/api/projects')
}

export function createProject(name: string): Promise<ProjectOut> {
  return apiJsonFetch<ProjectOut>('/api/projects', 'POST', { name })
}

export function renameProject(projectId: string, name: string): Promise<ProjectOut> {
  return apiJsonFetch<ProjectOut>(`/api/projects/${projectId}`, 'PATCH', { name })
}

export async function deleteProject(projectId: string): Promise<void> {
  await apiFetch<void>(`/api/projects/${projectId}`, { method: 'DELETE' })
}
