import { useMemo, useState, type ReactNode } from 'react'
import {
  ChevronDown,
  ChevronRight,
  FileCode,
  FileText,
  Folder,
  FolderOpen,
  Search,
  Settings,
} from 'lucide-react'

import { Input } from '@/components/ui/input'
import { useShape } from '@/lib/shape-context'
import { cn } from '@/lib/utils'

interface FileNode {
  name: string
  path: string
  type: 'file' | 'directory'
  status?: 'modified' | 'added' | 'untracked'
  icon?: 'code' | 'json' | 'text' | 'config'
  children?: FileNode[]
}

const sampleTree: FileNode[] = [
  {
    name: '.agents',
    path: '.agents',
    type: 'directory',
    children: [
      { name: 'skills', path: '.agents/skills', type: 'directory' },
    ],
  },
  { name: '.chunk', path: '.chunk', type: 'directory' },
  { name: '.circleci', path: '.circleci', type: 'directory' },
  { name: '.claude', path: '.claude', type: 'directory' },
  { name: '.codex', path: '.codex', type: 'directory' },
  { name: '.git', path: '.git', type: 'directory' },
  { name: '.github', path: '.github', type: 'directory' },
  { name: '.remember', path: '.remember', type: 'directory' },
  { name: '.ruff_cache', path: '.ruff_cache', type: 'directory' },
  {
    name: 'apps',
    path: 'apps',
    type: 'directory',
    children: [
      { name: 'api', path: 'apps/api', type: 'directory' },
      { name: 'web', path: 'apps/web', type: 'directory' },
    ],
  },
  { name: 'node_modules', path: 'node_modules', type: 'directory' },
  { name: 'packages', path: 'packages', type: 'directory' },
  { name: 'scripts', path: 'scripts', type: 'directory' },
  { name: '.gitignore', path: '.gitignore', type: 'file', icon: 'config' },
  { name: 'AGENTS.md', path: 'AGENTS.md', type: 'file', status: 'modified', icon: 'text' },
  { name: 'CODE_OF_CONDUCT.md', path: 'CODE_OF_CONDUCT.md', type: 'file', status: 'modified', icon: 'text' },
  { name: 'compose.yaml', path: 'compose.yaml', type: 'file', icon: 'config' },
  { name: 'CONTRIBUTING.md', path: 'CONTRIBUTING.md', type: 'file', status: 'modified', icon: 'text' },
  { name: 'LICENSE', path: 'LICENSE', type: 'file', icon: 'text' },
  { name: 'package.json', path: 'package.json', type: 'file', icon: 'json' },
  { name: 'PLAN.md', path: 'PLAN.md', type: 'file', status: 'modified', icon: 'text' },
  { name: 'pnpm-lock.yaml', path: 'pnpm-lock.yaml', type: 'file', icon: 'config' },
  { name: 'pnpm-workspace.yaml', path: 'pnpm-workspace.yaml', type: 'file', icon: 'config' },
  { name: 'README.md', path: 'README.md', type: 'file', status: 'modified', icon: 'text' },
  { name: 'SECURITY.md', path: 'SECURITY.md', type: 'file', status: 'modified', icon: 'text' },
  { name: 'skills-lock.json', path: 'skills-lock.json', type: 'file', icon: 'json' },
  { name: 'SUPPORT.md', path: 'SUPPORT.md', type: 'file', status: 'modified', icon: 'text' },
]

/** Keeps nodes whose name matches, or that contain a matching descendant. */
function filterTree(nodes: FileNode[], needle: string): FileNode[] {
  if (!needle) return nodes
  return nodes
    .map((node) => {
      const matches = node.name.toLowerCase().includes(needle)
      const children = node.children
        ? filterTree(node.children, needle)
        : []
      if (!matches && children.length === 0) return null
      return matches ? node : { ...node, children }
    })
    .filter((node): node is FileNode => node !== null)
}

