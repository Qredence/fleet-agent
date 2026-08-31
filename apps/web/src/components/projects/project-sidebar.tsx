import {
  Check,
  ChevronsUpDown,
  CircleUser,
  Laptop,
  Moon,
  MoreVertical,
  Pencil,
  Plug,
  Plus,
  Search,
  Settings,
  SlidersHorizontal,
  Sparkles,
  Sun,
  Trash,
  Wrench,
} from 'lucide-react'
import { useState, type FormEvent } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useNavigate, useParams, useLocation } from 'react-router-dom'

import { Button } from '@/components/ui/button'
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
  SidebarHeader,
  SidebarInput,
  SidebarContent,
  SidebarFooter,
  SidebarGroup,
  SidebarGroupLabel,
  SidebarGroupActions,
  SidebarGroupAction,
  SidebarMenu,
  SidebarMenuItem,
  SidebarMenuButton,
  SidebarMenuAction,
  SidebarMenuBadge,
  SidebarMenuSkeleton,
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
} from '@/features/threads/threads-api'
import { useWorkspaceStore } from '@/state/workspace-store'
import { SettingsDialog } from '@/components/settings/settings-dialog'
import { useShape } from '@/lib/shape-context'
import { cn } from '@/lib/utils'

const THREAD_PREVIEW_COUNT = 5

// Project-level controls keep their space in the header so revealing them
// never moves the project label. Pointer hover and focus-within both expose
// the controls; the touch variant keeps the same actions reachable without a
// hover device.
const PROJECT_ACTION_REVEAL =
  'pointer-events-none opacity-0 transition-opacity duration-80 group-hover/group-header:pointer-events-auto group-hover/group-header:opacity-100 group-focus-within/group-header:pointer-events-auto group-focus-within/group-header:opacity-100 has-[[data-state=open]]:pointer-events-auto has-[[data-state=open]]:opacity-100 has-[[data-popup-open]]:pointer-events-auto has-[[data-popup-open]]:opacity-100 pointer-coarse:pointer-events-auto pointer-coarse:opacity-100'

/**
 * Renders the application sidebar with workspace controls, project search, navigation links, project groups, and footer actions.
 */
