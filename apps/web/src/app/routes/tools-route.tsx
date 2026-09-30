import { useState } from 'react'
import { useParams } from 'react-router-dom'
import {
  Wrench,
  FileCode,
  Search,
  Globe,
  Clock,
  AlertTriangle,
  FolderSearch,
  Terminal,
} from 'lucide-react'

import { AgentWorkspace } from '@/components/workspace/agent-workspace'
import { WorkspacePage } from '@/components/workspace/workspace-page'
import { useThreads } from '@/features/threads/use-threads'
import {
  type ToolCatalogEntry,
} from '@/features/tools/tools-api'
import { useTools } from '@/features/tools/use-tools'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import {
  Card,
  CardAction,
  CardContent,
  CardDescription,
  CardFooter,
  CardGroup,
  CardHeader,
  CardMedia,
  CardTitle,
} from '@/components/ui/card'
import { Switch } from '@/components/ui/switch'

const TOOL_META: Record<string, { icon: typeof Search; type: string }> = {
  search_docs: { icon: Search, type: 'Built-in Knowledge' },
  write_report: { icon: FileCode, type: 'Artifact Generation' },
  web_search: { icon: Globe, type: 'Web Discovery' },
  fetch_page: { icon: Globe, type: 'Web Discovery' },
  get_current_time: { icon: Clock, type: 'Utility' },
  ls: { icon: FolderSearch, type: 'Workspace inspection' },
  find: { icon: FolderSearch, type: 'Workspace inspection' },
  grep: { icon: Search, type: 'Workspace inspection' },
  read: { icon: FileCode, type: 'Workspace inspection' },
  write: { icon: FileCode, type: 'Workspace mutation' },
  edit: { icon: FileCode, type: 'Workspace mutation' },
  bash: { icon: Terminal, type: 'Workspace command' },
}

/**
 * Retrieves display metadata for a tool name.
 *
 * @param name - The tool name used to look up its metadata
 * @returns The tool's icon and category, or generic registered-tool metadata when no match exists
 */
function toolMeta(name: string) {
  return TOOL_META[name] ?? { icon: Wrench, type: 'Registered Tool' }
}

/**
 * Renders a catalog card with a tool's metadata, description, status, capabilities, and timeout.
 *
 * @param tool - The tool entry to display.
 * @param index - Position inside the CardGroup, injected by the group so the
 *   proximity highlight and divider geometry line up.
 */
function ToolCard({ tool, index }: { tool: ToolCatalogEntry; index?: number }) {
  const { icon: Icon, type } = toolMeta(tool.name)
  const capabilityLabel = tool.capability === 'shell'
    ? 'Shell'
    : tool.read_only
      ? 'Read-only'
      : 'Mutation'
  return (
    <Card index={index}>
      <CardHeader>
        <CardMedia icon={Icon} />
        <h3><CardTitle className="font-mono">{tool.name}</CardTitle></h3>
        <CardDescription className="text-xs">{type}</CardDescription>
        <CardAction>
          <Badge variant="outline" className="text-xs">
            {capabilityLabel}
          </Badge>
        </CardAction>
      </CardHeader>

      <CardContent>
        <p className="text-xs text-muted-foreground leading-relaxed">
          {tool.description}
        </p>
      </CardContent>

      <CardFooter className="flex-wrap gap-1.5">
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
        {tool.requires_approval && (
          <Badge variant="outline" className="text-[10px] text-warning">
            Approval required
          </Badge>
        )}
        {tool.timeout_seconds !== undefined && <Badge variant="outline" className="text-[10px] font-mono text-muted-foreground">
          <Clock className="size-3" aria-hidden="true" /> {tool.timeout_seconds}s
        </Badge>}
      </CardFooter>
    </Card>
  )
}

/**
 * Renders the DSPy Tools Catalog for the current project.
 */
export function ToolsRoute() {
  const { projectId } = useParams<{ projectId: string }>()
  const threads = useThreads(projectId)
  const thread = threads.data?.[0]
  const tools = useTools()
  const [readOnlyOnly, setReadOnlyOnly] = useState(false)

  const visibleTools =
    readOnlyOnly && tools.data
      ? tools.data.filter((tool) => tool.read_only)
      : tools.data

  return (
    <AgentWorkspace
      projectId={projectId}
      threadId={thread?.id}
      threadTitle="DSPy Tools Catalog"
      customMain={
        <WorkspacePage
          title="DSPy Tools Catalog"
          description="Inspect registered tools, capabilities, and execution policies available to the DSPy engine."
          icon={Wrench}
          action={
            <Switch
              label="Read-only tools"
              checked={readOnlyOnly}
              onToggle={() => setReadOnlyOnly((value) => !value)}
              disabled={!tools.data}
            />
          }
        >

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
            {visibleTools && visibleTools.length === 0 && (
              <p className="text-sm text-muted-foreground" role="status">
                {readOnlyOnly
                  ? 'No read-only tools are registered with the DSPy engine.'
                  : 'No tools are registered with the DSPy engine.'}
              </p>
            )}
            {visibleTools && visibleTools.length > 0 && (
              <CardGroup orientation="card" columns={1} separated border="outlined">
                {visibleTools.map((tool) => (
                  <ToolCard key={tool.name} tool={tool} />
                ))}
              </CardGroup>
            )}
        </WorkspacePage>
      }
    />
  )
}
