"use client";

import {
  createContext,
  useContext,
  useMemo,
  useState,
  type ComponentProps,
  type FC,
  type PropsWithChildren,
} from "react";
import {
  AtSignIcon,
  BrainIcon,
  CheckIcon,
  ChevronDownIcon,
  CircleAlertIcon,
  FileTextIcon,
  GlobeIcon,
  LockKeyholeIcon,
  SparklesIcon,
  WrenchIcon,
  ZapIcon,
  type LucideIcon,
} from "lucide-react";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuGroup,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { useProviders } from "@/hooks/use-providers";
import { useOpenCodeZenAuth } from "@/hooks/use-opencode-zen-auth";
import { useOpenRouterAuth } from "@/hooks/use-openrouter-auth";
import {
  POPULAR_OPENCODE_ZEN_MODELS,
} from "@/lib/opencode-zen-auth";
import { POPULAR_OPENROUTER_MODELS } from "@/lib/openrouter-auth";
import {
  OPENCODE_ZEN_PROFILE_ID,
  OPENROUTER_PROFILE_ID,
  SERVER_DEFAULT_ID,
} from "@/lib/providers";
import {
  ComposerPrimitive,
  type Unstable_DirectiveFormatter,
  type Unstable_Mention,
  type Unstable_TriggerItem,
  unstable_useMentionAdapter,
  unstable_useSlashCommandAdapter,
  useAui,
  useAuiState,
} from "@assistant-ui/react";
import { cn } from "@/lib/utils";
import { clamp, pct } from "@/lib/range";
import { surfaceClasses } from "@/lib/surface-classes";
import { ghostButton, mono } from "@/lib/surfaces";

export type EffortLevel = "Low" | "Medium" | "High";
export type ComposerSpeed = "Fast" | "Standard";
export type ComposerAccess = "Full access" | "Read-only";

export interface ComposerPreferences {
  effort: EffortLevel;
  speed: ComposerSpeed;
  access: ComposerAccess;
}

export interface ComposerWorkspaceContext {
  agentLabel: string;
  projectLabel: string;
  threadLabel: string;
  projectId?: string;
  threadId?: string;
}

export interface SlashCommand {
  name: string;
  description: string;
  icon: LucideIcon;
}

export const SLASH_COMMANDS: SlashCommand[] = [
  {
    name: "search",
    description: "Add a /search prompt helper",
    icon: GlobeIcon,
  },
  {
    name: "report",
    description: "Add a /report prompt helper",
    icon: FileTextIcon,
  },
  {
    name: "optimize",
    description: "Add an /optimize prompt helper",
    icon: SparklesIcon,
  },
  {
    name: "tools",
    description: "Add a /tools prompt helper",
    icon: WrenchIcon,
  },
];

const DEFAULT_PREFERENCES: ComposerPreferences = {
  effort: "High",
  speed: "Fast",
  access: "Full access",
};

interface ComposerPreferencesContextValue {
  preferences: ComposerPreferences;
  setEffort: (effort: EffortLevel) => void;
  setSpeed: (speed: ComposerSpeed) => void;
  setAccess: (access: ComposerAccess) => void;
}

const ComposerPreferencesContext =
  createContext<ComposerPreferencesContextValue | null>(null);

/**
 * Provides composer preferences and their update functions to descendant components.
 *
 * @param children - The components that can access the composer preferences context
 */
export function ComposerPreferencesProvider({
  children,
}: PropsWithChildren) {
  const [effort, setEffort] = useState<EffortLevel>(DEFAULT_PREFERENCES.effort);
  const [speed, setSpeed] = useState<ComposerSpeed>(DEFAULT_PREFERENCES.speed);
  const [access, setAccess] = useState<ComposerAccess>(DEFAULT_PREFERENCES.access);

  const value = useMemo<ComposerPreferencesContextValue>(
    () => ({
      preferences: { effort, speed, access },
      setEffort,
      setSpeed,
      setAccess,
    }),
    [effort, speed, access],
  );

  return (
    <ComposerPreferencesContext.Provider value={value}>
      {children}
    </ComposerPreferencesContext.Provider>
  );
}

