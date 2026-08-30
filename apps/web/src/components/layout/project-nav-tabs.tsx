import { MessageSquare, Plug, Sparkles, Wrench } from 'lucide-react'
import { NavLink, useParams } from 'react-router-dom'

import { useShape } from '@/lib/shape-context'
import { cn } from '@/lib/utils'

interface ProjectNavTabsProps {
  className?: string
}

/**
 * Renders navigation tabs for the sections of the current project.
 *
 * @param className - Additional CSS classes for the navigation container
 */
export function ProjectNavTabs({ className }: ProjectNavTabsProps) {
  const { projectId, threadId } = useParams<{
    projectId?: string
    threadId?: string
  }>()

  if (!projectId) return null

  const workspacePath = threadId
    ? `/projects/${projectId}/threads/${threadId}`
    : `/projects/${projectId}`

  const tabs = [
    {
      label: 'Workspace',
      path: workspacePath,
      icon: MessageSquare,
      isActive: (currentPath: string) =>
        currentPath === `/projects/${projectId}` ||
        currentPath.startsWith(`/projects/${projectId}/threads`),
    },
    {
      label: 'Optimizer',
      path: `/projects/${projectId}/optimizer`,
      icon: Sparkles,
      isActive: (currentPath: string) =>
        currentPath.startsWith(`/projects/${projectId}/optimizer`),
    },
    {
      label: 'Tools',
      path: `/projects/${projectId}/tools`,
      icon: Wrench,
      isActive: (currentPath: string) =>
        currentPath.startsWith(`/projects/${projectId}/tools`),
    },
    {
      label: 'Connectors',
      path: `/projects/${projectId}/connectors`,
      icon: Plug,
      isActive: (currentPath: string) =>
        currentPath.startsWith(`/projects/${projectId}/connectors`),
    },
  ]

  // A segmented control on the shape ladder (Fluid Functionalism): the track
  // takes the `container` step and its items the `item` step, so the nav
  // reads as a sibling of Tabs and every other control in pill mode. With
  // p-1 the two are exactly concentric (20 + 4 = 24).
  const shape = useShape()

  return (
    <nav
      aria-label="Project sections"
      className={cn('flex items-center gap-1 bg-muted/60 p-[3px]', shape.container, className)}
    >
      {tabs.map((tab) => (
        <NavLink
          key={tab.label}
          to={tab.path}
          className={({ isActive }) =>
            cn(
              'inline-flex items-center gap-1.5 px-2.5 py-1 text-xs font-medium transition-colors',
              shape.item,
              tab.isActive(window.location.pathname) || isActive
                ? 'bg-background text-foreground shadow-xs font-semibold'
                : 'text-muted-foreground hover:bg-background/50 hover:text-foreground'
            )
          }
        >
          <tab.icon className="size-3.5" />
          <span>{tab.label}</span>
        </NavLink>
      ))}
    </nav>
  )
}
