import { useState, type FormEvent, type ReactNode } from 'react'
import {
  Check,
  CircleDot,
  Cpu,
  ExternalLink,
  Eye,
  EyeOff,
  Globe,
  Key,
  Laptop,
  LogOut,
  MessageSquare,
  Moon,
  Palette,
  Pencil,
  Plus,
  Search,
  Server,
  ShieldCheck,
  Sun,
  Trash2,
  X,
  type LucideIcon,
} from 'lucide-react'

import { OpenRouterButton } from '@/components/auth/openrouter-button'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import {
  Card,
  CardAction,
  CardDescription,
  CardGroup,
  CardHeader,
  CardMedia,
  CardTitle,
} from '@/components/ui/card'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Switch } from '@/components/ui/switch'
import { useOpenRouterAuth } from '@/hooks/use-openrouter-auth'
import { useOpenCodeZenAuth } from '@/hooks/use-opencode-zen-auth'
import { useProviders } from '@/hooks/use-providers'
import {
  maskApiKey,
  DEFAULT_OPENROUTER_MODEL,
} from '@/lib/openrouter-auth'
import {
  DEFAULT_OPENCODE_ZEN_MODEL,
} from '@/lib/opencode-zen-auth'
import { useSearchSettings } from '@/hooks/use-search-settings'
import {
  maskSearchApiKey,
  SEARCH_PROVIDERS,
} from '@/lib/search-settings'
import {
  OPENROUTER_PROFILE_ID,
  OPENROUTER_BASE_URL,
  OPENCODE_ZEN_PROFILE_ID,
  OPENCODE_ZEN_BASE_URL,
  SERVER_DEFAULT_ID,
  type MessagesFormat,
  type ProviderProfile,
  type ResponseFormat,
} from '@/lib/providers'
import { ModelCardsRow } from './model-cards-row'
import { useWorkspaceStore } from '@/state/workspace-store'
import { cn } from '@/lib/utils'

/** Profile id that also works on insecure origins (randomUUID is secure-only). */
function newProfileId(): string {
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
    return crypto.randomUUID()
  }
  if (
    typeof crypto !== 'undefined' &&
    typeof crypto.getRandomValues === 'function'
  ) {
    const bytes = new Uint8Array(16)
    crypto.getRandomValues(bytes)
    return Array.from(bytes, (byte) => byte.toString(16).padStart(2, '0')).join(
      '',
    )
  }
  return `${Date.now().toString(36)}${Math.random().toString(36).slice(2, 10)}`
}

export interface SettingsDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
}

interface SegmentedOption<T extends string> {
  value: T
  label: string
}

function SegmentedOptions<T extends string>({
  ariaLabel,
  value,
  options,
  onChange,
}: {
  ariaLabel: string
  value: T
  options: SegmentedOption<T>[]
  onChange: (value: T) => void
}) {
  return (
    <div className="flex flex-wrap gap-1.5" role="group" aria-label={ariaLabel}>
      {options.map((option) => (
        <Button
          key={option.value}
          variant={value === option.value ? 'default' : 'outline'}
          size="sm"
          onClick={() => onChange(option.value)}
          className="h-7 text-xs gap-1.5"
        >
          {value === option.value && <Check className="size-3" />}
          {option.label}
        </Button>
      ))}
    </div>
  )
}

const RESPONSE_FORMAT_OPTIONS: SegmentedOption<ResponseFormat>[] = [
  { value: 'native_function_calling', label: 'Native function calling' },
  { value: 'json_tool_calls', label: 'JSON tool calls' },
]

const MESSAGES_FORMAT_OPTIONS: SegmentedOption<MessagesFormat>[] = [
  { value: 'system_role', label: 'System role' },
  { value: 'developer_role', label: 'Developer role' },
]

const SETTINGS_CATEGORIES = [
  {
    id: 'providers',
    label: 'Providers',
    description: 'Connect accounts and manage provider endpoints.',
    icon: Server,
  },
  {
    id: 'models',
    label: 'Models',
    description: 'Choose the model used for agent runs.',
    icon: Cpu,
  },
  {
    id: 'search',
    label: 'Web Search',
    description: 'Configure web search provider and browser API keys for agent research tools.',
    icon: Search,
  },
  {
    id: 'appearance',
    label: 'Appearance',
    description: 'Set your preferred color theme.',
    icon: Palette,
  },
] as const

type SettingsCategory = (typeof SETTINGS_CATEGORIES)[number]['id']

const EMPTY_FORM = {
  name: '',
  apiKey: '',
  modelId: '',
  baseUrl: '',
  responseFormat: 'native_function_calling' as ResponseFormat,
  messagesFormat: 'system_role' as MessagesFormat,
}

/**
 * SettingsSection: a clean semantic section matching Fluid Functionalism's
 * dialog-sidebar layout. Features a subtle icon + title heading, helper description,
 * trailing action (e.g. Switch or Badge), and borderless hairline divider.
 */
function SettingsSection({
  icon: Icon,
  title,
  description,
  action,
  children,
  className,
}: {
  icon?: LucideIcon
  title: string
  description?: string
  action?: ReactNode
  children: ReactNode
  className?: string
}) {
  return (
    <section className={cn('space-y-3.5', className)}>
      <div className="flex items-start justify-between gap-4 pb-2.5 border-b border-border/40">
        <div className="space-y-1 min-w-0">
          <div className="flex items-center gap-2">
            {Icon && <Icon className="size-4 text-muted-foreground shrink-0" />}
            <h3 className="text-sm font-semibold text-foreground tracking-tight">{title}</h3>
          </div>
          {description && (
            <p className="text-xs text-muted-foreground leading-normal">{description}</p>
          )}
        </div>
        {action && <div className="shrink-0 pt-0.5">{action}</div>}
      </div>
      <div>{children}</div>
    </section>
  )
}

/**
 * Settings & Preferences dialog with provider management (BYOK profiles,
 * OpenRouter OAuth, model selection) and theme configuration.
 */
