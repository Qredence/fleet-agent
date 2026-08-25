import { useState } from 'react'

import { useAssistantDataUI } from '@assistant-ui/react'

import {
  AgentPlan,
  type AgentPlanStepStatus,
} from '@/components/elements/agent-plan'
import {
  ToolGroup,
  type GroupedTool,
} from '@/components/elements/tool-group'
import {
  ResearchReport,
  type ReportSection,
  type SectionState,
} from '@/components/elements/research-report'
import {
  Sources,
  type Source,
} from '@/components/elements/sources'
import {
  WebSearch,
  type WebSearchResult,
} from '@/components/elements/web-search'

const INLINE_SCHEMA_VERSION = 1
const MAX_TEXT = 240
const MAX_STEPS = 4
const MAX_TOOLS = 4
const MAX_SOURCES = 12
const MAX_SECTIONS = 8

type RecordValue = Record<string, unknown>

function isRecord(value: unknown): value is RecordValue {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function text(value: unknown, limit = MAX_TEXT): string {
  return typeof value === 'string' ? value.trim().slice(0, limit) : ''
}

function versioned(value: unknown): value is RecordValue {
  return (
    isRecord(value) &&
    value.schemaVersion === INLINE_SCHEMA_VERSION
  )
}

const isPlanStatus = (value: unknown): value is AgentPlanStepStatus =>
  value === 'pending' ||
  value === 'running' ||
  value === 'completed' ||
  value === 'failed' ||
  value === 'skipped'

function toolState(value: unknown): GroupedTool['state'] {
  if (value === 'done') return 'done'
  if (value === 'failed') return 'failed'
  return 'running'
}

function parseProgress(value: unknown) {
  if (!versioned(value) || !Array.isArray(value.steps)) return null
  const steps = value.steps
    .filter(isRecord)
    .slice(0, MAX_STEPS)
    .map((step, index) => ({
      id: text(step.id, 80) || `phase-${index}`,
      label: text(step.label) || 'Agent step',
      status: isPlanStatus(step.status) ? step.status : 'pending',
    }))
  if (steps.length === 0) return null

  const tools = Array.isArray(value.tools)
    ? value.tools.filter(isRecord).slice(0, MAX_TOOLS).map((tool, index) => ({
        id: text(tool.id, 80) || `research-${index}`,
        name: text(tool.name, 80) || 'research',
        target: text(tool.target) || 'Research task',
        state: toolState(tool.state),
        ...(typeof tool.durationMs === 'number' && tool.durationMs >= 0
          ? { durationMs: Math.floor(tool.durationMs) }
          : {}),
      }))
    : []

  return {
    steps,
    activeIndex:
      typeof value.activeIndex === 'number' ? Math.floor(value.activeIndex) : 0,
    tools,
  }
}

function parseWebSearch(value: unknown) {
  if (!versioned(value) || !Array.isArray(value.results)) return null
  const results: WebSearchResult[] = value.results
    .filter(isRecord)
    .slice(0, MAX_SOURCES)
    .map((result) => ({
      title: text(result.title) || 'Untitled source',
      domain: text(result.domain, 120) || 'source',
    }))
  return {
    query: text(value.query) || 'Web search',
    results,
    visibleResults:
      typeof value.visibleResults === 'number'
        ? Math.floor(value.visibleResults)
        : results.length,
    searching: value.searching === true,
    cycle: typeof value.cycle === 'number' ? Math.floor(value.cycle) : 0,
  }
}

function parseSources(value: unknown) {
  if (!versioned(value) || !Array.isArray(value.sources)) return null
  const sources: Source[] = value.sources
    .filter(isRecord)
    .slice(0, MAX_SOURCES)
    .map((source) => ({
      title: text(source.title) || 'Untitled source',
      domain: text(source.domain, 120) || 'source',
    }))
  return sources.length > 0 ? { sources } : null
}

function parseReport(value: unknown) {
  if (!versioned(value) || !Array.isArray(value.sections)) return null
  const sections: ReportSection[] = value.sections
    .filter(isRecord)
    .slice(0, MAX_SECTIONS)
    .map((section, index) => {
      const state = section.state
      const safeState: SectionState =
        state === 'writing' || state === 'done' || state === 'failed'
          ? state
          : 'pending'
      return {
        id: text(section.id, 80) || `section-${index}`,
        heading: text(section.heading) || 'Report section',
        state: safeState,
        sources:
          typeof section.sources === 'number' && section.sources >= 0
            ? Math.floor(section.sources)
            : 0,
        ...(text(section.preview) ? { preview: text(section.preview) } : {}),
      }
    })
  if (sections.length === 0) return null
  return {
    title: text(value.title) || 'Research report',
    sections,
    sourcesRead:
      typeof value.sourcesRead === 'number' && value.sourcesRead >= 0
        ? Math.floor(value.sourcesRead)
        : 0,
  }
}

function InlineProgress({ data }: { data: unknown }) {
  const parsed = parseProgress(data)
  const [open, setOpen] = useState(false)
  if (!parsed) return null

  return (
    <div className="flex flex-col gap-3 py-2" data-slot="inline-agent-progress">
      <AgentPlan
        steps={parsed.steps.map((step) => step.label)}
        statuses={parsed.steps.map((step) => step.status)}
        activeIndex={parsed.activeIndex}
        aria-label="Agent progress"
      />
      {parsed.tools.length > 0 && (
        <ToolGroup
          label="Parallel research tasks"
          tools={parsed.tools}
          open={open}
          onOpenChange={setOpen}
          aria-label="Parallel research tasks"
        />
      )}
    </div>
  )
}

function InlineWebSearch({ data }: { data: unknown }) {
  const parsed = parseWebSearch(data)
  if (!parsed) return null
  return (
    <WebSearch
      query={parsed.query}
      results={parsed.results}
      visibleResults={parsed.visibleResults}
      searching={parsed.searching}
      cycle={parsed.cycle}
      className="py-2"
      aria-label={`Web search: ${parsed.query}`}
    />
  )
}

function InlineSources({ data }: { data: unknown }) {
  const parsed = parseSources(data)
  const [open, setOpen] = useState(false)
  if (!parsed) return null
  return (
    <Sources
      sources={parsed.sources}
      open={open}
      onOpenChange={setOpen}
      className="py-2"
    />
  )
}

function InlineResearchReport({ data }: { data: unknown }) {
  const parsed = parseReport(data)
  if (!parsed) return null
  return (
    <ResearchReport
      title={parsed.title}
      sections={parsed.sections}
      sourcesRead={parsed.sourcesRead}
      className="my-2"
      aria-label="Research report progress"
    />
  )
}

/**
 * Registers safe, versioned AG-UI CUSTOM projections for the transcript.
 * Process state remains owned by useAgUiState in the process panel; these
 * renderers only display bounded message-scoped summaries.
 */
export function InlineAgentDataUIRegistration() {
  useAssistantDataUI({
    name: 'agent-progress',
    render: ({ data }) => <InlineProgress data={data} />,
  })
  useAssistantDataUI({
    name: 'web-search',
    render: ({ data }) => <InlineWebSearch data={data} />,
  })
  useAssistantDataUI({
    name: 'sources',
    render: ({ data }) => <InlineSources data={data} />,
  })
  useAssistantDataUI({
    name: 'research-report',
    render: ({ data }) => <InlineResearchReport data={data} />,
  })
  return null
}