export function ProjectSidebar() {
  const projects = useProjects()
  const [createOpen, setCreateOpen] = useState(false)
  const [settingsOpen, setSettingsOpen] = useState(false)
  const [searchFilter, setSearchFilter] = useState('')
  const { projectId } = useParams<{ projectId?: string }>()
  const navigate = useNavigate()
  const location = useLocation()
  // Element-step radius for the bare icon chips this sidebar renders by hand
  // (the SidebarMenu components pull their own shape classes).
  const shape = useShape()

  const allProjects = projects.data ?? []
  const filteredProjects = searchFilter
    ? allProjects.filter((p) =>
        p.name.toLowerCase().includes(searchFilter.toLowerCase()),
      )
    : allProjects

  return (
    <SidebarProvider
      className="h-full min-h-0 w-full min-w-0"
      width="100%"
      widthMobile="18rem"
    >
      <Sidebar
        variant="floating"
        collapsible="none"
        className="h-full w-full min-w-0"
      >
        {/* Workspace Switcher & Search */}
        <SidebarHeader>
          <div className="flex items-center justify-between px-1 py-0.5">
            <DropdownMenu>
              <DropdownMenuTrigger
                render={
                  <Button
                    variant="ghost"
                    size="sm"
                    className="h-8 w-full min-w-0 gap-2 px-2 text-start text-sm font-semibold [&>span.relative]:w-full [&>span.relative]:min-w-0 [&>span.relative>span]:flex [&>span.relative>span]:min-w-0 [&>span.relative>span]:flex-1 [&>span.relative>span]:items-center"
                  />
                }
              >
                <span className="min-w-0 flex-1 truncate text-start">Fleet Agent</span>
                <ChevronsUpDown className="ms-auto size-3.5 shrink-0 text-muted-foreground" />
              </DropdownMenuTrigger>
              <DropdownMenuContent align="start" className="w-48">
                <DropdownMenuItem onClick={() => setCreateOpen(true)}>
                  <Plus className="size-3.5" />
                  New workspace
                </DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>
          </div>

          <div className="relative">
            <Search className="size-3.5 absolute start-2.5 top-1/2 -translate-y-1/2 text-muted-foreground pointer-events-none" />
            <SidebarInput
              placeholder="Search…"
              value={searchFilter}
              onChange={(e) => setSearchFilter(e.target.value)}
              className="ps-8"
            />
          </div>

          <SidebarMenu>
            <NewThreadMenuItem />

            <SidebarMenuItem>
              <SidebarMenuButton
                icon={Sparkles}
                isActive={location.pathname.includes('/optimizer')}
                onClick={() => projectId && navigate(`/projects/${projectId}/optimizer`)}
                disabled={!projectId}
              >
                <span>Optimizer</span>
              </SidebarMenuButton>
            </SidebarMenuItem>

            <SidebarMenuItem>
              <SidebarMenuButton
                icon={Wrench}
                isActive={location.pathname.includes('/tools')}
                onClick={() => projectId && navigate(`/projects/${projectId}/tools`)}
                disabled={!projectId}
              >
                <span>Tools</span>
              </SidebarMenuButton>
            </SidebarMenuItem>

            <SidebarMenuItem>
              <SidebarMenuButton
                icon={Plug}
                isActive={location.pathname.includes('/connectors')}
                onClick={() => projectId && navigate(`/projects/${projectId}/connectors`)}
                disabled={!projectId}
              >
                <span>Connectors</span>
              </SidebarMenuButton>
            </SidebarMenuItem>
          </SidebarMenu>
        </SidebarHeader>

        {/* Dynamic Project Groups */}
        <SidebarContent>
          <div className="flex items-center justify-between px-3 pt-2 pb-1 text-[11px] font-medium tracking-wider uppercase text-muted-foreground/80">
            <span>Projects</span>
            <button
              type="button"
              aria-label="New project"
              onClick={() => setCreateOpen(true)}
              className={cn('p-1 hover:bg-sidebar-accent text-muted-foreground hover:text-foreground transition-colors', shape.bg)}
            >
              <Plus className="size-3.5" />
            </button>
          </div>

          {projects.data ? (
            filteredProjects.length ? (
              filteredProjects.map((project) => (
                <ProjectSection
                  key={project.id}
                  project={project}
                  defaultOpen={project.id === projectId}
                />
              ))
            ) : (
              <SidebarGroup className="h-full items-center justify-center gap-2 text-center text-sm text-muted-foreground p-6">
                <p className="text-xs">No projects found</p>
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => setCreateOpen(true)}
                  className="h-7 text-xs gap-1"
                >
                  <Plus className="size-3.5" />
                  New project
                </Button>
              </SidebarGroup>
            )
          ) : (
            <SidebarGroup>
              <SidebarGroupLabel>Projects</SidebarGroupLabel>
              <SidebarMenu>
                {Array.from({ length: 3 }, (_, i) => (
                  <SidebarMenuItem key={i}>
                    <SidebarMenuSkeleton showIcon />
                  </SidebarMenuItem>
                ))}
              </SidebarMenu>
            </SidebarGroup>
          )}
        </SidebarContent>

        {/* Footer Actions & Settings */}
        <SidebarFooter>
          <SidebarMenu>
            <SidebarMenuItem>
              <SidebarMenuButton
                icon={Settings}
                onClick={() => setSettingsOpen(true)}
              >
                Settings
              </SidebarMenuButton>
            </SidebarMenuItem>
            <SidebarMenuItem>
              <ThemeDropdownMenu />
            </SidebarMenuItem>
          </SidebarMenu>

          <SidebarSeparator />

          <div className="flex items-center justify-between px-2 py-1.5 text-xs text-muted-foreground">
            <div className="flex items-center gap-2">
              <CircleUser className="size-4" />
              <span className="font-semibold text-foreground">Qredence</span>
            </div>
            <span className="text-[10px] bg-muted px-1.5 py-0.5 rounded font-mono">
              v0.1.0
            </span>
          </div>
        </SidebarFooter>
      </Sidebar>

      <CreateProjectDialog open={createOpen} onOpenChange={setCreateOpen} />
      <SettingsDialog open={settingsOpen} onOpenChange={setSettingsOpen} />
    </SidebarProvider>
  )
}