export function SettingsDialog({ open, onOpenChange }: SettingsDialogProps) {
  const {
    apiKey,
    isAuthenticated,
    selectedModel,
    customModelEnabled,
    signOut,
    setApiKey,
    setSelectedModel,
    setCustomModelEnabled,
    error,
    clearError,
  } = useOpenRouterAuth()

  const {
    apiKey: openCodeZenApiKey,
    isAuthenticated: openCodeZenAuthenticated,
    selectedModel: openCodeZenSelectedModel,
    customModelEnabled: openCodeZenCustomModelEnabled,
    setApiKey: setOpenCodeZenApiKey,
    setSelectedModel: setOpenCodeZenSelectedModel,
    setCustomModelEnabled: setOpenCodeZenCustomModelEnabled,
    signOut: signOutOpenCodeZen,
  } = useOpenCodeZenAuth()

  const {
    profiles,
    activeProviderId,
    setActiveProviderId,
    upsertProfile,
    removeProfile,
  } = useProviders()
  const customProfiles = profiles.filter(
    (profile) =>
      profile.id !== OPENROUTER_PROFILE_ID &&
      profile.id !== OPENCODE_ZEN_PROFILE_ID,
  )

  const theme = useWorkspaceStore((s) => s.theme)
  const setTheme = useWorkspaceStore((s) => s.setTheme)

  const [manualKeyInput, setManualKeyInput] = useState('')
  const [showManualKeyForm, setShowManualKeyForm] = useState(false)
  const [customModelInput, setCustomModelInput] = useState(selectedModel)
  const [manualKeyError, setManualKeyError] = useState<string | null>(null)

  const [openCodeZenKeyInput, setOpenCodeZenKeyInput] = useState('')
  const [showOpenCodeZenKeyForm, setShowOpenCodeZenKeyForm] = useState(false)
  const [openCodeZenCustomModelInput, setOpenCodeZenCustomModelInput] = useState(
    openCodeZenSelectedModel,
  )
  const [openCodeZenKeyError, setOpenCodeZenKeyError] = useState<string | null>(
    null,
  )

  const [showProviderForm, setShowProviderForm] = useState(false)
  const [editingProfileId, setEditingProfileId] = useState<string | null>(null)
  const [providerForm, setProviderForm] = useState(EMPTY_FORM)
  const [providerFormError, setProviderFormError] = useState<string | null>(null)
  const [activeCategory, setActiveCategory] =
    useState<SettingsCategory>('providers')

  const {
    apiKey: searchApiKey,
    provider: searchProvider,
    isConnected: isSearchConnected,
    setApiKey: setSearchApiKey,
    clearApiKey: clearSearchApiKey,
    setProvider: setSearchProvider,
  } = useSearchSettings()

  const [searchKeyInput, setSearchKeyInput] = useState('')
  const [showSearchKeyForm, setShowSearchKeyForm] = useState(false)
  const [searchKeyError, setSearchKeyError] = useState<string | null>(null)
  const [showSearchSecret, setShowSearchSecret] = useState(false)

  const handleManualKeySubmit = (e: FormEvent) => {
    e.preventDefault()
    const trimmed = manualKeyInput.trim()
    if (!trimmed) {
      setManualKeyError('Please enter a valid API key.')
      return
    }
    if (!trimmed.startsWith('sk-or-') && !trimmed.startsWith('sk-')) {
      setManualKeyError('OpenRouter API keys typically begin with "sk-or-".')
      return
    }
    setApiKey(trimmed)
    setManualKeyInput('')
    setShowManualKeyForm(false)
    setManualKeyError(null)
  }

  const handleOpenCodeZenKeySubmit = (e: FormEvent) => {
    e.preventDefault()
    const trimmed = openCodeZenKeyInput.trim()
    if (!trimmed) {
      setOpenCodeZenKeyError('Please enter a valid OpenCode Zen API key.')
      return
    }
    if (trimmed.length < 8) {
      setOpenCodeZenKeyError('That key looks too short to be valid.')
      return
    }
    setOpenCodeZenApiKey(trimmed)
    setOpenCodeZenKeyInput('')
    setShowOpenCodeZenKeyForm(false)
    setOpenCodeZenKeyError(null)
  }

  const handleCustomModelSubmit = (e: FormEvent) => {
    e.preventDefault()
    const trimmed = customModelInput.trim()
    if (trimmed) {
      setSelectedModel(trimmed)
    }
  }

  const handleOpenCodeZenCustomModelSubmit = (e: FormEvent) => {
    e.preventDefault()
    const trimmed = openCodeZenCustomModelInput.trim()
    if (trimmed) {
      setOpenCodeZenSelectedModel(trimmed)
    }
  }

  const handleSearchKeySubmit = (e: FormEvent) => {
    e.preventDefault()
    const trimmed = searchKeyInput.trim()
    if (!trimmed) {
      setSearchKeyError('Please enter a valid search API key.')
      return
    }
    if (!trimmed.startsWith('tvly-') && trimmed.length < 8) {
      setSearchKeyError('Tavily API keys typically begin with "tvly-".')
      return
    }
    setSearchApiKey(trimmed)
    setSearchKeyInput('')
    setShowSearchKeyForm(false)
    setSearchKeyError(null)
  }

  const startCreateProvider = () => {
    setEditingProfileId(null)
    setProviderForm(EMPTY_FORM)
    setProviderFormError(null)
    setShowProviderForm(true)
  }

  const startEditProvider = (profile: ProviderProfile) => {
    setEditingProfileId(profile.id)
    setProviderForm({
      name: profile.name,
      apiKey: profile.apiKey ?? '',
      modelId: profile.modelId ?? '',
      baseUrl: profile.baseUrl ?? '',
      responseFormat: profile.responseFormat,
      messagesFormat: profile.messagesFormat,
    })
    setProviderFormError(null)
    setShowProviderForm(true)
  }

  const handleProviderSubmit = (e: FormEvent) => {
    e.preventDefault()
    const name = providerForm.name.trim()
    const apiKey = providerForm.apiKey.trim()
    const modelId = providerForm.modelId.trim()
    const baseUrl = providerForm.baseUrl.trim()

    if (!name) {
      setProviderFormError('Please enter a provider name.')
      return
    }
    if (!/^https?:\/\/.+/i.test(baseUrl)) {
      setProviderFormError('Please enter a valid base URL (https://…).')
      return
    }
    if (!apiKey) {
      setProviderFormError('Please enter an API key for this provider.')
      return
    }

    const profile: ProviderProfile = {
      id: editingProfileId ?? `profile-${newProfileId()}`,
      name,
      baseUrl,
      apiKey,
      ...(modelId ? { modelId } : {}),
      chatCompletionFormat: 'openai-chat-completions',
      responseFormat: providerForm.responseFormat,
      messagesFormat: providerForm.messagesFormat,
    }
    upsertProfile(profile)
    if (editingProfileId === null) {
      setActiveProviderId(profile.id)
    }
    setShowProviderForm(false)
    setEditingProfileId(null)
    setProviderForm(EMPTY_FORM)
    setProviderFormError(null)
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        size="xl"
        className="font-inter flex h-[min(48rem,calc(100dvh-2rem))] max-h-[calc(100dvh-2rem)] flex-col overflow-hidden p-0 sm:flex-row"
      >
        <aside className="hidden w-56 shrink-0 flex-col border-r bg-muted/30 p-4 sm:flex">
          <DialogHeader className="mb-6 px-2">
            <h2 className="text-lg font-semibold">
              Workspace Settings
            </h2>
            <DialogDescription>
              Manage providers, models, and preferences.
            </DialogDescription>
          </DialogHeader>
          <nav aria-label="Settings sections" className="space-y-1">
            {SETTINGS_CATEGORIES.map(({ id, label, icon: Icon }) => (
              <Button
                key={id}
                type="button"
                variant="ghost"
                active={activeCategory === id}
                aria-current={activeCategory === id ? 'page' : undefined}
                onClick={() => setActiveCategory(id)}
                leadingIcon={Icon}
                className="w-full justify-start gap-2.5 px-3 text-left"
              >
                {label}
              </Button>
            ))}
          </nav>
        </aside>

        <div className="flex min-h-0 min-w-0 flex-1 flex-col">
          <header className="flex shrink-0 flex-col gap-3 border-b px-5 py-4 pr-14 sm:px-6 sm:pr-14">
            <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
              <DialogHeader className="min-w-0">
                <DialogTitle className="text-base font-semibold">
                  {SETTINGS_CATEGORIES.find(({ id }) => id === activeCategory)?.label}
                </DialogTitle>
                <DialogDescription>
                  {SETTINGS_CATEGORIES.find(({ id }) => id === activeCategory)?.description}
                </DialogDescription>
              </DialogHeader>
              <label className="flex w-full flex-col gap-1 text-[11px] text-muted-foreground sm:hidden">
                Section
                <select
                  aria-label="Settings section"
                  value={activeCategory}
                  onChange={(event) =>
                    setActiveCategory(event.target.value as SettingsCategory)
                  }
                  className="h-9 w-full rounded-md border bg-background px-2 text-xs text-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
                >
                  {SETTINGS_CATEGORIES.map(({ id, label }) => (
                    <option key={id} value={id}>
                      {label}
                    </option>
                  ))}
                </select>
              </label>
            </div>
          </header>

          <div
            key={activeCategory}
            role="region"
            aria-label={`${activeCategory} settings`}
            tabIndex={0}
            className="min-h-0 flex-1 space-y-4 overflow-y-auto p-4 focus-visible:ring-1 focus-visible:ring-inset focus-visible:ring-ring sm:p-6"
          >
            {activeCategory === 'providers' && (
              <div className="space-y-4">
            {/* Active Provider Section */}
            <SettingsSection
              icon={Server}
              title="Active Provider"
              description="Choose which LLM provider serves engine runs. Server default uses the operator-configured environment (MODAL_* or FLEET_AGENT_LLM_*)."
            >
              <CardGroup
                columns={Math.min(3, profiles.length + 1)}
                separated
                border="outlined"
                className="w-full"
              >
                <Card
                  onClick={() => setActiveProviderId(SERVER_DEFAULT_ID)}
                  selected={activeProviderId === SERVER_DEFAULT_ID}
                  label="Server default"
                  className="cursor-pointer"
                >
                  <CardHeader className="p-3">
                    <div className="flex items-center justify-between gap-2">
                      <div className="flex items-center gap-2 min-w-0">
                        <CardMedia icon={Server} className="mb-0" />
                        <div className="min-w-0">
                          <CardTitle className="text-xs font-semibold truncate">
                            Server default
                          </CardTitle>
                          <CardDescription className="text-[10px] text-muted-foreground truncate">
                            Environment default
                          </CardDescription>
                        </div>
                      </div>
                      {activeProviderId === SERVER_DEFAULT_ID && (
                        <Check className="size-3.5 shrink-0 text-primary" />
                      )}
                    </div>
                  </CardHeader>
                </Card>
                {profiles.map((profile) => {
                  const isSelected = activeProviderId === profile.id
                  const ProviderIcon =
                    profile.id === OPENROUTER_PROFILE_ID
                      ? Globe
                      : profile.id === OPENCODE_ZEN_PROFILE_ID
                        ? Cpu
                        : Server
                  return (
                    <Card
                      key={profile.id}
                      onClick={() => setActiveProviderId(profile.id)}
                      selected={isSelected}
                      label={profile.name}
                      className="cursor-pointer"
                    >
                      <CardHeader className="p-3">
                        <div className="flex items-center justify-between gap-2">
                          <div className="flex items-center gap-2 min-w-0">
                            <CardMedia icon={ProviderIcon} className="mb-0" />
                            <div className="min-w-0">
                              <CardTitle className="text-xs font-semibold truncate">
                                {profile.name}
                              </CardTitle>
                              <CardDescription className="text-[10px] text-muted-foreground truncate font-mono">
                                {profile.modelId || 'default model'}
                              </CardDescription>
                            </div>
                          </div>
                          {isSelected && (
                            <Check className="size-3.5 shrink-0 text-primary" />
                          )}
                        </div>
                      </CardHeader>
                    </Card>
                  )
                })}
              </CardGroup>
            </SettingsSection>

            {/* Auth Section */}
            <SettingsSection
              icon={Key}
              title="OpenRouter Authentication"
              description="Sign in directly via OAuth PKCE to connect your OpenRouter account."
              action={
                isAuthenticated ? (
                  <Badge variant="outline" className="gap-1 px-2 py-0.5 text-[11px] border-success/30 bg-success/10 text-success">
                    <CircleDot className="size-2 fill-success text-success" />
                    Connected
                  </Badge>
                ) : (
                  <Badge variant="outline" className="gap-1 px-2 py-0.5 text-[11px] border-warning/30 bg-warning/10 text-warning">
                    Disconnected
                  </Badge>
                )
              }
            >

              {error && (
                <div className="flex items-center justify-between rounded-lg bg-destructive/10 px-3 py-2 text-xs text-destructive">
                  <span>{error}</span>
                  <Button
                    variant="ghost"
                    size="icon-xs"
                    onClick={clearError}
                    aria-label="Dismiss error"
                  >
                    <X className="size-3" />
                  </Button>
                </div>
              )}

              {isAuthenticated ? (
                <div className="space-y-3 pt-1">
                  <div className="flex items-center justify-between rounded-lg bg-muted/60 p-3 text-xs">
                    <div className="space-y-0.5">
                      <span className="text-muted-foreground text-[11px]">Active API Key:</span>
                      <div className="font-mono text-foreground font-medium">
                        {maskApiKey(apiKey)}
                      </div>
                    </div>
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={signOut}
                      className="gap-1.5 text-xs text-destructive hover:bg-destructive/10 hover:text-destructive"
                    >
                      <LogOut className="size-3.5" />
                      Disconnect
                    </Button>
                  </div>

                  {/* App Attribution Notice */}
                  <Card className="border border-success/20 bg-success/5">
                    <CardHeader className="p-3">
                      <div className="flex items-start gap-2">
                        <ShieldCheck className="size-4 shrink-0 text-success mt-0.5" />
                        <div className="space-y-0.5">
                          <div className="font-medium text-foreground text-xs">
                            App Attribution Configured
                          </div>
                          <CardDescription className="text-[11px] text-muted-foreground">
                            Your requests include official app attribution (<code className="font-mono text-success">Fleet Agent</code>) and HTTP referer verification for OpenRouter stats and rankings.
                          </CardDescription>
                        </div>
                      </div>
                    </CardHeader>
                  </Card>
                </div>
              ) : (
                <div className="space-y-3 pt-1">
                  <div className="flex flex-col sm:flex-row sm:items-center gap-3">
                    <OpenRouterButton variant="cta" size="default" className="w-full sm:w-auto">
                      Sign in with OpenRouter
                    </OpenRouterButton>
                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={() => setShowManualKeyForm((prev) => !prev)}
                      className="text-xs text-muted-foreground hover:text-foreground"
                    >
                      {showManualKeyForm ? 'Cancel Manual Key' : 'Or paste API key manually'}
                    </Button>
                  </div>

                  {showManualKeyForm && (
                    <form onSubmit={handleManualKeySubmit} className="space-y-2 pt-2 border-t">
                      <label htmlFor="manual-openrouter-key" className="text-xs font-medium text-foreground">
                        Manual OpenRouter API Key
                      </label>
                      <div className="flex gap-2">
                        <Input
                          id="manual-openrouter-key"
                          type="password"
                          placeholder="sk-or-v1-..."
                          value={manualKeyInput}
                          onChange={(e) => setManualKeyInput(e.target.value)}
                          className="text-xs font-mono"
                        />
                        <Button type="submit" size="sm" disabled={!manualKeyInput.trim()}>
                          Save Key
                        </Button>
                      </div>
                      {manualKeyError && (
                        <p className="text-[11px] text-destructive">{manualKeyError}</p>
                      )}
                    </form>
                  )}
                </div>
              )}
            </SettingsSection>

            {/* OpenCode Zen Authentication */}
            <SettingsSection
              icon={Key}
              title="OpenCode Zen Authentication"
              description={`Paste an OpenCode Zen API key to route engine runs through ${OPENCODE_ZEN_BASE_URL}.`}
              action={
                openCodeZenAuthenticated ? (
                  <Badge variant="outline" className="gap-1 px-2 py-0.5 text-[11px] border-success/30 bg-success/10 text-success">
                    <CircleDot className="size-2 fill-success text-success" />
                    Connected
                  </Badge>
                ) : (
                  <Badge variant="outline" className="gap-1 px-2 py-0.5 text-[11px] border-warning/30 bg-warning/10 text-warning">
                    Disconnected
                  </Badge>
                )
              }
            >
              {openCodeZenAuthenticated ? (
                <div className="space-y-3 pt-1">
                  <div className="flex items-center justify-between rounded-lg bg-muted/60 p-3 text-xs">
                    <div className="space-y-0.5">
                      <span className="text-muted-foreground text-[11px]">Active API Key:</span>
                      <div className="font-mono text-foreground font-medium">
                        {maskApiKey(openCodeZenApiKey)}
                      </div>
                    </div>
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={signOutOpenCodeZen}
                      className="gap-1.5 text-xs text-destructive hover:bg-destructive/10 hover:text-destructive"
                    >
                      <LogOut className="size-3.5" />
                      Disconnect
                    </Button>
                  </div>
                </div>
              ) : (
                <div className="space-y-3 pt-1">
                  <div className="flex flex-col sm:flex-row sm:items-center gap-3">
                    <Button
                      variant="default"
                      size="default"
                      onClick={() => setShowOpenCodeZenKeyForm((prev) => !prev)}
                      className="w-full sm:w-auto"
                    >
                      {showOpenCodeZenKeyForm ? 'Cancel' : 'Add OpenCode Zen API Key'}
                    </Button>
                    <span className="text-[11px] text-muted-foreground">
                      Keys are stored in this browser only and never reach the Fleet API.
                    </span>
                  </div>

                  {showOpenCodeZenKeyForm && (
                    <form onSubmit={handleOpenCodeZenKeySubmit} className="space-y-2 pt-2 border-t">
                      <label
                        htmlFor="manual-opencode-zen-key"
                        className="text-xs font-medium text-foreground"
                      >
                        OpenCode Zen API Key
                      </label>
                      <div className="flex gap-2">
                        <Input
                          id="manual-opencode-zen-key"
                          type="password"
                          placeholder="zen-..."
                          value={openCodeZenKeyInput}
                          onChange={(e) => setOpenCodeZenKeyInput(e.target.value)}
                          className="text-xs font-mono"
                        />
                        <Button type="submit" size="sm" disabled={!openCodeZenKeyInput.trim()}>
                          Save Key
                        </Button>
                      </div>
                      {openCodeZenKeyError && (
                        <p className="text-[11px] text-destructive">{openCodeZenKeyError}</p>
                      )}
                    </form>
                  )}
                </div>
              )}
            </SettingsSection>

            {/* Custom Providers Section */}
            <SettingsSection
              icon={Plus}
              title="Custom Providers"
              description="Add any OpenAI-compatible provider: your key stays in this browser and is sent only to the agent endpoint."
              action={
                <Button
                  variant="outline"
                  size="sm"
                  onClick={showProviderForm ? () => setShowProviderForm(false) : startCreateProvider}
                  className="shrink-0 text-xs gap-1.5"
                >
                  {showProviderForm ? (
                    <X className="size-3.5" />
                  ) : (
                    <Plus className="size-3.5" />
                  )}
                  {showProviderForm ? 'Cancel' : 'Add Provider'}
                </Button>
              }
            >
              {customProfiles.length === 0 && !showProviderForm && (
                <p className="text-[11px] text-muted-foreground">
                  No custom providers yet. Add one to route engine runs through a
                  different API key, model, or gateway.
                </p>
              )}

              {customProfiles.length > 0 && (
                <CardGroup separated border="outlined" className="w-full">
                  {customProfiles.map((profile) => (
                    <Card
                      key={profile.id}
                      className="border border-border/60 bg-muted/30"
                    >
                      <CardHeader className="p-3">
                        <div className="flex items-start justify-between gap-2">
                          <div className="min-w-0 space-y-0.5">
                            <div className="flex items-center gap-2">
                              <CardTitle className="text-xs font-semibold">
                                {profile.name}
                              </CardTitle>
                              {activeProviderId === profile.id && (
                                <Badge
                                  variant="outline"
                                  className="px-2 py-0 text-[10px] border-success/30 bg-success/10 text-success"
                                >
                                  Active
                                </Badge>
                              )}
                            </div>
                            <CardDescription className="font-mono text-[11px] truncate">
                              {profile.modelId || 'server default model'}
                            </CardDescription>
                            <div className="font-mono text-[11px] text-muted-foreground truncate">
                              {profile.baseUrl}
                            </div>
                            <div className="font-mono text-[11px] text-muted-foreground">
                              Key: {maskApiKey(profile.apiKey)}
                            </div>
                          </div>
                          <CardAction className="flex shrink-0 gap-1">
                            <Button
                              variant="ghost"
                              size="icon-xs"
                              onClick={() => startEditProvider(profile)}
                              aria-label={`Edit ${profile.name}`}
                            >
                              <Pencil className="size-3" />
                            </Button>
                            <Button
                              variant="ghost"
                              size="icon-xs"
                              onClick={() => removeProfile(profile.id)}
                              className="text-destructive hover:bg-destructive/10 hover:text-destructive"
                              aria-label={`Delete ${profile.name}`}
                            >
                              <Trash2 className="size-3" />
                            </Button>
                          </CardAction>
                        </div>
                      </CardHeader>
                    </Card>
                  ))}
                </CardGroup>
              )}

              {showProviderForm && (
                <form onSubmit={handleProviderSubmit} className="space-y-3 border-t pt-3">
                  <div className="space-y-1.5">
                    <label htmlFor="provider-name" className="text-xs font-medium text-foreground">
                      Provider Name
                    </label>
                    <Input
                      id="provider-name"
                      placeholder="Modal Gateway"
                      value={providerForm.name}
                      onChange={(e) =>
                        setProviderForm((prev) => ({ ...prev, name: e.target.value }))
                      }
                      className="text-xs"
                    />
                  </div>

                  <div className="space-y-1.5">
                    <label htmlFor="provider-base-url" className="text-xs font-medium text-foreground">
                      Base URL (OpenAI-compatible)
                    </label>
                    <Input
                      id="provider-base-url"
                      placeholder="https://fleet-proxy.modal.run/v1"
                      value={providerForm.baseUrl}
                      onChange={(e) =>
                        setProviderForm((prev) => ({ ...prev, baseUrl: e.target.value }))
                      }
                      className="text-xs font-mono"
                    />
                  </div>

                  <div className="space-y-1.5">
                    <label htmlFor="provider-api-key" className="text-xs font-medium text-foreground">
                      API Key
                    </label>
                    <Input
                      id="provider-api-key"
                      type="password"
                      placeholder="sk-..."
                      value={providerForm.apiKey}
                      onChange={(e) =>
                        setProviderForm((prev) => ({ ...prev, apiKey: e.target.value }))
                      }
                      className="text-xs font-mono"
                    />
                  </div>

                  <div className="space-y-1.5">
                    <label htmlFor="provider-model-id" className="text-xs font-medium text-foreground">
                      Model ID (as your gateway names it, e.g. openai/gpt-4o-mini)
                    </label>
                    <Input
                      id="provider-model-id"
                      placeholder="openai/gpt-4o-mini"
                      value={providerForm.modelId}
                      onChange={(e) =>
                        setProviderForm((prev) => ({ ...prev, modelId: e.target.value }))
                      }
                      className="text-xs font-mono"
                    />
                  </div>

                  <div className="space-y-1.5">
                    <span className="text-xs font-medium text-muted-foreground">
                      Chat completion format:
                    </span>
                    <SegmentedOptions
                      ariaLabel="Chat completion format"
                      value="openai-chat-completions"
                      options={[{ value: 'openai-chat-completions', label: 'OpenAI chat completions' }]}
                      onChange={() => undefined}
                    />
                    <p className="text-[11px] text-muted-foreground">
                      The engine's stable wire format; forward-compatible with DSPy's
                      typed LMRequest/LMResponse API.
                    </p>
                  </div>

                  <div className="space-y-1.5">
                    <span className="text-xs font-medium text-muted-foreground">
                      Response format:
                    </span>
                    <SegmentedOptions
                      ariaLabel="Response format"
                      value={providerForm.responseFormat}
                      options={RESPONSE_FORMAT_OPTIONS}
                      onChange={(responseFormat) =>
                        setProviderForm((prev) => ({ ...prev, responseFormat }))
                      }
                    />
                    <p className="text-[11px] text-muted-foreground flex items-center gap-1.5">
                      <Cpu className="size-3" />
                      Native function calling uses provider tool calls; JSON tool
                      calls prompt tools as JSON for gateways without native support.
                    </p>
                  </div>

                  <div className="space-y-1.5">
                    <span className="text-xs font-medium text-muted-foreground">
                      Messages format:
                    </span>
                    <SegmentedOptions
                      ariaLabel="Messages format"
                      value={providerForm.messagesFormat}
                      options={MESSAGES_FORMAT_OPTIONS}
                      onChange={(messagesFormat) =>
                        setProviderForm((prev) => ({ ...prev, messagesFormat }))
                      }
                    />
                    <p className="text-[11px] text-muted-foreground flex items-center gap-1.5">
                      <MessageSquare className="size-3" />
                      System role sends system messages as-is; developer role uses the
                      newer developer role for OpenAI-style APIs.
                    </p>
                  </div>

                  {providerFormError && (
                    <p className="text-[11px] text-destructive">{providerFormError}</p>
                  )}

                  <div className="flex justify-end gap-2">
                    <Button
                      type="button"
                      variant="ghost"
                      size="sm"
                      onClick={() => {
                        setShowProviderForm(false)
                        setEditingProfileId(null)
                        setProviderForm(EMPTY_FORM)
                        setProviderFormError(null)
                      }}
                      className="text-xs"
                    >
                      Cancel
                    </Button>
                    <Button type="submit" size="sm" className="text-xs">
                      Save Provider
                    </Button>
                  </div>
                </form>
              )}
            </SettingsSection>

              </div>
            )}

            {activeCategory === 'models' && (
              activeProviderId === OPENCODE_ZEN_PROFILE_ID ? (
              <SettingsSection
                icon={Cpu}
                title="Active LLM Model"
                description={`Select which model to route through your OpenCode Zen connection (${OPENCODE_ZEN_BASE_URL}).`}
                action={
                  <div className="flex shrink-0 items-center gap-2">
                    <span className="text-xs text-muted-foreground">
                      {openCodeZenCustomModelEnabled ? 'Active' : 'Disabled'}
                    </span>
                    <Switch
                      label="Toggle Custom OpenCode Zen Model"
                      checked={openCodeZenCustomModelEnabled}
                      onToggle={() =>
                        setOpenCodeZenCustomModelEnabled(!openCodeZenCustomModelEnabled)
                      }
                      hideLabel
                    />
                  </div>
                }
              >
                <div
                  className={
                    openCodeZenCustomModelEnabled
                      ? 'space-y-3 opacity-100'
                      : 'space-y-3 opacity-60'
                  }
                >
                  <ModelCardsRow
                    providerId={OPENCODE_ZEN_PROFILE_ID}
                    baseUrl={OPENCODE_ZEN_BASE_URL}
                    apiKey={openCodeZenApiKey}
                    selectedModel={openCodeZenSelectedModel}
                    onSelectModel={(modelId) => {
                      setOpenCodeZenCustomModelEnabled(true)
                      setOpenCodeZenSelectedModel(modelId)
                      setOpenCodeZenCustomModelInput(modelId)
                    }}
                  />

                  <form
                    onSubmit={handleOpenCodeZenCustomModelSubmit}
                    className="space-y-1.5 pt-1"
                  >
                    <label
                      htmlFor="custom-opencode-zen-model-id"
                      className="text-xs font-medium text-muted-foreground"
                    >
                      Custom Model Identifier:
                    </label>
                    <div className="flex gap-2">
                      <Input
                        id="custom-opencode-zen-model-id"
                        placeholder={DEFAULT_OPENCODE_ZEN_MODEL}
                        value={openCodeZenCustomModelInput}
                        onChange={(e) => setOpenCodeZenCustomModelInput(e.target.value)}
                        className="text-xs font-mono"
                      />
                      <Button
                        type="submit"
                        variant="secondary"
                        size="sm"
                        disabled={
                          !openCodeZenCustomModelInput.trim() ||
                          openCodeZenCustomModelInput === openCodeZenSelectedModel
                        }
                      >
                        Apply
                      </Button>
                    </div>
                  </form>

                  <div className="flex items-center gap-2 text-[11px] text-muted-foreground">
                    <Globe className="size-3" />
                    <span>Currently routed:</span>
                    <code className="font-mono text-foreground font-semibold">
                      {openCodeZenCustomModelEnabled
                        ? openCodeZenSelectedModel
                        : 'Default OpenCode Zen Model'}
                    </code>
                  </div>
                </div>
              </SettingsSection>
            ) : (
              <SettingsSection
                icon={Cpu}
                title="Active LLM Model"
                description="Select which model to route through your OpenRouter connection."
                action={
                  <div className="flex shrink-0 items-center gap-2">
                    <span className="text-xs text-muted-foreground">
                      {customModelEnabled ? 'Active' : 'Disabled'}
                    </span>
                    <Switch
                      label="Toggle Custom OpenRouter Model"
                      checked={customModelEnabled}
                      onToggle={() => setCustomModelEnabled(!customModelEnabled)}
                      hideLabel
                    />
                  </div>
                }
              >
                <div className={customModelEnabled ? 'space-y-3 opacity-100' : 'space-y-3 opacity-60'}>
                  <ModelCardsRow
                    providerId={OPENROUTER_PROFILE_ID}
                    baseUrl={OPENROUTER_BASE_URL}
                    apiKey={apiKey}
                    selectedModel={selectedModel}
                    onSelectModel={(modelId) => {
                      setCustomModelEnabled(true)
                      setSelectedModel(modelId)
                      setCustomModelInput(modelId)
                    }}
                  />

                  <form onSubmit={handleCustomModelSubmit} className="space-y-1.5 pt-1">
                    <label htmlFor="custom-model-id" className="text-xs font-medium text-muted-foreground">
                      Custom Model Identifier:
                    </label>
                    <div className="flex gap-2">
                      <Input
                        id="custom-model-id"
                        placeholder={DEFAULT_OPENROUTER_MODEL}
                        value={customModelInput}
                        onChange={(e) => setCustomModelInput(e.target.value)}
                        className="text-xs font-mono"
                      />
                      <Button
                        type="submit"
                        variant="secondary"
                        size="sm"
                        disabled={!customModelInput.trim() || customModelInput === selectedModel}
                      >
                        Apply
                      </Button>
                    </div>
                  </form>

                  <div className="flex items-center gap-2 text-[11px] text-muted-foreground">
                    <Globe className="size-3" />
                    <span>Currently routed:</span>
                    <code className="font-mono text-foreground font-semibold">
                      {customModelEnabled ? selectedModel : 'Default Server Model'}
                    </code>
                  </div>
                </div>
              </SettingsSection>
              )
            )}

            {activeCategory === 'search' && (
              <div className="space-y-4">
                <SettingsSection
                  icon={Search}
                  title="Search Provider"
                  description="Choose which web search engine powers agent research, web extraction, and real-time query tools."
                >
                  <CardGroup
                    columns={1}
                    separated
                    border="outlined"
                    className="w-full"
                  >
                    {Object.values(SEARCH_PROVIDERS).map((p) => {
                      const isSelected = searchProvider === p.id
                      return (
                        <Card
                          key={p.id}
                          onClick={() => setSearchProvider(p.id)}
                          selected={isSelected}
                          label={p.name}
                          className="cursor-pointer"
                        >
                          <CardHeader className="p-3">
                            <div className="flex items-start justify-between gap-3">
                              <div className="flex items-start gap-2.5 min-w-0">
                                <CardMedia icon={Search} className="mb-0 mt-0.5" />
                                <div className="min-w-0 space-y-1">
                                  <div className="flex items-center gap-2">
                                    <CardTitle className="text-xs font-semibold">
                                      {p.name}
                                    </CardTitle>
                                    <Badge
                                      variant="secondary"
                                      className="text-[10px] px-1.5 py-0 uppercase tracking-wider"
                                    >
                                      Default
                                    </Badge>
                                  </div>
                                  <CardDescription className="text-xs text-muted-foreground leading-relaxed">
                                    {p.description}
                                  </CardDescription>
                                  <div className="pt-0.5">
                                    <a
                                      href={p.website}
                                      target="_blank"
                                      rel="noopener noreferrer"
                                      onClick={(e) => e.stopPropagation()}
                                      className="inline-flex items-center gap-1 text-[11px] text-primary hover:underline"
                                    >
                                      Visit {p.website.replace('https://', '')}
                                      <ExternalLink className="size-3" />
                                    </a>
                                  </div>
                                </div>
                              </div>
                              {isSelected && (
                                <Check className="size-4 shrink-0 text-primary mt-1" />
                              )}
                            </div>
                          </CardHeader>
                        </Card>
                      )
                    })}
                  </CardGroup>
                </SettingsSection>

                <SettingsSection
                  icon={Key}
                  title="Tavily Search API Key"
                  description="Provide a Tavily search API key for agent research and browser search tools."
                  action={
                    isSearchConnected ? (
                      <Badge
                        variant="outline"
                        className="gap-1 px-2 py-0.5 text-[11px] border-success/30 bg-success/10 text-success"
                      >
                        <CircleDot className="size-2 fill-success text-success" />
                        Connected
                      </Badge>
                    ) : (
                      <Badge
                        variant="outline"
                        className="gap-1 px-2 py-0.5 text-[11px] border-warning/30 bg-warning/10 text-warning"
                      >
                        Disconnected
                      </Badge>
                    )
                  }
                >
                  {isSearchConnected && !showSearchKeyForm ? (
                    <div className="space-y-3 pt-1">
                      <div className="flex items-center justify-between rounded-lg bg-muted/60 p-3 text-xs">
                        <div className="space-y-0.5">
                          <span className="text-muted-foreground text-[11px]">
                            Configured API Key:
                          </span>
                          <div className="font-mono text-foreground font-medium flex items-center gap-2">
                            <span>
                              {showSearchSecret
                                ? searchApiKey
                                : maskSearchApiKey(searchApiKey)}
                            </span>
                            <Button
                              type="button"
                              variant="ghost"
                              size="icon-xs"
                              onClick={() => setShowSearchSecret((prev) => !prev)}
                              aria-label={
                                showSearchSecret ? 'Hide key' : 'Show key'
                              }
                            >
                              {showSearchSecret ? (
                                <EyeOff className="size-3" />
                              ) : (
                                <Eye className="size-3" />
                              )}
                            </Button>
                          </div>
                        </div>
                        <div className="flex items-center gap-2">
                          <Button
                            variant="ghost"
                            size="sm"
                            onClick={() => {
                              setSearchKeyInput('')
                              setShowSearchKeyForm(true)
                            }}
                            className="text-xs"
                          >
                            <Pencil className="size-3 mr-1" />
                            Change Key
                          </Button>
                          <Button
                            variant="outline"
                            size="sm"
                            onClick={clearSearchApiKey}
                            className="gap-1.5 text-xs text-destructive hover:bg-destructive/10 hover:text-destructive"
                          >
                            <LogOut className="size-3.5" />
                            Disconnect
                          </Button>
                        </div>
                      </div>
                    </div>
                  ) : (
                    <div className="space-y-3 pt-1">
                      {!showSearchKeyForm && (
                        <div className="flex flex-col sm:flex-row sm:items-center gap-3">
                          <Button
                            variant="default"
                            size="default"
                            onClick={() => setShowSearchKeyForm(true)}
                            className="w-full sm:w-auto"
                          >
                            <Plus className="size-3.5 mr-1.5" />
                            Add Tavily API Key
                          </Button>
                          <span className="text-[11px] text-muted-foreground">
                            Keys are stored in your browser and sent only when the agent performs search queries.
                          </span>
                        </div>
                      )}

                      {showSearchKeyForm && (
                        <form
                          onSubmit={handleSearchKeySubmit}
                          className="space-y-3 rounded-lg border bg-muted/20 p-3.5"
                        >
                          <div className="space-y-1.5">
                            <div className="flex items-center justify-between">
                              <label
                                htmlFor="search-api-key-input"
                                className="text-xs font-medium text-foreground"
                              >
                                Enter Tavily API Key
                              </label>
                              <a
                                href="https://app.tavily.com/home"
                                target="_blank"
                                rel="noopener noreferrer"
                                className="inline-flex items-center gap-1 text-[11px] text-primary hover:underline"
                              >
                                Get API key
                                <ExternalLink className="size-3" />
                              </a>
                            </div>
                            <div className="relative">
                              <Input
                                id="search-api-key-input"
                                type={showSearchSecret ? 'text' : 'password'}
                                placeholder="tvly-..."
                                value={searchKeyInput}
                                onChange={(e) => {
                                  setSearchKeyInput(e.target.value)
                                  if (searchKeyError) setSearchKeyError(null)
                                }}
                                className="text-xs font-mono pr-8"
                              />
                              <Button
                                type="button"
                                variant="ghost"
                                size="icon-xs"
                                onClick={() => setShowSearchSecret((prev) => !prev)}
                                className="absolute right-1.5 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground"
                                aria-label={
                                  showSearchSecret ? 'Hide key' : 'Show key'
                                }
                              >
                                {showSearchSecret ? (
                                  <EyeOff className="size-3.5" />
                                ) : (
                                  <Eye className="size-3.5" />
                                )}
                              </Button>
                            </div>
                            {searchKeyError && (
                              <p className="text-[11px] text-destructive">
                                {searchKeyError}
                              </p>
                            )}
                          </div>

                          <div className="flex justify-end gap-2 pt-1">
                            <Button
                              type="button"
                              variant="ghost"
                              size="sm"
                              onClick={() => {
                                setShowSearchKeyForm(false)
                                setSearchKeyInput('')
                                setSearchKeyError(null)
                              }}
                              className="text-xs"
                            >
                              Cancel
                            </Button>
                            <Button
                              type="submit"
                              size="sm"
                              disabled={!searchKeyInput.trim()}
                              className="text-xs"
                            >
                              Save Key
                            </Button>
                          </div>
                        </form>
                      )}
                    </div>
                  )}

                  <Card className="border border-border/60 bg-muted/20 mt-3">
                    <CardHeader className="p-3">
                      <div className="flex items-start gap-2.5">
                        <ShieldCheck className="size-4 shrink-0 text-primary mt-0.5" />
                        <div className="space-y-0.5">
                          <div className="font-medium text-foreground text-xs">
                            Client-Side Storage (BYOK)
                          </div>
                          <CardDescription className="text-[11px] text-muted-foreground leading-relaxed">
                            Your search API key is kept exclusively in this browser's local storage. It is forwarded to the backend via ephemeral <code className="font-mono text-foreground font-medium">X-Search-Key</code> request headers on agent execution calls and is never persisted in any database or telemetry log.
                          </CardDescription>
                        </div>
                      </div>
                    </CardHeader>
                  </Card>
                </SettingsSection>
              </div>
            )}

            {activeCategory === 'appearance' && (
              <div className="space-y-4">
                <SettingsSection
                  icon={Palette}
                  title="Interface Theme"
                  description="Select your preferred color theme for Fleet Agent."
                >
                  <CardGroup columns={3} separated border="outlined" className="pt-1">
                    <Card
                      onClick={() => setTheme('light')}
                      selected={theme === 'light'}
                      label="Light"
                      className="cursor-pointer"
                    >
                      <CardHeader className="p-3 flex flex-col items-center justify-center text-center gap-1.5">
                        <CardMedia icon={Sun} className="mb-0" />
                        <CardTitle className="text-xs font-medium">Light</CardTitle>
                      </CardHeader>
                    </Card>
                    <Card
                      onClick={() => setTheme('dark')}
                      selected={theme === 'dark'}
                      label="Dark"
                      className="cursor-pointer"
                    >
                      <CardHeader className="p-3 flex flex-col items-center justify-center text-center gap-1.5">
                        <CardMedia icon={Moon} className="mb-0" />
                        <CardTitle className="text-xs font-medium">Dark</CardTitle>
                      </CardHeader>
                    </Card>
                    <Card
                      onClick={() => setTheme('system')}
                      selected={theme === 'system'}
                      label="System"
                      className="cursor-pointer"
                    >
                      <CardHeader className="p-3 flex flex-col items-center justify-center text-center gap-1.5">
                        <CardMedia icon={Laptop} className="mb-0" />
                        <CardTitle className="text-xs font-medium">System</CardTitle>
                      </CardHeader>
                    </Card>
                  </CardGroup>
                </SettingsSection>
              </div>
            )}
          </div>
        </div>
      </DialogContent>
    </Dialog>
  )
}
