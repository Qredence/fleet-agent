import { ChevronsUpDown, CircleUser, FolderOpen, MoreHorizontal, Plus, Trash } from 'lucide-react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useNavigate, useParams } from 'react-router-dom'

import { Button } from '@/components/ui/button'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { ScrollArea } from '@/components/ui/scroll-area'
import { Separator } from '@/components/ui/separator'
import { useProjects } from '@/features/projects/use-projects'
import { useThreads } from '@/features/threads/use-threads'
import { createThread, deleteThread, type ThreadOut } from '@/features/threads/threads-api'
import { cn } from '@/lib/utils'

/**
 * Left sidebar: workspace header, new thread, project tree, user menu.
 * Data comes from the API (TanStack Query); navigation is via the URL —
 * the URL owns the active project/thread, not local state.
 */
export function ProjectSidebar() {
  const projects = useProjects()

  return (
    <aside
      aria-label="Projects and threads"
      className="flex h-full min-h-0 flex-col bg-background"
    >
      <header className="flex h-12 shrink-0 items-center px-4">
        <span className="text-sm font-semibold">Fleet Agent</span>
      </header>
      <Separator />

      <div className="shrink-0 p-3">
        <NewThreadButton />
      </div>

      <ScrollArea className="min-h-0 flex-1">
        {projects.data?.length ? (
          <nav className="px-3 pb-3">
            <ul className="space-y-4">
              {projects.data.map((project) => (
                <ProjectEntry key={project.id} projectId={project.id} name={project.name} />
              ))}
            </ul>
          </nav>
        ) : (
          <div className="flex h-full flex-col items-center justify-center gap-2 p-6 text-center text-sm text-muted-foreground">
            <FolderOpen className="size-5" />
            <p>No projects yet</p>
          </div>
        )}
      </ScrollArea>

      <Separator />
      <footer className="shrink-0 p-3">
        <DropdownMenu>
          <DropdownMenuTrigger
            render={
              <Button
                variant="ghost"
                className="w-full justify-start gap-2"
                aria-label="User menu"
              />
            }
          >
            <CircleUser className="size-4" />
            <span className="flex-1 truncate text-left">Guest</span>
            <ChevronsUpDown className="size-4 text-muted-foreground" />
          </DropdownMenuTrigger>
          <DropdownMenuContent align="start" side="top" className="w-56">
            <DropdownMenuItem disabled>Settings (coming soon)</DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      </footer>
    </aside>
  )
}

function NewThreadButton() {
  const { projectId } = useParams<{ projectId?: string }>()
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const createMutation = useMutation({
    mutationFn: (activeProjectId: string) => createThread(activeProjectId),
    onSuccess: async (thread, activeProjectId) => {
      await queryClient.invalidateQueries({ queryKey: ['projects', activeProjectId, 'threads'] })
      navigate(`/projects/${activeProjectId}/threads/${thread.id}`)
    },
  })

  const disabled = !projectId || createMutation.isPending
  return (
    <Button
      variant="outline"
      className="w-full justify-start gap-2"
      disabled={disabled}
      title={projectId ? 'Start a new thread' : 'Select a project first'}
      onClick={() => projectId && createMutation.mutate(projectId)}
    >
      <Plus className="size-4" />
      New thread
    </Button>
  )
}

function ProjectEntry({ projectId, name }: { projectId: string; name: string }) {
  const threads = useThreads(projectId)
  const { projectId: activeProjectId, threadId: activeThreadId } = useParams()
  const navigate = useNavigate()
  const queryClient = useQueryClient()

  const deleteMutation = useMutation({
    mutationFn: deleteThread,
    onSuccess: async (_void, deletedThreadId) => {
      await queryClient.invalidateQueries({ queryKey: ['projects', projectId, 'threads'] })
      queryClient.removeQueries({ queryKey: ['thread-bootstrap', deletedThreadId] })
      if (deletedThreadId === activeThreadId) {
        navigate(`/projects/${projectId}`)
      }
    },
  })

  return (
    <li>
      <p className="mb-1 truncate text-xs font-semibold text-muted-foreground">{name}</p>
      {threads.data?.length ? (
        <ul className="space-y-0.5">
          {threads.data.map((thread) => (
            <ThreadEntry
              key={thread.id}
              thread={thread}
              isActive={thread.id === activeThreadId && projectId === activeProjectId}
              onOpen={() =>
                navigate(`/projects/${projectId}/threads/${thread.id}`)
              }
              onDelete={() => deleteMutation.mutate(thread.id)}
            />
          ))}
        </ul>
      ) : (
        <p className="text-xs text-muted-foreground">No threads</p>
      )}
    </li>
  )
}

function ThreadEntry({
  thread,
  isActive,
  onOpen,
  onDelete,
}: {
  thread: ThreadOut
  isActive: boolean
  onOpen: () => void
  onDelete: () => void
}) {
  return (
    <li className="group flex items-center gap-1">
      <Button
        variant="ghost"
        size="sm"
        aria-current={isActive ? 'page' : undefined}
        className={cn(
          'min-w-0 flex-1 justify-start truncate',
          isActive && 'bg-accent font-medium',
        )}
        onClick={onOpen}
      >
        <span className="truncate">{thread.title}</span>
      </Button>
      <DropdownMenu>
        <DropdownMenuTrigger
          render={
            <Button
              variant="ghost"
              size="icon"
              className="size-6 opacity-0 group-hover:opacity-100 focus-visible:opacity-100"
              aria-label={`Thread actions: ${thread.title}`}
            />
          }
        >
          <MoreHorizontal className="size-3.5" />
        </DropdownMenuTrigger>
        <DropdownMenuContent align="end" className="w-36">
          <DropdownMenuItem onClick={onDelete}>
            <Trash className="size-3.5" />
            Delete
          </DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>
    </li>
  )
}
