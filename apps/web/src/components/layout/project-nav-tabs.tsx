import { MessageSquare, Plug, Sparkles, Wrench } from 'lucide-react'
import { NavLink, useParams } from 'react-router-dom'

import { cn } from '@/lib/utils'

interface ProjectNavTabsProps {
  className?: string
}

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

  return (
    <nav
      aria-label="Project sections"
      className={cn('flex items-center gap-1 rounded-lg bg-muted/60 p-1', className)}
    >
      {tabs.map((tab) => (
        <NavLink
          key={tab.label}
          to={tab.path}
          className={({ isActive }) =>
            cn(
              'inline-flex items-center gap-1.5 rounded-md px-2.5 py-1 text-xs font-medium transition-colors',
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