/**
 * Provides access to composer preferences and their setters.
 *
 * @returns The current composer preferences context
 * @throws Error if used outside a `ComposerPreferencesProvider`
 */
function useComposerPreferences(): ComposerPreferencesContextValue {
  const value = useContext(ComposerPreferencesContext);
  if (!value) {
    throw new Error(
      "Composer controls must be rendered inside ComposerPreferencesProvider",
    );
  }
  return value;
}

interface ComposerUsage {
  system: number;
  tools: number;
  messages: number;
  total: number;
  estimated?: boolean;
  description?: string;
}

/** Visual model trigger kept next to the runtime picker that owns it. */
export function ComposerModelTrigger({
  model,
  open,
  unconfigured = false,
  className,
  ...props
}: Omit<ComponentProps<"button">, "children"> & {
  model: string;
  open: boolean;
  unconfigured?: boolean;
}) {
  return (
    <button
      type="button"
      aria-expanded={open}
      data-slot="composer-model-trigger"
      data-unconfigured={unconfigured || undefined}
      className={cn(
        "text-foreground/55 hover:bg-foreground/[0.06] hover:text-foreground/90 dark:hover:bg-foreground/[0.09] flex h-8 items-center gap-1.5 rounded-full px-3 text-[12.5px] transition-colors motion-reduce:transition-none",
        className,
      )}
      {...props}
    >
      {unconfigured && (
        <CircleAlertIcon
          aria-hidden
          className="size-3 shrink-0 text-amber-500 dark:text-amber-400"
        />
      )}
      <span className="min-w-0 truncate">{model}</span>
      <ChevronDownIcon className="size-3 shrink-0 opacity-60" />
    </button>
  );
}

