import { useParams } from 'react-router-dom'
import {
  Wrench,
  Check,
  FileCode,
  Search,
  Globe,
  Clock,
  AlertTriangle,
} from 'lucide-react'

import { AgentWorkspace } from '@/components/workspace/agent-workspace'
import { useThreads } from '@/features/threads/use-threads'
import {
  type ToolCatalogEntry,
} from '@/features/tools/tools-api'
import { useTools } from '@/features/tools/use-tools'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'

const TOOL_META: Record<string, { icon: typeof Search; type: string }> = {
  search_docs: { icon: Search, type: 'Built-in Knowledge' },
  write_report: { icon: FileCode, type: 'Artifact Generation' },
  web_search: { icon: Globe, type: 'Web Discovery' },
  fetch_page: { icon: Globe, type: 'Web Discovery' },
  get_current_time: { icon: Clock, type: 'Utility' },
}

function toolMeta(name: string) {
  return TOOL_META[name] ?? { icon: Wrench, type: 'Registered Tool' }
}

function ToolCard({ tool }: { tool: ToolCatalogEntry }) {
  const { icon: Icon, type } = toolMeta(tool.name)
  return (
    <div className="rounded-xl border bg-card p-5 space-y-3 hover:border-primary/50 transition-colors">
      <div className="flex items-start justify-between gap-2">
        <div className="flex items-center gap-2.5">
          <div className="flex size-8 items-center justify-center rounded-lg bg-muted text-foreground">
            <Icon className="size-4" />
          </div>
          <div>
            <h2 className="text-sm font-semibold font-mono">{tool.name}</h2>
            <span className="text-xs text-muted-foreground">{type}</span>
          </div>
        </div>
        <Badge variant="outline" className="text-xs text-emerald-400 border-emerald-500/30 bg-emerald-500/10 gap-1">
          <Check className="size-3" /> Active
        </Badge>
      </div>

      <p className="text-xs text-muted-foreground leading-relaxed">
        {tool.description}
      </p>

      <div className="flex flex-wrap gap-1.5 pt-1">
        {tool.read_only && (
          <Badge variant="secondary" className="text-[10px] font-normal">
            Read-Only
          </Badge>
        )}
        {tool.parallelizable && (
          <Badge variant="secondary" className="text-[10px] font-normal">
            Parallelizable
          </Badge>
        )}
        {tool.idempotent && (
          <Badge variant="secondary" className="text-[10px] font-normal">
            Idempotent
          </Badge>
        )}
        <Badge variant="outline" className="text-[10px] font-mono text-muted-foreground">
          ⏱ {tool.timeout_seconds}s
        </Badge>
      </div>
    </div>
  )
}

export function ToolsRoute() {
  const { projectId } = useParams<{ projectId: string }>()
  const threads = useThreads(projectId)
  const thread = threads.data?.[0]
  const tools = useTools()

  return (
    <AgentWorkspace
      projectId={projectId}
      threadId={thread?.id}
      threadTitle="DSPy Tools Catalog"
      customMain={
        <main
          aria-label="Tools Catalog"
          className="flex h-full min-w-0 flex-1 flex-col bg-background"
        >
          <div className="flex-1 overflow-y-auto p-6 space-y-6">
            <div className="border-b pb-4">
              <h1 className="text-xl font-semibold flex items-center gap-2">
                <Wrench className="size-5 text-sky-400" />
                DSPy Tools Catalog
              </h1>
              <p className="text-sm text-muted-foreground mt-1">
                Inspect registered tools, parameter schemas, and execution policies available to the DSPy engine.
              </p>
            </div>

            {tools.isPending && (
              <p className="text-sm text-muted-foreground" role="status">
                Loading tools…
              </p>
            )}
            {tools.isError && (
              <div
                role="alert"
                className="rounded-xl border border-destructive/40 bg-destructive/5 p-4 space-y-2"
              >
                <p className="text-sm text-destructive flex items-center gap-2">
                  <AlertTriangle className="size-4" aria-hidden />
                  Could not load the tool registry.
                </p>
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => tools.refetch()}
                >
                  Retry
                </Button>
              </div>
            )}
            {tools.data && tools.data.length === 0 && (
              <p className="text-sm text-muted-foreground" role="status">
                No tools are registered with the DSPy engine.
              </p>
            )}
            {tools.data && tools.data.length > 0 && (
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                {tools.data.map((tool) => (
                  <ToolCard key={tool.name} tool={tool} />
                ))}
              </div>
            )}
          </div>
        </main>
      }
    />
  )
}
