import type { ReactNode } from 'react'
import type { LucideIcon } from 'lucide-react'

interface WorkspacePageProps {
  title: string
  description: string
  icon: LucideIcon
  notice?: string
  action?: ReactNode
  children: ReactNode
}

export function WorkspacePage({
  title,
  description,
  icon: Icon,
  notice,
  action,
  children,
}: WorkspacePageProps) {
  return (
    <div className="flex h-full min-w-0 flex-col overflow-y-auto bg-background">
      <div className="w-full min-w-0 space-y-6 p-4 sm:p-6">
        <header className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
          <div className="flex min-w-0 items-start gap-3">
            <div className="flex size-9 shrink-0 items-center justify-center rounded-lg bg-primary/10 text-primary">
              <Icon className="size-5" aria-hidden="true" />
            </div>
            <div className="min-w-0">
              <h2 className="text-lg font-semibold text-foreground">{title}</h2>
              <p className="text-sm text-muted-foreground">{description}</p>
              {notice && <p className="mt-1 text-xs text-muted-foreground">{notice}</p>}
            </div>
          </div>
          {action && <div className="shrink-0 sm:ms-4">{action}</div>}
        </header>
        {children}
      </div>
    </div>
  )
}
