import {
  ChevronsUpDown,
  CircleUser,
  Folder,
  FolderOpen,
  MoreHorizontal,
  Pencil,
  Plus,
  Trash,
} from 'lucide-react'
import { useState, type FormEvent } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useNavigate, useParams } from 'react-router-dom'

import { Button } from '@/components/ui/button'
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '@/components/ui/collapsible'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import {
  Sidebar,
  SidebarContent,
  SidebarFooter,
  SidebarGroup,
  SidebarGroupAction,
  SidebarGroupContent,
  SidebarGroupLabel,
  SidebarHeader,
  SidebarMenu,
  SidebarMenuAction,
  SidebarMenuBadge,
  SidebarMenuButton,
  SidebarMenuItem,
  SidebarMenuSkeleton,
  SidebarMenuSub,
  SidebarMenuSubButton,
  SidebarMenuSubItem,
  SidebarProvider,
  SidebarSeparator,
} from '@/components/ui/sidebar'
import { Input } from '@/components/ui/input'
import {
  createProject,
  deleteProject,
  renameProject,
  type ProjectOut,
} from '@/features/projects/projects-api'
import { useProjects } from '@/features/projects/use-projects'
import { useThreads } from '@/features/threads/use-threads'
import {
  createThread,
  deleteThread,
  type ThreadOut,
} from '@/features/threads/threads-api'

/** Threads shown per project group before a "Show more" expander appears. */
const THREAD_PREVIEW_COUNT = 5

/**
 * Left sidebar, built on the vendored shadcn/Base-UI sidebar kit
 * (`components/ui/sidebar.tsx`). Structure: header > New thread > one
 * collapsible SidebarMenuItem per project (badge = thread count, hover
 * actions: new-thread + rename/delete) > threads as MenuSub > footer menu.
 * Open/close of the whole panel stays with the workspace shell (zustand +
 * resizable panes) — the kit Provider here is local and never persists.
 */
export function ProjectSidebar() {
  const projects = useProjects()
  const [createOpen, setCreateOpen] = useState(false)

  return (
    // The shell owns panel visibility; this provider only feeds the kit's
    // internal `useSidebar` consumers (never persists, no ⌘B).
    <SidebarProvider
      className="h-full min-h-0"
      enableKeyboardShortcut={false}
      persistState={false}
    >
      <Sidebar
        collapsible="none"
        className="w-full"
        role="complementary"
        aria-label="Projects and threads"
      >
        <SidebarHeader className="gap-0 p-0">
          <div className="flex h-12 items-center px-3">
            <span className="text-sm font-semibold">Fleet Agent</span>
          </div>
          <SidebarSeparator />
          <div className="p-2">
            <NewThreadButton />
          </div>
          <SidebarSeparator />
        </SidebarHeader>

        <SidebarContent>
          {projects.data ? (
            projects.data.length ? (
              <SidebarGroup>
                <SidebarGroupLabel>
                  <span>Projects</span>
                </SidebarGroupLabel>
                <SidebarGroupAction
                  aria-label="New project"
                  onClick={() => setCreateOpen(true)}
                >
                  <Plus />
                </SidebarGroupAction>
                <SidebarGroupContent>
                  <ProjectsMenu projects={projects.data} />
                </SidebarGroupContent>
              </SidebarGroup>
            ) : (
              <SidebarGroup className="h-full items-center justify-center gap-2 text-center text-sm text-muted-foreground">
                <FolderOpen className="size-5" />
                <p>No projects yet</p>
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => setCreateOpen(true)}
                >
                  <Plus className="size-4" />
                  New project
                </Button>
              </SidebarGroup>
            )
          ) : (
            <SidebarGroup>
              <SidebarGroupLabel>Projects</SidebarGroupLabel>
              <SidebarGroupContent>
                <SidebarMenu>
                  {Array.from({ length: 3 }, (_, i) => (
                    <SidebarMenuItem key={i}>
                      <SidebarMenuSkeleton showIcon />
                    </SidebarMenuItem>
                  ))}
                </SidebarMenu>
              </SidebarGroupContent>
            </SidebarGroup>
          )}
        </SidebarContent>

        <SidebarFooter className="gap-0 p-0">
          <SidebarSeparator />
          <div className="p-2">
            <UserMenu />
          </div>
        </SidebarFooter>
      </Sidebar>

      <CreateProjectDialog open={createOpen} onOpenChange={setCreateOpen} />
    </SidebarProvider>
  )
}

function NewThreadButton() {
  const { projectId } = useParams<{ projectId?: string }>()
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const createMutation = useMutation({
    mutationFn: (activeProjectId: string) => createThread(activeProjectId),
    onSuccess: async (thread, activeProjectId) => {
      await queryClient.invalidateQueries({
        queryKey: ['projects', activeProjectId, 'threads'],
      })
      navigate(`/projects/${activeProjectId}/threads/${thread.id}`)
    },
  })

  const disabled = !projectId || createMutation.isPending
  return (
    <SidebarMenuButton
      variant="outline"
      onClick={() => projectId && createMutation.mutate(projectId)}
      disabled={disabled}
      title={projectId ? 'Start a new thread' : 'Select a project first'}
      className="justify-start"
    >
      <Plus />
      <span>New thread</span>
    </SidebarMenuButton>
  )
}