/** Displays the estimated context breakdown used by the Composer toolbar. */
export function ComposerContext({
  usage,
  className,
  ...props
}: Omit<ComponentProps<"div">, "children"> & { usage: ComposerUsage }) {
  const used = usage.system + usage.tools + usage.messages;
  const fraction = usage.total === 0 ? 0 : used / usage.total;
  const warn = fraction > 0.85;
  const circumference = 2 * Math.PI * 6;
  const segments = [
    { label: "System", value: usage.system, className: "bg-foreground/25" },
    { label: "Tools", value: usage.tools, className: "bg-foreground/45" },
    { label: "Messages", value: usage.messages, className: "bg-foreground/80" },
  ];

  return (
    <div
      data-slot="composer-context"
      className={cn("group/ctx relative", className)}
      {...props}
    >
      <div
        className={cn(
          "absolute end-0 bottom-full z-10 mb-2 flex min-w-64 max-w-[calc(100vw-2rem)] origin-bottom-right flex-col gap-3.5 rounded-2xl border border-border/60 p-4",
          surfaceClasses(3, 3),
          "transition-[opacity,scale] duration-200 ease-[cubic-bezier(0.23,1,0.32,1)] motion-reduce:transition-none",
          "pointer-events-none scale-[0.97] opacity-0",
          "group-hover/ctx:pointer-events-auto group-hover/ctx:scale-100 group-hover/ctx:opacity-100",
          "group-focus-within/ctx:pointer-events-auto group-focus-within/ctx:scale-100 group-focus-within/ctx:opacity-100",
        )}
      >
        <div className="flex items-baseline justify-between">
          <div className="min-w-0">
            <p className="text-[13.5px] font-medium">
              {usage.estimated ? "Estimated context" : "Context"}
            </p>
            {usage.description && (
              <p className="text-foreground/45 mt-0.5 text-[11px] leading-4">
                {usage.description}
              </p>
            )}
          </div>
          <p
            className={cn(
              mono,
              "tabular-nums",
              warn ? "text-red-500 dark:text-red-400" : "text-foreground/35",
            )}
          >
            {Math.round(clamp(fraction, 0, 1) * 100)}%
          </p>
        </div>
        <div className="bg-foreground/[0.06] flex h-[5px] w-full gap-px overflow-hidden rounded-full">
          {segments.map((segment) => (
            <span
              key={segment.label}
              className={cn(
                "h-full transition-[width] duration-700 motion-reduce:transition-none",
                segment.className,
              )}
              style={{ width: `${pct(segment.value, usage.total)}%` }}
            />
          ))}
        </div>
        <div className="flex flex-col gap-2">
          {segments.map((segment) => (
            <div
              key={segment.label}
              className="text-foreground/55 flex items-center gap-2.5 text-[13px]"
            >
              <span
                aria-hidden
                className={cn("size-1.5 rounded-full", segment.className)}
              />
              <span className="flex-1">{segment.label}</span>
              <span className={cn(mono, "text-foreground/40 tabular-nums")}>
                {segment.value}k
              </span>
            </div>
          ))}
        </div>
        <div className="bg-foreground/[0.06] h-px" />
        <div className="text-foreground/55 flex items-center justify-between text-[13px]">
          <span>{usage.estimated ? "Estimate" : "Total"}</span>
          <span className={cn(mono, "text-foreground/40 tabular-nums")}>
            {used}k / {usage.total}k
          </span>
        </div>
      </div>
      <button
        type="button"
        aria-label={
          usage.estimated ? "Estimated context usage" : "Context usage"
        }
        className={cn(
          ghostButton,
          "size-8",
          warn && "text-red-500 dark:text-red-400",
        )}
      >
        <svg viewBox="0 0 16 16" className="size-4 -rotate-90" aria-hidden>
          <circle
            cx="8"
            cy="8"
            r="6"
            fill="none"
            strokeWidth="2.5"
            className="stroke-foreground/10"
          />
          <circle
            cx="8"
            cy="8"
            r="6"
            fill="none"
            strokeWidth="2.5"
            strokeLinecap="round"
            className="stroke-current transition-[stroke-dashoffset] duration-700 motion-reduce:transition-none"
            strokeDasharray={circumference}
            strokeDashoffset={circumference * (1 - clamp(fraction, 0, 1))}
          />
        </svg>
      </button>
    </div>
  );
}

/**
 * Resolves the model shown for a provider route without exposing its endpoint.
 * Built-in providers keep their model selection in their own browser-owned
 * auth stores, while custom profiles persist the model identifier directly.
 */
interface ComposerModelOption {
  key: string;
  modelId?: string;
  label: string;
  description: string;
  providerId: string;
  ready: boolean;
}

function modelOptionKey(providerId: string, modelId: string): string {
  return `${providerId}:${modelId}`;
}

/**
 * Sentinel model id for options that route a provider's own default model.
 * It never equals a configured model id, so option keys stay unique even for
 * a profile whose model id is literally "default".
 */
const DEFAULT_MODEL_KEY = "__default__";

