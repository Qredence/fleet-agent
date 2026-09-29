import { useState } from 'react'
import { useParams } from 'react-router-dom'
import { Plug, Plus, Database, FolderGit2, Globe, LogOut } from 'lucide-react'

import { AgentWorkspace } from '@/components/workspace/agent-workspace'
import { WorkspacePage } from '@/components/workspace/workspace-page'
import { useThreads } from '@/features/threads/use-threads'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Card, CardContent, CardFooter, CardGroup, CardHeader, CardMedia, CardTitle } from '@/components/ui/card'
import { OpenRouterLogo } from '@/features/providers/components/openrouter-logo'
import { OpenRouterButton } from '@/features/providers/components/openrouter-button'
import { useOpenRouterAuth } from '@/features/providers/use-openrouter-auth'
import { SettingsDialog } from '@/features/providers/settings/settings-dialog'
import { maskApiKey } from '@/features/providers/openrouter-auth'
import { useIsMobile } from '@/hooks/use-media-query'

const sampleConnectors = [
  {
    name: 'GitHub MCP Server',
    icon: FolderGit2,
    type: 'Model Context Protocol (Remote HTTP)',
    endpoint: 'http://localhost:8001/mcp',
    latency: '34ms',
    toolsCount: 8,
  },
  {
    name: 'PostgreSQL Lakebase MCP',
    icon: Database,
    type: 'Local Stdio Process',
    endpoint: 'stdio://@bytebase/mcp-postgres',
    latency: '12ms',
    toolsCount: 5,
  },
  {
    name: 'Tavily Search Provider',
    icon: Globe,
    type: 'REST Gateway',
    endpoint: 'https://api.tavily.com/v1',
    latency: '128ms',
    toolsCount: 2,
  },
]

/** Renders the live OpenRouter integration and preview-only connector examples. */
export function ConnectorsRoute() {
  const { projectId } = useParams<{ projectId: string }>()
  const threads = useThreads(projectId)
  const thread = threads.data?.[0]
  const { apiKey, isAuthenticated, signOut, selectedModel, customModelEnabled } =
    useOpenRouterAuth()
  const [settingsOpen, setSettingsOpen] = useState(false)
  const isMobile = useIsMobile()

  return (
    <AgentWorkspace
      projectId={projectId}
      threadId={thread?.id}
      threadTitle="Connectors & MCP Hub"
      customMain={
        <WorkspacePage
          title="Connectors & MCP Hub"
          description="Connect Model Context Protocol (MCP) servers, databases, and external providers into DSPy tools."
          icon={Plug}
          notice="OpenRouter is live. The other connectors are examples only and are not connected."
          action={
            <Button disabled aria-describedby="add-connector-note">
              <Plus className="size-4" aria-hidden="true" />
              Add Connector
            </Button>
          }
        >
          <span id="add-connector-note" className="sr-only">Preview only — adding connectors is not available yet.</span>
          <CardGroup orientation="card" columns={isMobile ? 1 : 2} border="outlined" separated>
            <Card className="bg-card">
              <CardHeader className="min-w-0">
                <div className="mb-2 flex size-9 items-center justify-center rounded-lg bg-primary/10 text-primary">
                  <OpenRouterLogo className="size-5" />
                </div>
                <h3><CardTitle>OpenRouter AI Gateway</CardTitle></h3>
                <p className="text-xs text-muted-foreground">OAuth PKCE / REST LLM Gateway</p>
              </CardHeader>
              <CardContent className="min-w-0 space-y-2">
                <Badge variant="outline" className="text-xs">
                  {isAuthenticated ? 'Connected' : 'Ready to connect'}
                </Badge>
                <p className="break-all font-mono text-xs text-muted-foreground">
                  {isAuthenticated
                    ? `Key: ${maskApiKey(apiKey)} (${customModelEnabled ? selectedModel : 'server-default'})`
                    : 'https://openrouter.ai'}
                </p>
              </CardContent>
              <CardFooter className="mt-auto gap-2">
                {isAuthenticated ? (
                  <>
                    <Button variant="outline" size="sm" onClick={() => setSettingsOpen(true)}>Configure</Button>
                    <Button variant="ghost" size="sm" onClick={signOut} className="text-destructive hover:bg-destructive/10">
                      <LogOut className="size-3.5" aria-hidden="true" />
                      Disconnect
                    </Button>
                  </>
                ) : (
                  <OpenRouterButton variant="cta" size="sm">Connect OpenRouter</OpenRouterButton>
                )}
              </CardFooter>
            </Card>
            {sampleConnectors.map((connector) => (
              <Card key={connector.name} className="bg-card">
                <CardHeader className="min-w-0">
                  <CardMedia icon={connector.icon} />
                  <h3><CardTitle>{connector.name}</CardTitle></h3>
                  <p className="text-xs text-muted-foreground">{connector.type}</p>
                </CardHeader>
                <CardContent className="min-w-0 space-y-2">
                  <Badge variant="secondary" className="text-xs">Sample · not connected</Badge>
                  <p className="break-all font-mono text-xs text-muted-foreground">{connector.endpoint}</p>
                  <p className="text-xs text-muted-foreground">
                    Sample latency: {connector.latency} · Sample tools: {connector.toolsCount}
                  </p>
                </CardContent>
                <CardFooter className="mt-auto">
                  <Button variant="outline" size="sm" disabled title="Preview — coming soon">Configure</Button>
                </CardFooter>
              </Card>
            ))}
          </CardGroup>
          <SettingsDialog open={settingsOpen} onOpenChange={setSettingsOpen} />
        </WorkspacePage>
      }
    />
  )
}
