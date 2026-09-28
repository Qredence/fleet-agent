import type { LucideIcon } from 'lucide-react'

/**
 * Centered, icon-led placeholder for an empty process panel tab.
 *
 * @param icon - The icon representing the tab's content type.
 * @param title - A short statement of what is missing.
 * @param description - One line describing when content will appear.
 */
export function EmptyTabState({
  icon: Icon,
  title,
  description,
}: {
  icon: LucideIcon
  title: string
  description: string
}) {
  return (
    <div className="flex h-full min-h-48 flex-col items-center justify-center gap-2 px-6 text-center">
      <Icon className="size-6 text-muted-foreground" />
      <div className="space-y-1">
        <p className="text-sm font-medium text-foreground">{title}</p>
        <p className="text-xs text-muted-foreground">{description}</p>
      </div>
    </div>
  )
}
