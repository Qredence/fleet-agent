import { useParams } from 'react-router-dom'
import { Sparkles, Play, CheckCircle2, ArrowUpRight, Code, Activity } from 'lucide-react'

import { AgentWorkspace } from '@/components/workspace/agent-workspace'
import { WorkspacePage } from '@/components/workspace/workspace-page'
import { useThreads } from '@/features/threads/use-threads'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Card, CardContent, CardGroup, CardHeader, CardMedia, CardTitle } from '@/components/ui/card'
import { useIsMobile } from '@/hooks/use-media-query'

/** Renders preview metrics and architecture for the DSPy Program Optimizer. */
export function OptimizerRoute() {
  const { projectId } = useParams<{ projectId: string }>()
  const threads = useThreads(projectId)
  const thread = threads.data?.[0]
  const isMobile = useIsMobile()

  return (
    <AgentWorkspace
      projectId={projectId}
      threadId={thread?.id}
      threadTitle="DSPy Program Optimizer"
      customMain={
        <WorkspacePage
          title="DSPy Program Optimizer (Flex + GEPA)"
          description="Optimize prompt instructions, few-shot demonstrations, and module architecture for this project."
          icon={Sparkles}
          notice="Preview only — these metrics and the program below are sample data, not results from this project."
          action={
            <Button disabled title="Preview — coming soon">
              <Play className="size-4" aria-hidden="true" />
              Run GEPA Optimization
            </Button>
          }
        >
          <CardGroup columns={isMobile ? 1 : 2} border="outlined" separated>
            <Card className="bg-card">
              <CardHeader>
                <CardMedia icon={Activity} />
                <h3><CardTitle>Groundedness (F1)</CardTitle></h3>
              </CardHeader>
              <CardContent className="space-y-2">
                <Badge variant="secondary">Sample metric</Badge>
                <p className="text-2xl font-semibold text-foreground">94.2%</p>
                <p className="flex items-center gap-1 text-xs text-muted-foreground">
                  <ArrowUpRight className="size-3" aria-hidden="true" /> +14.6% vs sample baseline
                </p>
              </CardContent>
            </Card>
            <Card className="bg-card">
              <CardHeader>
                <CardMedia icon={CheckCircle2} />
                <h3><CardTitle>Answer completeness</CardTitle></h3>
              </CardHeader>
              <CardContent className="space-y-2">
                <Badge variant="secondary">Sample metric</Badge>
                <p className="text-2xl font-semibold text-foreground">91.8%</p>
                <p className="flex items-center gap-1 text-xs text-muted-foreground">
                  <ArrowUpRight className="size-3" aria-hidden="true" /> +11.2% vs sample baseline
                </p>
              </CardContent>
            </Card>
            <Card className="bg-card">
              <CardHeader>
                <CardMedia icon={Code} />
                <h3><CardTitle>Active module (example)</CardTitle></h3>
              </CardHeader>
              <CardContent className="space-y-2">
                <Badge variant="secondary">Sample program</Badge>
                <p className="break-words text-xl font-semibold text-foreground">FlexModule</p>
                <p className="text-xs text-muted-foreground">3 Decomposed Predictors (Gen 3)</p>
              </CardContent>
            </Card>
          </CardGroup>

          <CardGroup border="outlined" separated>
            <Card className="min-w-0 bg-card">
              <CardHeader>
                <h3><CardTitle>Optimized Program Architecture (module_src)</CardTitle></h3>
                <p className="text-xs text-muted-foreground">Sample program · not generated from this project</p>
              </CardHeader>
              <CardContent className="min-w-0">
                <pre className="max-w-full overflow-x-auto rounded-lg border border-border bg-muted/60 p-4 text-xs leading-relaxed text-muted-foreground"><code>
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
                </code></pre>
              </CardContent>
            </Card>
          </CardGroup>
        </WorkspacePage>
      }
    />
  )
}