/** One tree row: disclosure for directories, selection for files. */
function FileTreeRow({
  node,
  depth,
  open,
  selected,
  onToggle,
  onSelect,
}: {
  node: FileNode
  depth: number
  open: boolean
  selected: boolean
  onToggle: (path: string) => void
  onSelect: (path: string) => void
}) {
  const isDir = node.type === 'directory'
  // Rows follow the shape ladder's `item` step — the same radius the sidebar
  // menu rows take, so the tree reads as a sibling of the sidebar in pill mode.
  const shape = useShape()

  return (
    <button
      type="button"
      aria-expanded={isDir ? open : undefined}
      onClick={() => (isDir ? onToggle(node.path) : onSelect(node.path))}
      className={cn(
        'flex items-center gap-1.5 px-2 py-1 text-start font-mono text-xs transition-colors select-none',
        shape.item,
        selected
          ? 'bg-muted font-semibold text-foreground'
          : 'text-muted-foreground hover:bg-muted/50 hover:text-foreground',
      )}
      style={{ paddingInlineStart: `${depth * 12 + 8}px` }}
    >
      {isDir ? (
        <span className="inline-flex size-3 shrink-0 rtl:-scale-x-100">
          {open ? (
            <ChevronDown className="size-3 text-muted-foreground/70" />
          ) : (
            <ChevronRight className="size-3 text-muted-foreground/70" />
          )}
        </span>
      ) : (
        <span className="w-3 shrink-0" />
      )}

      {isDir ? (
        open ? (
          <FolderOpen className="size-3.5 shrink-0 text-muted-foreground" />
        ) : (
          <Folder className="size-3.5 shrink-0 text-muted-foreground" />
        )
      ) : node.icon === 'json' ? (
        <span className="size-3.5 text-center font-mono text-[10px] font-bold leading-none text-amber-400">
          {'{ }'}
        </span>
      ) : node.icon === 'config' ? (
        <Settings className="size-3.5 shrink-0 text-muted-foreground" />
      ) : node.icon === 'code' ? (
        <FileCode className="size-3.5 shrink-0 text-sky-400" />
      ) : (
        <FileText className="size-3.5 shrink-0 text-muted-foreground" />
      )}

      <span className="flex-1 truncate">{node.name}</span>

      {node.status === 'modified' && (
        <span className="px-1 font-mono text-[10px] font-bold text-emerald-400">
          M↓
        </span>
      )}
    </button>
  )
}

/**
 * Renders a searchable, expandable file tree with selectable files, docked
 * at the bottom of the process panel.
 *
 * @param selectedPath - The path of the currently selected file or directory.
 * @param onSelectPath - Callback invoked with the path when a file is selected.
 */
export function FileExplorer({
  selectedPath = 'README.md',
  onSelectPath,
}: {
  selectedPath?: string
  onSelectPath?: (path: string) => void
}) {
  const [filter, setFilter] = useState('')
  const [openDirs, setOpenDirs] = useState<Record<string, boolean>>({
    apps: false,
    '.agents': false,
  })

  const needle = filter.trim().toLowerCase()
  const visibleTree = useMemo(() => filterTree(sampleTree, needle), [needle])

  const toggleDir = (dirPath: string) => {
    setOpenDirs((prev) => ({ ...prev, [dirPath]: !prev[dirPath] }))
  }

  const renderNodes = (nodes: FileNode[], depth: number): ReactNode[] =>
    nodes.flatMap((node) => {
      const isDir = node.type === 'directory'
      // An active filter force-expands surviving directories so nested
      // matches stay reachable.
      const open = needle ? true : (openDirs[node.path] ?? false)
      const row = (
        <FileTreeRow
          key={node.path}
          node={node}
          depth={depth}
          open={open}
          selected={selectedPath === node.path}
          onToggle={toggleDir}
          onSelect={(path) => onSelectPath?.(path)}
        />
      )
      return isDir && open && node.children
        ? [row, ...renderNodes(node.children, depth + 1)]
        : [row]
    })

  return (
    <div className="flex max-h-56 min-h-0 shrink-0 flex-col gap-2 border-t bg-sidebar/30 p-2">
      <div className="relative">
        <Search className="absolute start-2.5 top-1/2 size-3.5 -translate-y-1/2 text-muted-foreground" />
        <Input
          aria-label="Filter workspace files"
          placeholder="Filter files…"
          value={filter}
          onChange={(e) => setFilter(e.target.value)}
          className="h-7 border-border/60 bg-background/50 ps-8 pe-2 text-xs placeholder:text-muted-foreground/60"
        />
      </div>

      <div className="min-h-0 flex-1 space-y-0.5 overflow-y-auto">
        {visibleTree.length === 0 ? (
          <p className="px-2 py-1 font-mono text-xs text-muted-foreground">
            No matching files.
          </p>
        ) : (
          renderNodes(visibleTree, 0)
        )}
      </div>
    </div>
  )
}
