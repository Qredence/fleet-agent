import { FolderPlus } from 'lucide-react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Navigate } from 'react-router-dom'

import { Button } from '@/components/ui/button'
import { createProject } from '@/features/projects/projects-api'
import { useProjects } from '@/features/projects/use-projects'
import { listThreads } from '@/features/threads/threads-api'

/**
 * Index route: land in the newest thread, on the first project, or offer the
 * one-click "create your first thread" flow when nothing exists yet.
 */
export function WorkspaceBootstrapRoute() {
  const projects = useProjects()
  if (projects.isPending) {
    return <BootScreen message="Loading workspace…" />
  }
  if (projects.isError) {
    return <BootScreen message="Could not load projects." error />
  }

  const project = projects.data?.[0]
  if (!project) {
    return <EmptyBootstrap />
  }
  return <ProjectEntry projectId={project.id} />
}

function ProjectEntry({ projectId }: { projectId: string }) {
  const threads = useQueryThreadsForEntry(projectId)
  if (threads.isPending) return <BootScreen message="Loading threads…" />
  const thread = threads.data?.[0]
  if (thread) {
    return <Navigate to={`/projects/${projectId}/threads/${thread.id}`} replace />
  }
  return <Navigate to={`/projects/${projectId}`} replace />
}

function useQueryThreadsForEntry(projectId: string) {
  return useQuery({
    queryKey: ['projects', projectId, 'threads'],
    queryFn: () => listThreads(projectId),
  })
}

function EmptyBootstrap() {
  const queryClient = useQueryClient()
  const createWorkspace = useMutation({
    mutationFn: async () => createProject('Workspace'),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['projects'] }),
  })

  if (createWorkspace.isSuccess) {
    return <Navigate to={`/projects/${createWorkspace.data.id}`} replace />
  }

  return (
    <div className="flex h-dvh flex-col items-center justify-center gap-4 bg-background text-foreground">
      <h1 className="text-lg font-semibold">Fleet Agent</h1>
      <p className="max-w-sm text-center text-sm text-muted-foreground">
        Create your first project to start working with the agent.
      </p>
      <Button
        onClick={() => createWorkspace.mutate()}
        disabled={createWorkspace.isPending}
      >
        <FolderPlus className="size-4" />
        New project
      </Button>
      {createWorkspace.isError && (
        <p className="text-sm text-destructive">Could not create the project.</p>
      )}
    </div>
  )
}

function BootScreen({ message, error = false }: { message: string; error?: boolean }) {
  return (
    <div className="flex h-dvh items-center justify-center bg-background">
      <p className={error ? 'text-sm text-destructive' : 'text-sm text-muted-foreground'}>
        {message}
      </p>
    </div>
  )
}