export const ComposerModelPicker: FC = () => {
  const { preferences, setEffort, setSpeed, setAccess } =
    useComposerPreferences();
  const [open, setOpen] = useState(false);
  const { profiles, activeProviderId, setActiveProviderId } = useProviders();
  const {
    apiKey: openRouterApiKey,
    selectedModel: openRouterModel,
    customModelEnabled: openRouterCustomModelEnabled,
    setSelectedModel: setOpenRouterModel,
    setCustomModelEnabled: setOpenRouterCustomModelEnabled,
  } = useOpenRouterAuth();
  const {
    apiKey: openCodeZenApiKey,
    selectedModel: openCodeZenModel,
    customModelEnabled: openCodeZenCustomModelEnabled,
    setSelectedModel: setOpenCodeZenModel,
    setCustomModelEnabled: setOpenCodeZenCustomModelEnabled,
  } = useOpenCodeZenAuth();

  const activeProfile = profiles.find((entry) => entry.id === activeProviderId);
  const openRouterReady = Boolean(openRouterApiKey?.trim());
  const openCodeZenReady = Boolean(openCodeZenApiKey?.trim());
  const modelOptions = useMemo<ComposerModelOption[]>(() => {
    const options: ComposerModelOption[] = [
      {
        key: SERVER_DEFAULT_ID,
        label: "Server default model",
        description: "Server configuration",
        providerId: SERVER_DEFAULT_ID,
        ready: true,
      },
      {
        key: modelOptionKey(OPENROUTER_PROFILE_ID, DEFAULT_MODEL_KEY),
        label: "OpenRouter default model",
        description: "Provider default · via OpenRouter",
        providerId: OPENROUTER_PROFILE_ID,
        ready: openRouterReady,
      },
      {
        key: modelOptionKey(OPENCODE_ZEN_PROFILE_ID, DEFAULT_MODEL_KEY),
        label: "OpenCode Zen default model",
        description: "Provider default · via OpenCode Zen",
        providerId: OPENCODE_ZEN_PROFILE_ID,
        ready: openCodeZenReady,
      },
      ...POPULAR_OPENROUTER_MODELS.map((model) => ({
        key: modelOptionKey(OPENROUTER_PROFILE_ID, model.id),
        modelId: model.id,
        label: model.label,
        description: `${model.id} · via OpenRouter`,
        providerId: OPENROUTER_PROFILE_ID,
        ready: openRouterReady,
      })),
      ...POPULAR_OPENCODE_ZEN_MODELS.map((model) => ({
        key: modelOptionKey(OPENCODE_ZEN_PROFILE_ID, model.id),
        modelId: model.id,
        label: model.label,
        description: `${model.id} · via OpenCode Zen`,
        providerId: OPENCODE_ZEN_PROFILE_ID,
        ready: openCodeZenReady,
      })),
    ];

    const knownModelKeys = new Set(
      options
        .filter((option) => option.modelId)
        .map((option) => option.key),
    );
    if (!knownModelKeys.has(modelOptionKey(OPENROUTER_PROFILE_ID, openRouterModel))) {
      options.push({
        key: modelOptionKey(OPENROUTER_PROFILE_ID, openRouterModel),
        modelId: openRouterModel,
        label: openRouterModel,
        description: "Custom model · via OpenRouter",
        providerId: OPENROUTER_PROFILE_ID,
        ready: openRouterReady,
      });
    }
    if (!knownModelKeys.has(modelOptionKey(OPENCODE_ZEN_PROFILE_ID, openCodeZenModel))) {
      options.push({
        key: modelOptionKey(OPENCODE_ZEN_PROFILE_ID, openCodeZenModel),
        modelId: openCodeZenModel,
        label: openCodeZenModel,
        description: "Custom model · via OpenCode Zen",
        providerId: OPENCODE_ZEN_PROFILE_ID,
        ready: openCodeZenReady,
      });
    }

    for (const profile of profiles) {
      if (
        profile.id === OPENROUTER_PROFILE_ID ||
        profile.id === OPENCODE_ZEN_PROFILE_ID
      ) {
        continue;
      }
      const routeReady = Boolean(profile.apiKey?.trim() && profile.baseUrl?.trim());
      const modelId = profile.modelId?.trim();
      if (!modelId) {
        // Without a configured model id the profile routes its provider
        // default, so one option describes the whole route.
        options.push({
          key: modelOptionKey(profile.id, DEFAULT_MODEL_KEY),
          label: `${profile.name} default model`,
          description: `Provider default · via ${profile.name}`,
          providerId: profile.id,
          ready: routeReady,
        });
        continue;
      }
      // A profile with a model id always sends that id, so a second
      // "provider default" row would duplicate this route and mislabel the
      // model that actually runs.
      options.push({
        key: modelOptionKey(profile.id, modelId),
        modelId,
        label: modelId,
        description: `via ${profile.name}`,
        providerId: profile.id,
        ready: routeReady,
      });
    }

    const seenKeys = new Set<string>();
    return options.filter((option) => {
      if (seenKeys.has(option.key)) return false;
      seenKeys.add(option.key);
      return true;
    });
  }, [
    openCodeZenModel,
    openCodeZenReady,
    openRouterModel,
    openRouterReady,
    profiles,
  ]);

  const activeModelKey = (() => {
    if (activeProviderId === SERVER_DEFAULT_ID) return SERVER_DEFAULT_ID;
    if (activeProviderId === OPENROUTER_PROFILE_ID) {
      if (!openRouterReady) return SERVER_DEFAULT_ID;
      return openRouterCustomModelEnabled
        ? modelOptionKey(activeProviderId, openRouterModel)
        : modelOptionKey(activeProviderId, DEFAULT_MODEL_KEY);
    }
    if (activeProviderId === OPENCODE_ZEN_PROFILE_ID) {
      if (!openCodeZenReady) return SERVER_DEFAULT_ID;
      return openCodeZenCustomModelEnabled
        ? modelOptionKey(activeProviderId, openCodeZenModel)
        : modelOptionKey(activeProviderId, DEFAULT_MODEL_KEY);
    }
    const routeReady = Boolean(
      activeProfile?.apiKey?.trim() && activeProfile.baseUrl?.trim(),
    );
    if (!routeReady) return SERVER_DEFAULT_ID;
    const modelId = activeProfile?.modelId?.trim();
    const option = modelOptions.find(
      (entry) =>
        entry.key ===
          modelOptionKey(activeProviderId, modelId || DEFAULT_MODEL_KEY) &&
        entry.ready,
    );
    return option?.key ?? SERVER_DEFAULT_ID;
  })();

  const activeModelOption = modelOptions.find((option) => option.key === activeModelKey);
  const activeModelLabel = activeModelOption?.label ?? "Server default model";

  // The selected route and the effective route diverge when the stored
  // provider has no usable credentials: the run sends no provider headers, so
  // it falls back to the server model. Name that state instead of silently
  // presenting the fallback as the user's own selection.
  const unconfiguredRoute = (() => {
    if (activeProviderId === SERVER_DEFAULT_ID) return null;
    if (activeProviderId === OPENROUTER_PROFILE_ID) {
      return openRouterReady
        ? null
        : { name: "OpenRouter", detail: "has no API key" };
    }
    if (activeProviderId === OPENCODE_ZEN_PROFILE_ID) {
      return openCodeZenReady
        ? null
        : { name: "OpenCode Zen", detail: "has no API key" };
    }
    if (!activeProfile) return null;
    const ready = Boolean(
      activeProfile.apiKey?.trim() && activeProfile.baseUrl?.trim(),
    );
    return ready
      ? null
      : { name: activeProfile.name, detail: "has no usable key or base URL" };
  })();

  const handleModelChange = (key: string) => {
    const option = modelOptions.find((entry) => entry.key === key);
    if (!option || !option.ready) return;

    setActiveProviderId(option.providerId);
    if (option.providerId === OPENROUTER_PROFILE_ID) {
      if (option.modelId) setOpenRouterModel(option.modelId);
      setOpenRouterCustomModelEnabled(Boolean(option.modelId));
    }
    if (option.providerId === OPENCODE_ZEN_PROFILE_ID) {
      if (option.modelId) setOpenCodeZenModel(option.modelId);
      setOpenCodeZenCustomModelEnabled(Boolean(option.modelId));
    }
  };

  // Keep the compact trigger focused on the selected route. Effort, speed,
  // and access remain available as local preferences from the menu.
  const triggerLabel = activeModelLabel;

  return (
    <DropdownMenu onOpenChange={setOpen}>
      <DropdownMenuTrigger
        render={
          <ComposerModelTrigger
            model={triggerLabel}
            open={open}
            unconfigured={unconfiguredRoute !== null}
            aria-label="Model and reasoning preferences"
            title={
              unconfiguredRoute
                ? `${unconfiguredRoute.name} needs setup · runs use the ${triggerLabel}`
                : undefined
            }
            className="h-7 max-w-[15rem] px-2 text-xs max-sm:max-w-[8rem]"
          />
        }
      />
      <DropdownMenuContent
        align="end"
        className="max-h-[var(--available-height)] w-72 max-w-[calc(100vw-1rem)] space-y-1 overflow-y-auto p-1.5 text-xs"
      >
        <DropdownMenuGroup>
          <DropdownMenuLabel className="px-2 py-1 text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
            Model
          </DropdownMenuLabel>
          {unconfiguredRoute && (
            <p className="mx-2 mb-1.5 flex items-start gap-1.5 rounded-lg border border-amber-500/30 bg-amber-500/[0.08] px-2 py-1.5 text-[10px] leading-4 text-amber-700 dark:text-amber-300">
              <CircleAlertIcon aria-hidden className="mt-0.5 size-3 shrink-0" />
              <span>
                {unconfiguredRoute.name} {unconfiguredRoute.detail} yet, so
                runs use the {triggerLabel}. Finish its setup in Settings →
                Providers &amp; Models.
              </span>
            </p>
          )}
          <DropdownMenuRadioGroup
            value={activeModelKey}
            onValueChange={handleModelChange}
          >
            {modelOptions.map((option) => (
              <DropdownMenuRadioItem
                key={option.key}
                value={option.key}
                disabled={!option.ready}
                className="flex cursor-pointer items-center justify-between py-1.5"
              >
                <span className="flex min-w-0 flex-col">
                  <span className="truncate font-medium">{option.label}</span>
                  <span className="truncate text-[10px] text-muted-foreground">
                    {option.description}
                  </span>
                </span>
              </DropdownMenuRadioItem>
            ))}
          </DropdownMenuRadioGroup>
          <p className="px-2 pb-1 pt-1.5 text-[10px] leading-4 text-muted-foreground">
            Selecting a model chooses its configured route. Manage keys and
            model identifiers in Settings → Providers &amp; Models.
          </p>
        </DropdownMenuGroup>

        <DropdownMenuSeparator />

        <DropdownMenuGroup>
          <DropdownMenuLabel className="flex items-center gap-1.5 px-2 py-1 text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
            <BrainIcon className="size-3" />
            Reasoning effort
          </DropdownMenuLabel>
          <DropdownMenuRadioGroup
            value={preferences.effort}
            onValueChange={(value) => setEffort(value as EffortLevel)}
          >
            {([
              ["Low", "Brief reasoning"],
              ["Medium", "Balanced"],
              ["High", "Deep thinking"],
            ] as const).map(([value, description]) => (
              <DropdownMenuRadioItem
                key={value}
                value={value}
                className="flex cursor-pointer items-center justify-between py-1"
              >
                <span>{value}</span>
                <span className="text-[10px] text-muted-foreground">{description}</span>
              </DropdownMenuRadioItem>
            ))}
          </DropdownMenuRadioGroup>
        </DropdownMenuGroup>

        <DropdownMenuSeparator />

        <DropdownMenuGroup>
          <DropdownMenuLabel className="flex items-center gap-1.5 px-2 py-1 text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
            <LockKeyholeIcon className="size-3" />
            Access
          </DropdownMenuLabel>
          <DropdownMenuRadioGroup
            value={preferences.access}
            onValueChange={(value) => setAccess(value as ComposerAccess)}
          >
            <DropdownMenuRadioItem
              value="Full access"
              className="cursor-pointer py-1"
            >
              <span className="flex flex-col">
                <span className="font-medium">Full access</span>
                <span className="text-[10px] text-muted-foreground">
                  Session preference only
                </span>
              </span>
            </DropdownMenuRadioItem>
            <DropdownMenuRadioItem
              value="Read-only"
              className="cursor-pointer py-1"
            >
              <span className="flex flex-col">
                <span className="font-medium">Read-only</span>
                <span className="text-[10px] text-muted-foreground">
                  Session preference only
                </span>
              </span>
            </DropdownMenuRadioItem>
          </DropdownMenuRadioGroup>
        </DropdownMenuGroup>

        <DropdownMenuSeparator />

        <DropdownMenuItem
          onClick={() => setSpeed(preferences.speed === "Fast" ? "Standard" : "Fast")}
          className="flex cursor-pointer items-center justify-between py-1.5"
        >
          <span className="flex items-center gap-2">
            <ZapIcon className="size-3.5 text-muted-foreground" />
            <span className="flex flex-col">
              <span className="font-medium">Fast mode</span>
              <span className="text-[10px] text-muted-foreground">
                Session preference only
              </span>
            </span>
          </span>
          {preferences.speed === "Fast" && <CheckIcon className="size-3.5" />}
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );
};

