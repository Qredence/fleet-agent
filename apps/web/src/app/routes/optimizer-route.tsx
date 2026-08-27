import { useParams } from 'react-router-dom'
import { Sparkles, Play, CheckCircle2, ArrowUpRight, Code, Activity, Info } from 'lucide-react'

import { AgentWorkspace } from '@/components/workspace/agent-workspace'
import { useThreads } from '@/features/threads/use-threads'
import { Button } from '@/components/ui/button'

export function OptimizerRoute() {
  const { projectId } = useParams<{ projectId: string }>()
  const threads = useThreads(projectId)
  const thread = threads.data?.[0]

  return (
    <AgentWorkspace
      projectId={projectId}
      threadId={thread?.id}
      threadTitle="DSPy Program Optimizer"
      customMain={
        <main
          aria-label="Optimizer Studio"
          className="flex h-full min-w-0 flex-1 flex-col bg-background"
        >
          <div className="flex-1 overflow-y-auto p-6 space-y-6">
            <div className="flex items-center justify-between border-b pb-4">
              <div>
                <h1 className="text-xl font-semibold flex items-center gap-2">
                  <Sparkles className="size-5 text-amber-400" />
                  DSPy Program Optimizer (Flex + GEPA)
                </h1>
                <p className="text-sm text-muted-foreground mt-1">
                  Optimize prompt instructions, few-shot demonstrations, and module architecture for this project.
                </p>
                <p className="text-xs text-muted-foreground/70 mt-2 flex items-center gap-1.5">
                  <Info className="size-3" aria-hidden />
                  Preview — the metrics and program below show sample data and are not yet connected to the backend.
                </p>
              </div>
              <Button className="gap-2 bg-primary text-primary-foreground" disabled title="Preview — coming soon">
                <Play className="size-4" />
                Run GEPA Optimization
              </Button>
            </div>

            <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
              <div className="rounded-xl border bg-card p-4 space-y-2">
                <div className="flex items-center justify-between text-muted-foreground text-xs font-medium">
                  <span>GROUNDEDNESS (F1)</span>
                  <Activity className="size-4 text-emerald-400" />
                </div>
                <div className="text-2xl font-bold text-foreground">94.2%</div>
                <p className="text-xs text-emerald-400 flex items-center gap-1">
                  <ArrowUpRight className="size-3" /> +14.6% vs Baseline
                </p>
              </div>

              <div className="rounded-xl border bg-card p-4 space-y-2">
                <div className="flex items-center justify-between text-muted-foreground text-xs font-medium">
                  <span>ANSWER COMPLETENESS</span>
                  <CheckCircle2 className="size-4 text-emerald-400" />
                </div>
                <div className="text-2xl font-bold text-foreground">91.8%</div>
                <p className="text-xs text-emerald-400 flex items-center gap-1">
                  <ArrowUpRight className="size-3" /> +11.2% vs Baseline
                </p>
              </div>

              <div className="rounded-xl border bg-card p-4 space-y-2">
                <div className="flex items-center justify-between text-muted-foreground text-xs font-medium">
                  <span>ACTIVE MODULE</span>
                  <Code className="size-4 text-amber-400" />
                </div>
                <div className="text-2xl font-bold text-foreground">FlexModule</div>
                <p className="text-xs text-muted-foreground">
                  3 Decomposed Predictors (Gen 3)
                </p>
              </div>
            </div>

            <div className="rounded-xl border bg-card p-5 space-y-3">
              <h2 className="text-sm font-semibold flex items-center gap-2">
                <Code className="size-4 text-muted-foreground" />
                Optimized Program Architecture (<code className="text-xs font-mono text-primary">module_src</code>)
              </h2>
              <pre className="rounded-lg bg-muted/60 p-4 text-xs font-mono text-muted-foreground overflow-x-auto leading-relaxed border">
{`class MarketResearchAgent(dspy.Module):
    def __init__(self):
        super().__init__()
        self.decomposer = dspy.Predict("request -> subqueries: list[str]")
        self.researcher = dspy.RLM("subquery -> evidence: str", tools=[search_docs, web_search])
        self.synthesizer = dspy.Predict("request, evidence -> answer, summary, decisions")

    def forward(self, request: str):
        subtasks = self.decomposer(request=request).subqueries
        evidence = [self.researcher(subquery=q).evidence for q in subtasks]
        return self.synthesizer(request=request, evidence="\\n".join(evidence))`}
              </pre>
            </div>
          </div>
        </main>
      }
    />
  )
}
