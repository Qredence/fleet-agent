import { useParams } from 'react-router-dom'
import { Wrench, Check, FileCode, Search, Globe, Info } from 'lucide-react'

import { AgentWorkspace } from '@/components/workspace/agent-workspace'
import { useThreads } from '@/features/threads/use-threads'
import { Badge } from '@/components/ui/badge'

const sampleTools = [
  {
    name: 'search_docs',
    icon: Search,
    type: 'Built-in Knowledge',
    description: 'Searches bundled local project documentation and knowledge corpus with BM25 + embedding ranking.',
    readOnly: true,
    idempotent: true,
    parallelizable: true,
    timeout: '30s',
  },
  {
    name: 'write_report',
    icon: FileCode,
    type: 'Artifact Generation',
    description: 'Produces a size-capped, user-safe Markdown report with controlled download access.',
    readOnly: false,
    idempotent: false,
    parallelizable: false,
    timeout: '60s',
  },
  {
    name: 'web_search',
    icon: Globe,
    type: 'Web Discovery',
    description: 'Tavily-backed live search engine discovery with run-scoped result IDs and untrusted content sandboxing.',
    readOnly: true,
    idempotent: true,
    parallelizable: true,
    timeout: '30s',
  },
  {
    name: 'fetch_page',
    icon: Globe,
    type: 'Web Discovery',
    description: 'Fetches a single web page through the Tavily extraction endpoint with size-capped, sandboxed content.',
    readOnly: true,
    idempotent: true,
    parallelizable: true,
    timeout: '30s',
  },
]

export function ToolsRoute() {
  const { projectId } = useParams<{ projectId: string }>()
  const threads = useThreads(projectId)
  const thread = threads.data?.[0]

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
              <p className="text-xs text-muted-foreground/70 mt-2 flex items-center gap-1.5">
                <Info className="size-3" aria-hidden />
                Preview — the cards below show sample data and are not yet connected to the backend.
              </p>
            </div>

            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              {sampleTools.map((tool) => (
                <div key={tool.name} className="rounded-xl border bg-card p-5 space-y-3 hover:border-primary/50 transition-colors">
                  <div className="flex items-start justify-between gap-2">
                    <div className="flex items-center gap-2.5">
                      <div className="flex size-8 items-center justify-center rounded-lg bg-muted text-foreground">
                        <tool.icon className="size-4" />
                      </div>
                      <div>
                        <h2 className="text-sm font-semibold font-mono">{tool.name}</h2>
                        <span className="text-xs text-muted-foreground">{tool.type}</span>
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
                    {tool.readOnly && (
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
                      ⏱ {tool.timeout}
                    </Badge>
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