function ProjectsMenu({ projects }: { projects: ProjectOut[] }) {
  const { projectId: activeProjectId } = useParams()
  return (
    <SidebarMenu>
      {projects.map((project) => (
        <ProjectGroup
          key={project.id}
          project={project}
          defaultOpen={project.id === activeProjectId}
        />
      ))}
    </SidebarMenu>
  )
}

function ProjectGroup({
  project,
  defaultOpen,
}: {
  project: ProjectOut
  defaultOpen: boolean
}) {
  const { id: projectId, name } = project
  const threads = useThreads(projectId)
  const { projectId: activeProjectId, threadId: activeThreadId } = useParams()
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const [showAll, setShowAll] = useState(false)
  // Codex-style: the group containing the active thread starts expanded.
  const [open, setOpen] = useState(defaultOpen)
  const [renameOpen, setRenameOpen] = useState(false)
  const [deleteOpen, setDeleteOpen] = useState(false)

  const newThreadMutation = useMutation({
    mutationFn: () => createThread(projectId),
    onSuccess: async (thread) => {
      setOpen(true)
      await queryClient.invalidateQueries({
        queryKey: ['projects', projectId, 'threads'],
      })
      navigate(`/projects/${projectId}/threads/${thread.id}`)
    },
  })

  const deleteThreadMutation = useMutation({
    mutationFn: deleteThread,
    onSuccess: async (_void, deletedThreadId) => {
      await queryClient.invalidateQueries({
        queryKey: ['projects', projectId, 'threads'],
      })
      queryClient.removeQueries({ queryKey: ['thread-bootstrap', deletedThreadId] })
      if (deletedThreadId === activeThreadId) {
        navigate(`/projects/${projectId}`)
      }
    },
  })

  const all = threads.data ?? []
  const visible = showAll ? all : all.slice(0, THREAD_PREVIEW_COUNT)
  const hasHidden = all.length > THREAD_PREVIEW_COUNT

  return (
    <SidebarMenuItem>
      <Collapsible open={open} onOpenChange={setOpen}>
        <CollapsibleTrigger
          render={
            <SidebarMenuButton
              size="sm"
              className="font-semibold text-muted-foreground group-has-data-[sidebar=menu-action]/menu-item:pr-[3.25rem]"
              aria-label={`Project: ${name}`}
            />
          }
        >
          {open ? <FolderOpen /> : <Folder />}
          <span>{name}</span>
        </CollapsibleTrigger>
        {threads.data && (
          <SidebarMenuBadge className="transition-opacity group-hover/menu-item:opacity-0 group-focus-within/menu-item:opacity-0">
            {all.length}
          </SidebarMenuBadge>
        )}
        <SidebarMenuAction
          showOnHover
          aria-label={`New thread in: ${name}`}
          onClick={() => newThreadMutation.mutate()}
          className="right-6"
        >
          <Plus />
        </SidebarMenuAction>
        <ProjectActionsMenu
          name={name}
          onRename={() => setRenameOpen(true)}
          onDelete={() => setDeleteOpen(true)}
        />
        <CollapsibleContent>
          {all.length ? (
            <SidebarMenuSub className="mx-0 translate-x-0 border-l-0 px-0 py-0.5">
              {visible.map((thread) => (
                <ThreadSubItem
                  key={thread.id}
                  thread={thread}
                  isActive={thread.id === activeThreadId && projectId === activeProjectId}
                  onOpen={() => navigate(`/projects/${projectId}/threads/${thread.id}`)}
                  onDelete={() => deleteThreadMutation.mutate(thread.id)}
                />
              ))}
              {hasHidden && (
                <SidebarMenuSubItem>
                  <SidebarMenuSubButton
                    className="w-full translate-x-0 pl-8 text-muted-foreground"
                    onClick={() => setShowAll((current) => !current)}
                    render={<button type="button" />}
                  >
                    <span className="text-xs">
                      {showAll ? 'Show less' : 'Show more'}
                    </span>
                  </SidebarMenuSubButton>
                </SidebarMenuSubItem>
              )}
            </SidebarMenuSub>
          ) : (
            <p className="pl-4 pt-1 text-xs text-muted-foreground">No threads</p>
          )}
        </CollapsibleContent>
      </Collapsible>

      <ProjectNameDialog
        open={renameOpen}
        onOpenChange={setRenameOpen}
        title="Rename project"
        initialName={name}
        confirmLabel="Rename"
        onSubmit={(newName) => renameProject(projectId, newName)}
        onSuccess={async () => {
          await queryClient.invalidateQueries({ queryKey: ['projects'] })
        }}
      />
      <DeleteProjectDialog
        open={deleteOpen}
        onOpenChange={setDeleteOpen}
        project={project}
        isActive={projectId === activeProjectId}
      />
    </SidebarMenuItem>
  )
}

