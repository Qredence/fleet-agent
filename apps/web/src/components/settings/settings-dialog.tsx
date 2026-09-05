import { useState, type FormEvent, type ReactNode } from 'react'
import {
  Check,
  CircleDot,
  Cpu,
  Globe,
  Key,
  Laptop,
  LogOut,
  MessageSquare,
  Moon,
  Palette,
  Pencil,
  Plus,
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
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Switch } from '@/components/ui/switch'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { useOpenRouterAuth } from '@/hooks/use-openrouter-auth'
import { useOpenCodeZenAuth } from '@/hooks/use-opencode-zen-auth'
import { useProviders } from '@/hooks/use-providers'
import {
  maskApiKey,
  POPULAR_OPENROUTER_MODELS,
  DEFAULT_OPENROUTER_MODEL,
} from '@/lib/openrouter-auth'
import {
  POPULAR_OPENCODE_ZEN_MODELS,
  DEFAULT_OPENCODE_ZEN_MODEL,
} from '@/lib/opencode-zen-auth'
import {
  OPENROUTER_PROFILE_ID,
  OPENCODE_ZEN_PROFILE_ID,
  OPENCODE_ZEN_BASE_URL,
  SERVER_DEFAULT_ID,
  type MessagesFormat,
  type ProviderProfile,
  type ResponseFormat,
} from '@/lib/providers'
import { useWorkspaceStore } from '@/state/workspace-store'
import { useShape } from '@/lib/shape-context'
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

const EMPTY_FORM = {
  name: '',
  apiKey: '',
  modelId: '',
  baseUrl: '',
  responseFormat: 'native_function_calling' as ResponseFormat,
  messagesFormat: 'system_role' as MessagesFormat,
}

/**
 * One settings section: a token-tinted icon chip, a title with its helper
 * description, an optional trailing control, and the section body. Shared by
 * every tab section so spacing, heading level, and surface stay identical.
 */