/**
 * Estimates character usage in thousands using 4,000-character increments.
 *
 * @param characters - The number of characters to estimate
 * @returns `0` for zero or fewer characters; otherwise, the estimated number of increments, with a minimum of `1`
 */
function estimateThousands(characters: number): number {
  if (characters <= 0) return 0;
  return Math.max(1, Math.ceil(characters / 4000));
}

/**
 * Counts visible text characters in strings and structured content.
 *
 * @param value - The value to inspect, including strings, arrays, or content objects
 * @returns The number of visible text characters, excluding image, file, audio, and data content
 */
function visibleTextCharacters(value: unknown): number {
  if (typeof value === "string") return value.length;
  if (Array.isArray(value)) {
    return value.reduce((total, item) => total + visibleTextCharacters(item), 0);
  }
  if (!value || typeof value !== "object") return 0;

  const record = value as Record<string, unknown>;
  if (["image", "file", "audio", "data"].includes(String(record.type))) {
    return 0;
  }
  if (typeof record.text === "string") return record.text.length;
  if ("content" in record) return visibleTextCharacters(record.content);
  return 0;
}

export const ComposerContextIndicator: FC = () => {
  const aui = useAui();
  const messages = useAuiState((state) => state.thread.messages);

  const usage = useMemo(() => {
    const modelContext = aui.thread.getModelContext();
    const system = estimateThousands(visibleTextCharacters(modelContext.system));
    const toolCharacters = Object.entries(modelContext.tools ?? {}).reduce(
      (total, [name, tool]) => total + name.length + (tool.description?.length ?? 0),
      0,
    );
    const tools = estimateThousands(toolCharacters);
    const messageTokens = estimateThousands(visibleTextCharacters(messages));

    return {
      system,
      tools,
      messages: messageTokens,
      total: 128,
      estimated: true,
      description:
        "Estimated from visible messages and registered tools; provider usage is unavailable.",
    };
  }, [aui, messages]);

  return <ComposerContext usage={usage} className="shrink-0" />;
};

