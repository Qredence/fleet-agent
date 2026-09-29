import { Pencil, Trash2 } from 'lucide-react'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardAction, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { maskApiKey } from '@/features/providers/openrouter-auth'
import type { ProviderProfile } from '@/features/providers/providers-store'

interface CustomProviderCardProps {
  profile: ProviderProfile
  isActive: boolean
  onEdit: (profile: ProviderProfile) => void
  onDelete: (id: string) => void
}

export function CustomProviderCard({
  profile,
  isActive,
  onEdit,
  onDelete,
}: CustomProviderCardProps) {
  return (
    <Card className="border border-border/60 bg-muted/30">
      <CardHeader className="p-3">
        <div className="flex items-start justify-between gap-2">
          <div className="min-w-0 space-y-0.5">
            <div className="flex items-center gap-2">
              <CardTitle className="text-xs font-semibold">
                {profile.name}
              </CardTitle>
              {isActive && (
                <Badge
                  variant="outline"
                  className="px-2 py-0 text-[10px] border-success/30 bg-success/10 text-success"
                >
                  Active
                </Badge>
              )}
            </div>
            <CardDescription className="font-mono text-[11px] truncate">
              {profile.modelId || 'server default model'}
            </CardDescription>
            <div className="font-mono text-[11px] text-muted-foreground truncate">
              {profile.baseUrl}
            </div>
            <div className="font-mono text-[11px] text-muted-foreground">
              Key: {maskApiKey(profile.apiKey)}
            </div>
          </div>
          <CardAction className="flex shrink-0 gap-1">
            <Button
              variant="ghost"
              size="icon-xs"
              onClick={() => onEdit(profile)}
              aria-label={`Edit ${profile.name}`}
            >
              <Pencil className="size-3" />
            </Button>
            <Button
              variant="ghost"
              size="icon-xs"
              onClick={() => onDelete(profile.id)}
              className="text-destructive hover:bg-destructive/10 hover:text-destructive"
              aria-label={`Delete ${profile.name}`}
            >
              <Trash2 className="size-3" />
            </Button>
          </CardAction>
        </div>
      </CardHeader>
    </Card>
  )
}
