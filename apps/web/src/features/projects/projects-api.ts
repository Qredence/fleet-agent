import { apiFetch } from '@/lib/api-client'

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
  return apiFetch<ProjectOut>('/api/projects', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ name }),
  })
}

export function renameProject(projectId: string, name: string): Promise<ProjectOut> {
  return apiFetch<ProjectOut>(`/api/projects/${projectId}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ name }),
  })
}

export async function deleteProject(projectId: string): Promise<void> {
  await apiFetch<void>(`/api/projects/${projectId}`, { method: 'DELETE' })
}