/**
 * Provides a menu for selecting the workspace theme.
 */
function ThemeDropdownMenu() {
  const theme = useWorkspaceStore((s) => s.theme)
  const setTheme = useWorkspaceStore((s) => s.setTheme)

  const Icon = theme === 'light' ? Sun : theme === 'dark' ? Moon : Laptop

  return (
    <DropdownMenu>
      <DropdownMenuTrigger
        render={
          <SidebarMenuButton icon={Icon}>
            <span>Theme</span>
          </SidebarMenuButton>
        }
      />
      <DropdownMenuContent align="start" side="top" className="w-36 text-xs p-1">
        <DropdownMenuItem
          onClick={() => setTheme('light')}
          className="flex items-center justify-between cursor-pointer"
        >
          <div className="flex items-center gap-2">
            <Sun className="size-3.5" />
            <span>Light</span>
          </div>
          {theme === 'light' && <Check className="size-3.5 text-foreground" />}
        </DropdownMenuItem>
        <DropdownMenuItem
          onClick={() => setTheme('dark')}
          className="flex items-center justify-between cursor-pointer"
        >
          <div className="flex items-center gap-2">
            <Moon className="size-3.5" />
            <span>Dark</span>
          </div>
          {theme === 'dark' && <Check className="size-3.5 text-foreground" />}
        </DropdownMenuItem>
        <DropdownMenuItem
          onClick={() => setTheme('system')}
          className="flex items-center justify-between cursor-pointer"
        >
          <div className="flex items-center gap-2">
            <Laptop className="size-3.5" />
            <span>System</span>
          </div>
          {theme === 'system' && <Check className="size-3.5 text-foreground" />}
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  )
}

/**
 * Provides a menu item for creating a thread in the active project and navigating to it.
 */
function NewThreadMenuItem() {
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
    <SidebarMenuItem>
      <SidebarMenuButton
        icon={Plus}
        onClick={() => projectId && createMutation.mutate(projectId)}
        disabled={disabled}
        aria-label="New thread"
        className="justify-between"
      >
        <span>New</span>
        <kbd className="pointer-events-none ms-auto text-[10px] text-muted-foreground font-mono bg-muted/60 px-1 py-0.5 rounded">
          ⇧⌘O
        </kbd>
      </SidebarMenuButton>
    </SidebarMenuItem>
  )
}

/**
 * Displays a project section with its threads and project actions.
 *
 * @param project - The project whose threads and actions are displayed
 * @param defaultOpen - Whether the section is initially expanded
 */
