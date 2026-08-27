import { useState } from 'react'
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

/**
 * Renders a searchable, expandable file tree with selectable files.
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

  const toggleDir = (dirPath: string) => {
    setOpenDirs((prev) => ({ ...prev, [dirPath]: !prev[dirPath] }))
  }

  const renderNode = (node: FileNode, depth = 0) => {
    if (filter && !node.name.toLowerCase().includes(filter.toLowerCase())) {
      if (node.type === 'file') return null
      const matchingChildren = node.children?.some((c) =>
        c.name.toLowerCase().includes(filter.toLowerCase())
      )
      if (!matchingChildren) return null
    }

    const isDir = node.type === 'directory'
    // An active filter expands every surviving directory so a nested match
    // is actually reachable.
    const isOpen = filter ? true : (openDirs[node.path] ?? false)
    const isSelected = selectedPath === node.path

    return (
      <div key={node.path} className="flex flex-col">
        <button
          type="button"
          onClick={() => {
            if (isDir) {
              toggleDir(node.path)
            } else {
              onSelectPath?.(node.path)
            }
          }}
          className={cn(
            'flex items-center gap-1.5 px-2 py-1 text-xs font-mono rounded-md transition-colors text-left select-none',
            isSelected
              ? 'bg-muted text-foreground font-semibold'
              : 'text-muted-foreground hover:bg-muted/50 hover:text-foreground',
          )}
          style={{ paddingLeft: `${depth * 12 + 8}px` }}
        >
          {isDir ? (
            isOpen ? (
              <ChevronDown className="size-3 shrink-0 text-muted-foreground/70" />
            ) : (
              <ChevronRight className="size-3 shrink-0 text-muted-foreground/70" />
            )
          ) : (
            <span className="w-3" />
          )}

          {isDir ? (
            isOpen ? (
              <FolderOpen className="size-3.5 shrink-0 text-muted-foreground" />
            ) : (
              <Folder className="size-3.5 shrink-0 text-muted-foreground" />
            )
          ) : node.icon === 'json' ? (
            <span className="size-3.5 text-[10px] font-bold text-amber-400 font-mono text-center leading-none">
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
            <span className="text-[10px] font-bold text-emerald-400 font-mono px-1">
              M↓
            </span>
          )}
        </button>

        {isDir && isOpen && node.children && (
          <div className="flex flex-col">
            {node.children.map((child) => renderNode(child, depth + 1))}
          </div>
        )}
      </div>
    )
  }

  return (
    <div className="flex h-full flex-col p-2 space-y-2 border-l border-border/60 bg-sidebar/30">
      <div className="relative">
        <Search className="size-3.5 absolute left-2.5 top-1/2 -translate-y-1/2 text-muted-foreground" />
        <Input
          placeholder="Filter files..."
          value={filter}
          onChange={(e) => setFilter(e.target.value)}
          className="h-7 text-xs pl-8 pr-2 bg-background/50 border-border/60 rounded-md placeholder:text-muted-foreground/60"
        />
      </div>

      <div className="flex-1 overflow-y-auto space-y-0.5">
        {sampleTree.map((node) => renderNode(node, 0))}
      </div>
    </div>
  )
}