function ProjectActionsMenu({
  name,
  onRename,
  onDelete,
}: {
  name: string
  onRename: () => void
  onDelete: () => void
}) {
  return (
    <DropdownMenu>
      <DropdownMenuTrigger
        render={
          <SidebarMenuAction
            showOnHover
            aria-label={`Project actions: ${name}`}
            className="aria-expanded:opacity-100"
          />
        }
      >
        <MoreHorizontal />
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-36">
        <DropdownMenuItem onClick={onRename}>
          <Pencil className="size-3.5" />
          Rename
        </DropdownMenuItem>
        <DropdownMenuItem variant="destructive" onClick={onDelete}>
          <Trash className="size-3.5" />
          Delete
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  )
}

function ThreadSubItem({
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
    <SidebarMenuSubItem>
      <SidebarMenuSubButton
        isActive={isActive}
        aria-current={isActive ? 'page' : undefined}
        onClick={onOpen}
        render={<button type="button" />}
        className="w-full translate-x-0 pl-8 pr-6"
      >
        <span>{thread.title}</span>
      </SidebarMenuSubButton>
      <DropdownMenu>
        <DropdownMenuTrigger
          render={
            <button
              type="button"
              className="absolute top-1 right-1 flex aspect-square w-5 items-center justify-center rounded-md p-0 text-sidebar-foreground opacity-0 outline-hidden transition-opacity hover:bg-sidebar-accent hover:text-sidebar-accent-foreground focus-visible:opacity-100 focus-visible:ring-2 group-hover/menu-sub-item:opacity-100 group-focus-within/menu-sub-item:opacity-100 data-popup-open:opacity-100 [&>svg]:size-4"
              aria-label={`Thread actions: ${thread.title}`}
            />
          }
        >
          <MoreHorizontal />
        </DropdownMenuTrigger>
        <DropdownMenuContent align="end" className="w-36">
          <DropdownMenuItem onClick={onDelete}>
            <Trash className="size-3.5" />
            Delete
          </DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>
    </SidebarMenuSubItem>
  )
}

function UserMenu() {
  return (
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
  )
}

function CreateProjectDialog({
  open,
  onOpenChange,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
}) {
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  return (
    <ProjectNameDialog
      open={open}
      onOpenChange={onOpenChange}
      title="New project"
      initialName=""
      confirmLabel="Create"
      onSubmit={(name) => createProject(name)}
      onSuccess={async (project) => {
        await queryClient.invalidateQueries({ queryKey: ['projects'] })
        navigate(`/projects/${project.id}`)
      }}
    />
  )
}

/** Name-input dialog shared by "New project" and "Rename project". */
function ProjectNameDialog<TResult>({
  open,
  onOpenChange,
  title,
  initialName,
  confirmLabel,
  onSubmit,
  onSuccess,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
  title: string
  initialName: string
  confirmLabel: string
  onSubmit: (name: string) => Promise<TResult>
  onSuccess?: (result: TResult) => void | Promise<void>
}) {
  const [name, setName] = useState(initialName)
  const [error, setError] = useState<string | null>(null)
  const [pending, setPending] = useState(false)

  const handleOpenChange = (next: boolean) => {
    if (next) {
      setName(initialName)
      setError(null)
    }
    onOpenChange(next)
  }

  const handleSubmit = async (event: FormEvent) => {
    event.preventDefault()
    const trimmed = name.trim()
    if (!trimmed || trimmed === initialName || pending) return
    setPending(true)
    setError(null)
    try {
      const result = await onSubmit(trimmed)
      await onSuccess?.(result)
      onOpenChange(false)
    } catch {
      setError('Something went wrong. Please try again.')
    } finally {
      setPending(false)
    }
  }

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{title}</DialogTitle>
        </DialogHeader>
        <form onSubmit={handleSubmit} className="flex flex-col gap-4">
          <label className="flex flex-col gap-1.5">
            <span className="sr-only">Project name</span>
            <Input
              autoFocus
              placeholder="Project name"
              value={name}
              onChange={(event) => setName(event.target.value)}
              maxLength={120}
              aria-label="Project name"
            />
          </label>
          {error && <p className="text-sm text-destructive">{error}</p>}
          <DialogFooter>
            <Button
              type="submit"
              disabled={!name.trim() || name.trim() === initialName || pending}
            >
              {pending ? 'Saving…' : confirmLabel}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}

function DeleteProjectDialog({
  open,
  onOpenChange,
  project,
  isActive,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
  project: ProjectOut
  isActive: boolean
}) {
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const mutation = useMutation({
    mutationFn: () => deleteProject(project.id),
    onSuccess: async () => {
      queryClient.removeQueries({ queryKey: ['projects', project.id, 'threads'] })
      await queryClient.invalidateQueries({ queryKey: ['projects'] })
      onOpenChange(false)
      if (isActive) {
        navigate('/')
      }
    },
  })

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Delete project?</DialogTitle>
          <DialogDescription>
            &ldquo;{project.name}&rdquo; and all its threads will be permanently
            deleted. This cannot be undone.
          </DialogDescription>
        </DialogHeader>
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button
            variant="destructive"
            disabled={mutation.isPending}
            onClick={() => mutation.mutate()}
          >
            {mutation.isPending ? 'Deleting…' : 'Delete'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
