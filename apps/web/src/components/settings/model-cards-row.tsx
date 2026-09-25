import { useState, useMemo, type ReactNode } from 'react'
import { useQueryClient, QueryClientProvider } from '@tanstack/react-query'
import {
  Card,
  CardGroup,
  CardHeader,
  CardMedia,
  CardTitle,
  CardDescription,
  CardFooter,
  CardButton,
} from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Cpu } from 'lucide-react'
import { queryClient as fallbackQueryClient } from '@/lib/query-client'
import { useProviderModels } from '@/features/providers/use-provider-models'

function SafeQueryProvider({ children }: { children: ReactNode }) {
  let hasClient = false
  try {
    hasClient = Boolean(useQueryClient())
  } catch {
    hasClient = false
  }
  if (!hasClient) {
    return (
      <QueryClientProvider client={fallbackQueryClient}>
        {children}
      </QueryClientProvider>
    )
  }
  return <>{children}</>
}

interface ModelCardsRowContentProps {
  providerId: string
  baseUrl?: string
  apiKey?: string | null
  selectedModel: string
  onSelectModel: (modelId: string) => void
  disabled?: boolean
}

function ModelCardsRowContent({
  providerId,
  baseUrl,
  apiKey,
  selectedModel,
  onSelectModel,
}: ModelCardsRowContentProps) {
  const [searchQuery, setSearchQuery] = useState('')
  const { data: models, isLoading, isError } = useProviderModels({
    providerId,
    baseUrl,
    apiKey,
    enabled: true,
  })

  const filteredModels = useMemo(() => {
    if (!models || models.length === 0) return []
    if (searchQuery.trim()) {
      const q = searchQuery.toLowerCase()
      return models.filter(
        (m) =>
          m.name.toLowerCase().includes(q) || m.id.toLowerCase().includes(q),
      )
    }
    const limit = 80
    if (models.length <= limit) return models
    const initial = models.slice(0, limit)
    if (selectedModel && !initial.some((m) => m.id === selectedModel)) {
      const found = models.find((m) => m.id === selectedModel)
      if (found) {
        return [found, ...initial.slice(0, limit - 1)]
      }
    }
    return initial
  }, [models, searchQuery, selectedModel])

  if (isLoading) {
    return (
      <div className="space-y-1.5">
        <span className="text-xs font-medium text-muted-foreground">
          Loading models...
        </span>
        <div className="rounded-lg border border-border/60 bg-muted/10 overflow-hidden">
          <CardGroup orientation="inline">
            {[1, 2, 3, 4].map((i) => (
              <Card key={i} className="animate-pulse">
                <CardMedia icon={Cpu} />
                <CardHeader>
                  <div className="h-3.5 w-32 bg-muted/60 rounded" />
                  <div className="h-2.5 w-48 bg-muted/40 rounded" />
                </CardHeader>
                <CardFooter>
                  <div className="h-7 w-16 bg-muted/50 rounded" />
                </CardFooter>
              </Card>
            ))}
          </CardGroup>
        </div>
      </div>
    )
  }

  if (isError) {
    return (
      <div className="rounded-lg border border-border/40 bg-muted/20 p-3 text-xs text-muted-foreground">
        Unable to fetch models from provider. You can specify a custom model identifier below.
      </div>
    )
  }

  if (!models || models.length === 0) {
    return (
      <div className="rounded-lg border border-border/40 bg-muted/20 p-3 text-xs text-muted-foreground">
        No models returned by provider. You can specify a custom model identifier below.
      </div>
    )
  }

  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between gap-2">
        <label
          htmlFor="filter-models-input"
          className="text-xs font-medium text-muted-foreground"
        >
          Available Models ({filteredModels.length}
          {models.length > filteredModels.length ? ` of ${models.length}` : ''}):
        </label>
        {models.length > 5 && (
          <Input
            id="filter-models-input"
            type="search"
            placeholder="Filter models..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            className="h-7 w-44 text-xs"
          />
        )}
      </div>

      <div className="rounded-lg border border-border/60 bg-muted/10 max-h-[290px] overflow-y-auto scrollbar-thin">
        <CardGroup orientation="inline">
          {filteredModels.map((model) => {
            const isSelected = selectedModel === model.id
            return (
              <Card
                key={model.id}
                onClick={() => onSelectModel(model.id)}
                selected={isSelected}
                label={model.name}
              >
                <CardMedia icon={Cpu} />
                <CardHeader>
                  <CardTitle>{model.name}</CardTitle>
                  <CardDescription>{model.id}</CardDescription>
                </CardHeader>
                <CardFooter>
                  <CardButton
                    variant={isSelected ? 'primary' : 'secondary'}
                    onClick={(e: React.MouseEvent) => {
                      e.stopPropagation()
                      onSelectModel(model.id)
                    }}
                  >
                    {isSelected ? 'Connected' : 'Connect'}
                  </CardButton>
                </CardFooter>
              </Card>
            )
          })}
        </CardGroup>
      </div>
    </div>
  )
}

export function ModelCardsRow(props: ModelCardsRowContentProps) {
  return (
    <SafeQueryProvider>
      <ModelCardsRowContent {...props} />
    </SafeQueryProvider>
  )
}