const plainDirectiveFormatter: Unstable_DirectiveFormatter = {
  serialize(item) {
    return item.type === "command" ? `/${item.id}` : `@${item.label}`;
  },
  parse(text) {
    return [{ kind: "text", text }];
  },
};

const slashAdapterCommands = SLASH_COMMANDS.map((command) => ({
  id: command.name,
  label: `/${command.name}`,
  description: command.description,
  execute: () => undefined,
}));

/**
 * Renders the icon associated with a slash command or mention trigger item.
 *
 * @param item - The trigger item whose icon should be rendered
 */
function TriggerItemIcon({ item }: { item: Unstable_TriggerItem }) {
  if (item.type === "command") {
    const command = SLASH_COMMANDS.find((entry) => entry.name === item.id);
    const Icon = command?.icon ?? ZapIcon;
    return <Icon className="size-4 shrink-0 text-muted-foreground" />;
  }
  return <AtSignIcon className="size-4 shrink-0 text-muted-foreground" />;
}

/**
 * Renders trigger items with their icons, labels, descriptions, and keyboard hints.
 *
 * @param items - The trigger items to display.
 */
function TriggerItems({ items }: { items: readonly Unstable_TriggerItem[] }) {
  if (!items.length) {
    return (
      <p className="px-3 py-3 text-xs text-muted-foreground" role="status">
        Nothing matches that search.
      </p>
    );
  }

  return (
    <div className="flex flex-col gap-0.5">
      {items.map((item, index) => (
        <ComposerPrimitive.Unstable_TriggerPopoverItem
          key={item.id}
          item={item}
          index={index}
          className="group flex w-full items-start gap-2 rounded-lg px-2.5 py-2 text-start text-xs outline-none transition-colors hover:bg-accent data-highlighted:bg-accent data-highlighted:text-accent-foreground"
        >
          <TriggerItemIcon item={item} />
          <span className="flex min-w-0 flex-1 flex-col gap-0.5">
            <span className="truncate font-medium">{item.label}</span>
            {item.description && (
              <span className="truncate text-[10px] text-muted-foreground group-data-highlighted:text-accent-foreground/70">
                {item.description}
              </span>
            )}
          </span>
          <kbd className="shrink-0 rounded bg-muted px-1 font-mono text-[10px] text-muted-foreground group-data-highlighted:bg-background/40">
            ↵
          </kbd>
        </ComposerPrimitive.Unstable_TriggerPopoverItem>
      ))}
    </div>
  );
}