function ProjectSection({
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
  const [open, setOpen] = useState(defaultOpen)
  const [showAll, setShowAll] = useState(false)
  const [renameOpen, setRenameOpen] = useState(false)
  const [deleteOpen, setDeleteOpen] = useState(false)

  const isProjectActive = projectId === activeProjectId

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
    <SidebarGroup collapsible open={open} onOpenChange={setOpen}>
      <div className="group/group-header relative w-full min-w-0">
        <div className="flex w-full min-w-0 items-center justify-between">
          {/* Two header actions occupy a 24px box each plus their gap. Keep
              this reservation local to the project row so the title never
              shifts when the quiet controls fade in. */}
          <SidebarGroupLabel
            role="button"
            tabIndex={0}
            aria-label={`Project: ${name}`}
            aria-expanded={open}
            onClick={() => setOpen(!open)}
            onKeyDown={(event) => {
              if (event.key !== 'Enter' && event.key !== ' ') return
              event.preventDefault()
              setOpen(!open)
            }}
            className="min-w-0 flex-1 cursor-pointer select-none truncate pe-[62px]"
          >
            <span>{name}</span>
          </SidebarGroupLabel>

          {threads.data && (
            <SidebarMenuBadge className="me-1 text-[10px]">
              {all.length}
            </SidebarMenuBadge>
          )}
        </div>

        <SidebarGroupActions
          className={`${PROJECT_ACTION_REVEAL} end-1.5 top-0`}
        >
          <SidebarGroupAction
            aria-label={`New thread in: ${name}`}
            onClick={() => newThreadMutation.mutate()}
          >
            <Plus className="size-3.5" />
          </SidebarGroupAction>

          <ProjectDropdownAction
            name={name}
            onRename={() => setRenameOpen(true)}
            onDelete={() => setDeleteOpen(true)}
          />
        </SidebarGroupActions>
      </div>

      {open && (
        <SidebarMenu className="w-full min-w-0">
          {all.length ? (
            visible.map((thread) => {
              const isActive = thread.id === activeThreadId && isProjectActive
              return (
                <SidebarMenuItem key={thread.id}>
                  <SidebarMenuButton
                    status={isActive ? 'active' : 'idle'}
                    isActive={isActive}
                    aria-current={isActive ? 'page' : undefined}
                    onClick={() => navigate(`/projects/${projectId}/threads/${thread.id}`)}
                    className="w-full min-w-0"
                  >
                    <span className="truncate">{thread.title}</span>
                  </SidebarMenuButton>

                  <DropdownMenu>
                    <DropdownMenuTrigger
                      render={
                        <SidebarMenuAction
                          showOnHover
                          aria-label={`Thread actions: ${thread.title}`}
                        >
                          <MoreVertical className="size-3.5" />
                        </SidebarMenuAction>
                      }
                    />
                    <DropdownMenuContent align="end" className="w-36">
                      <DropdownMenuItem onClick={() => deleteThreadMutation.mutate(thread.id)}>
                        <Trash className="size-3.5" />
                        Delete
                      </DropdownMenuItem>
                    </DropdownMenuContent>
                  </DropdownMenu>
                </SidebarMenuItem>
              )
            })
          ) : (
            <p className="px-2 py-1 text-xs text-muted-foreground italic">No chats</p>
          )}

          {hasHidden && (
            <SidebarMenuItem>
              <SidebarMenuButton
                size="sm"
                className="text-xs text-muted-foreground hover:text-foreground"
                onClick={() => setShowAll((cur) => !cur)}
              >
                <span>{showAll ? 'Show less' : 'Show more'}</span>
              </SidebarMenuButton>
            </SidebarMenuItem>
          )}
        </SidebarMenu>
      )}

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
        isActive={isProjectActive}
      />
    </SidebarGroup>
  )
}

/**
 * Renders a project actions menu with options to rename or delete the project.
 *
 * @param name - The project name used to label the actions control
 * @param onRename - Callback invoked when Rename is selected
 * @param onDelete - Callback invoked when Delete is selected
 */
function ProjectDropdownAction({
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
          <SidebarGroupAction
            aria-label={`Project actions: ${name}`}
            className="hover:bg-sidebar-accent"
          >
            <SlidersHorizontal className="size-3.5" />
          </SidebarGroupAction>
        }
      />
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

/**
 * Renders a dialog for creating a project and navigates to the new project after creation.
 *
 * @param open - Whether the dialog is open
 * @param onOpenChange - Called when the dialog's open state changes
 */
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

/**
 * Provides a dialog for creating or renaming a project.
 *
 * @param initialName - The project name displayed when the dialog opens
 * @param onSubmit - Handles submission of the trimmed project name
 * @param onSuccess - Handles the result after a successful submission
 */
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