function SettingsSection({
  icon: Icon,
  title,
  description,
  action,
  children,
}: {
  icon: LucideIcon
  title: string
  description: string
  action?: ReactNode
  children: ReactNode
}) {
  // The section is a Card-level surface: it takes the shape ladder's
  // `container` step (24px in pill mode), and its icon chip the `bg`/element
  // step — the same treatment Card gives its media tile.
  const shape = useShape()
  return (
    <section className={cn('space-y-3 border bg-card/60 p-4', shape.container)}>
      <div className="flex items-start justify-between gap-3">
        <div className="flex min-w-0 items-center gap-2">
          <div
            className={cn(
              'flex size-7 shrink-0 items-center justify-center bg-primary/10 text-primary',
              shape.bg,
            )}
          >
            <Icon className="size-4" />
          </div>
          <div className="min-w-0">
            <h3 className="text-sm font-semibold">{title}</h3>
            <p className="text-[11px] leading-4 text-muted-foreground">
              {description}
            </p>
          </div>
        </div>
        {action}
      </div>
      {children}
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
      <DialogContent className="flex max-h-[calc(100dvh-3rem)] w-full max-w-xl flex-col gap-4 overflow-hidden p-6 sm:max-w-2xl">
        <DialogHeader>
          <DialogTitle className="text-lg font-semibold flex items-center gap-2">
            Workspace Settings
          </DialogTitle>
          <DialogDescription className="text-xs text-muted-foreground">
            Manage your LLM providers, API keys, models, and appearance preferences.
          </DialogDescription>
        </DialogHeader>

        <Tabs
          defaultValue="providers"
          className="mt-2 flex w-full min-h-0 flex-1 flex-col gap-0"
        >
          <TabsList className="grid w-full shrink-0 grid-cols-2">
            <TabsTrigger value="providers" className="gap-2 text-xs">
              <Server className="size-3.5" />
              Providers & Models
            </TabsTrigger>
            <TabsTrigger value="appearance" className="gap-2 text-xs">
              <Palette className="size-3.5" />
              Appearance
            </TabsTrigger>
          </TabsList>

          {/* PROVIDER & MODEL CONFIGURATION */}
          <TabsContent
            value="providers"
            className="min-h-0 flex-1 space-y-4 overflow-y-auto pt-3"
          >
            {/* Active Provider Section */}
            <SettingsSection
              icon={Server}
              title="Active Provider"
              description="Choose which LLM provider serves engine runs. Server default uses the operator-configured environment (MODAL_* or FLEET_AGENT_LLM_*)."
            >
              <div className="flex flex-wrap gap-1.5" role="group" aria-label="Active provider">
                <Button
                  variant={activeProviderId === SERVER_DEFAULT_ID ? 'default' : 'outline'}
                  size="sm"
                  onClick={() => setActiveProviderId(SERVER_DEFAULT_ID)}
                  className="h-7 text-xs gap-1.5"
                >
                  {activeProviderId === SERVER_DEFAULT_ID && <Check className="size-3" />}
                  Server default
                </Button>
                {profiles.map((profile) => (
                  <Button
                    key={profile.id}
                    variant={activeProviderId === profile.id ? 'default' : 'outline'}
                    size="sm"
                    onClick={() => setActiveProviderId(profile.id)}
                    className="h-7 text-xs gap-1.5"
                  >
                    {activeProviderId === profile.id && <Check className="size-3" />}
                    {profile.name}
                  </Button>
                ))}
              </div>
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
                  <div className="flex items-start gap-2 rounded-lg border border-success/20 bg-success/5 p-3 text-xs">
                    <ShieldCheck className="size-4 shrink-0 text-success mt-0.5" />
                    <div className="space-y-0.5">
                      <div className="font-medium text-foreground">App Attribution Configured</div>
                      <p className="text-[11px] text-muted-foreground">
                        Your requests include official app attribution (<code className="font-mono text-success">Fleet Agent</code>) and HTTP referer verification for OpenRouter stats and rankings.
                      </p>
                    </div>
                  </div>
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

            {/* Model Selection Section */}
            {activeProviderId === OPENCODE_ZEN_PROFILE_ID ? (
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
                    />
                  </div>
                }
              >
                <div
                  className={
                    openCodeZenCustomModelEnabled
                      ? 'space-y-3 opacity-100'
                      : 'space-y-3 opacity-60 pointer-events-none'
                  }
                >
                  <div className="space-y-1.5">
                    <label className="text-xs font-medium text-muted-foreground">
                      Popular OpenCode Zen Models:
                    </label>
                    <div className="flex flex-wrap gap-1.5">
                      {POPULAR_OPENCODE_ZEN_MODELS.map((model) => {
                        const isSelected = openCodeZenSelectedModel === model.id
                        return (
                          <Button
                            key={model.id}
                            variant={isSelected ? 'default' : 'outline'}
                            size="sm"
                            onClick={() => {
                              setOpenCodeZenSelectedModel(model.id)
                              setOpenCodeZenCustomModelInput(model.id)
                            }}
                            className="h-7 text-xs gap-1.5"
                          >
                            {isSelected && <Check className="size-3" />}
                            {model.label}
                          </Button>
                        )
                      })}
                    </div>
                  </div>

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
                    />
                  </div>
                }
              >

                <div className={customModelEnabled ? 'space-y-3 opacity-100' : 'space-y-3 opacity-60 pointer-events-none'}>
                  <div className="space-y-1.5">
                    <label className="text-xs font-medium text-muted-foreground">
                      Popular Models:
                    </label>
                    <div className="flex flex-wrap gap-1.5">
                      {POPULAR_OPENROUTER_MODELS.map((model) => {
                        const isSelected = selectedModel === model.id
                        return (
                          <Button
                            key={model.id}
                            variant={isSelected ? 'default' : 'outline'}
                            size="sm"
                            onClick={() => {
                              setSelectedModel(model.id)
                              setCustomModelInput(model.id)
                            }}
                            className="h-7 text-xs gap-1.5"
                          >
                            {isSelected && <Check className="size-3" />}
                            {model.label}
                          </Button>
                        )
                      })}
                    </div>
                  </div>

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
            )}

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

              {customProfiles.map((profile) => (
                <div
                  key={profile.id}
                  className="rounded-lg border bg-muted/30 p-3 space-y-2"
                >
                  <div className="flex items-start justify-between gap-2">
                    <div className="min-w-0 space-y-0.5">
                      <div className="flex items-center gap-2">
                        <span className="text-xs font-semibold text-foreground">
                          {profile.name}
                        </span>
                        {activeProviderId === profile.id && (
                          <Badge variant="outline" className="px-2 py-0 text-[10px] border-success/30 bg-success/10 text-success">
                            Active
                          </Badge>
                        )}
                      </div>
                      <div className="font-mono text-[11px] text-muted-foreground truncate">
                        {profile.modelId || 'server default model'}
                      </div>
                      <div className="font-mono text-[11px] text-muted-foreground truncate">
                        {profile.baseUrl}
                      </div>
                      <div className="font-mono text-[11px] text-muted-foreground">
                        Key: {maskApiKey(profile.apiKey)}
                      </div>
                    </div>
                    <div className="flex shrink-0 gap-1">
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
                    </div>
                  </div>
                </div>
              ))}

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
          </TabsContent>

          {/* APPEARANCE CONFIGURATION */}
          <TabsContent
            value="appearance"
            className="min-h-0 flex-1 space-y-4 overflow-y-auto pt-3"
          >
            <SettingsSection
              icon={Palette}
              title="Interface Theme"
              description="Select your preferred color theme for Fleet Agent."
            >
              <div className="grid grid-cols-3 gap-2 pt-1">
                <Button
                  variant={theme === 'light' ? 'default' : 'outline'}
                  size="sm"
                  onClick={() => setTheme('light')}
                  className="flex items-center justify-center gap-2 h-10"
                >
                  <Sun className="size-4" />
                  <span>Light</span>
                </Button>
                <Button
                  variant={theme === 'dark' ? 'default' : 'outline'}
                  size="sm"
                  onClick={() => setTheme('dark')}
                  className="flex items-center justify-center gap-2 h-10"
                >
                  <Moon className="size-4" />
                  <span>Dark</span>
                </Button>
                <Button
                  variant={theme === 'system' ? 'default' : 'outline'}
                  size="sm"
                  onClick={() => setTheme('system')}
                  className="flex items-center justify-center gap-2 h-10"
                >
                  <Laptop className="size-4" />
                  <span>System</span>
                </Button>
              </div>
            </SettingsSection>
          </TabsContent>
        </Tabs>
      </DialogContent>
    </Dialog>
  )
}
