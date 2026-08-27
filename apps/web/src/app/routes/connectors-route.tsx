import { useParams } from 'react-router-dom'
import { Plug, Plus, Database, FolderGit2, Globe, Info } from 'lucide-react'

import { AgentWorkspace } from '@/components/workspace/agent-workspace'
import { useThreads } from '@/features/threads/use-threads'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'

const sampleConnectors = [
  {
    name: 'GitHub MCP Server',
    icon: FolderGit2,
    type: 'Model Context Protocol (Remote HTTP)',
    endpoint: 'http://localhost:8001/mcp',
    status: 'connected',
    latency: '34ms',
    toolsCount: 8,
  },
  {
    name: 'PostgreSQL Lakebase MCP',
    icon: Database,
    type: 'Local Stdio Process',
    endpoint: 'stdio://@bytebase/mcp-postgres',
    status: 'connected',
    latency: '12ms',
    toolsCount: 5,
  },
  {
    name: 'Tavily Search Provider',
    icon: Globe,
    type: 'REST Gateway',
    endpoint: 'https://api.tavily.com/v1',
    status: 'connected',
    latency: '128ms',
    toolsCount: 2,
  },
]

/**
 * Renders the preview hub for project connectors and MCP integrations.
 *
 * @returns The connectors hub interface with sample connector data and preview controls.
 */
export function ConnectorsRoute() {
  const { projectId } = useParams<{ projectId: string }>()
  const threads = useThreads(projectId)
  const thread = threads.data?.[0]

  return (
    <AgentWorkspace
      projectId={projectId}
      threadId={thread?.id}
      threadTitle="Connectors & MCP Hub"
      customMain={
        <main
          aria-label="Connectors Hub"
          className="flex h-full min-w-0 flex-1 flex-col bg-background"
        >
          <div className="flex-1 overflow-y-auto p-6 space-y-6">
            <div className="flex items-center justify-between border-b pb-4">
              <div>
                <h1 className="text-xl font-semibold flex items-center gap-2">
                  <Plug className="size-5 text-emerald-400" />
                  Connectors & MCP Hub
                </h1>
                <p className="text-sm text-muted-foreground mt-1">
                  Connect Model Context Protocol (MCP) servers, databases, and external providers into DSPy tools.
                </p>
                <p className="text-xs text-muted-foreground/70 mt-2 flex items-center gap-1.5">
                  <Info className="size-3" aria-hidden />
                  Preview — the connectors below show sample data and are not yet connected to the backend.
                </p>
              </div>
              <Button className="gap-2 bg-primary text-primary-foreground" disabled title="Preview — coming soon">
                <Plus className="size-4" />
                Add Connector
              </Button>
            </div>

            <div className="space-y-3">
              {sampleConnectors.map((connector) => (
                <div key={connector.name} className="flex items-center justify-between rounded-xl border bg-card p-4 hover:border-primary/50 transition-colors">
                  <div className="flex items-center gap-3">
                    <div className="flex size-10 items-center justify-center rounded-xl bg-muted text-foreground">
                      <connector.icon className="size-5" />
                    </div>
                    <div>
                      <div className="flex items-center gap-2">
                        <h2 className="text-sm font-semibold">{connector.name}</h2>
                        <Badge variant="outline" className="text-[10px] text-emerald-400 border-emerald-500/30 bg-emerald-500/10">
                          {connector.status}
                        </Badge>
                      </div>
                      <div className="flex items-center gap-3 text-xs text-muted-foreground mt-0.5">
                        <span>{connector.type}</span>
                        <span>•</span>
                        <code className="font-mono text-[11px]">{connector.endpoint}</code>
                      </div>
                    </div>
                  </div>

                  <div className="flex items-center gap-4">
                    <div className="text-right text-xs">
                      <span className="text-muted-foreground font-mono">{connector.latency}</span>
                      <div className="text-[11px] text-muted-foreground">{connector.toolsCount} tools exposed</div>
                    </div>
                    <Button variant="outline" size="sm" disabled title="Preview — coming soon">
                      Configure
                    </Button>
                  </div>
                </div>
              ))}
            </div>
          </div>
        </main>
      }
    />
  )
}