export const ComposerTriggerPopovers: FC<{
  workspaceContext: ComposerWorkspaceContext;
}> = ({ workspaceContext }) => {
  const mentionItems = useMemo<Unstable_Mention[]>(
    () => [
      {
        id: "agent",
        type: "agent",
        label: workspaceContext.agentLabel,
        description: "Active agent",
      },
      {
        id: `project:${workspaceContext.projectId ?? "current"}`,
        type: "project",
        label: workspaceContext.projectLabel,
        description: "Active project",
      },
      {
        id: `thread:${workspaceContext.threadId ?? "current"}`,
        type: "thread",
        label: workspaceContext.threadLabel,
        description: "Active thread",
      },
    ],
    [workspaceContext],
  );

  const mention = unstable_useMentionAdapter({
    items: mentionItems,
    includeModelContextTools: false,
    formatter: plainDirectiveFormatter,
  });
  const slash = unstable_useSlashCommandAdapter({
    commands: slashAdapterCommands,
    removeOnExecute: false,
  });

  const popoverClassName = cn(
    "absolute inset-x-0 bottom-full z-20 mb-2 max-h-72 overflow-y-auto rounded-xl border border-border/70 p-1 outline-none",
    surfaceClasses(3, 3),
  );

  return (
    <>
      <ComposerPrimitive.Unstable_TriggerPopover
        char="/"
        adapter={slash.adapter}
        aria-label="Slash commands"
        className={popoverClassName}
      >
        <ComposerPrimitive.Unstable_TriggerPopover.Action
          formatter={plainDirectiveFormatter}
          onExecute={slash.action.onExecute}
          removeOnExecute={false}
        />
        <ComposerPrimitive.Unstable_TriggerPopoverItems aria-label="Slash command results">
          {(items) => <TriggerItems items={items} />}
        </ComposerPrimitive.Unstable_TriggerPopoverItems>
      </ComposerPrimitive.Unstable_TriggerPopover>

      <ComposerPrimitive.Unstable_TriggerPopover
        char="@"
        adapter={mention.adapter}
        aria-label="Workspace mentions"
        className={popoverClassName}
      >
        <ComposerPrimitive.Unstable_TriggerPopover.Directive
          formatter={mention.directive.formatter}
          onInserted={mention.directive.onInserted}
        />
        <ComposerPrimitive.Unstable_TriggerPopoverItems aria-label="Workspace mention results">
          {(items) => <TriggerItems items={items} />}
        </ComposerPrimitive.Unstable_TriggerPopoverItems>
      </ComposerPrimitive.Unstable_TriggerPopover>
    </>
  );
};
