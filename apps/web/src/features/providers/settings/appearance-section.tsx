import { Laptop, Moon, Palette, Sun } from 'lucide-react'
import { Card, CardHeader, CardMedia, CardTitle, CardGroup } from '@/components/ui/card'
import { useWorkspaceStore } from '@/state/workspace-store'

export function AppearanceSection() {
  const theme = useWorkspaceStore((s) => s.theme)
  const setTheme = useWorkspaceStore((s) => s.setTheme)

  return (
    <div className="space-y-4">
      <section className="space-y-3.5">
        <div className="flex items-start justify-between gap-4 pb-2.5 border-b border-border/40">
          <div className="space-y-1 min-w-0">
            <div className="flex items-center gap-2">
              <Palette className="size-4 text-muted-foreground shrink-0" />
              <h3 className="text-sm font-semibold text-foreground tracking-tight">
                Interface Theme
              </h3>
            </div>
            <p className="text-xs text-muted-foreground leading-normal">
              Select your preferred color theme for Fleet Agent.
            </p>
          </div>
        </div>
        <CardGroup columns={3} separated border="outlined" className="pt-1">
          <Card
            onClick={() => setTheme('light')}
            selected={theme === 'light'}
            label="Light"
            className="cursor-pointer"
          >
            <CardHeader className="p-3 flex flex-col items-center justify-center text-center gap-1.5">
              <CardMedia icon={Sun} className="mb-0" />
              <CardTitle className="text-xs font-medium">Light</CardTitle>
            </CardHeader>
          </Card>
          <Card
            onClick={() => setTheme('dark')}
            selected={theme === 'dark'}
            label="Dark"
            className="cursor-pointer"
          >
            <CardHeader className="p-3 flex flex-col items-center justify-center text-center gap-1.5">
              <CardMedia icon={Moon} className="mb-0" />
              <CardTitle className="text-xs font-medium">Dark</CardTitle>
            </CardHeader>
          </Card>
          <Card
            onClick={() => setTheme('system')}
            selected={theme === 'system'}
            label="System"
            className="cursor-pointer"
          >
            <CardHeader className="p-3 flex flex-col items-center justify-center text-center gap-1.5">
              <CardMedia icon={Laptop} className="mb-0" />
              <CardTitle className="text-xs font-medium">System</CardTitle>
            </CardHeader>
          </Card>
        </CardGroup>
      </section>
    </div>
  )
}
