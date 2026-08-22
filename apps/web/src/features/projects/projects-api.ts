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
