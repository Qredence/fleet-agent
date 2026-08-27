"use client";

import {
  createContext,
  useContext,
  useMemo,
  useState,
  type FC,
  type PropsWithChildren,
} from "react";
import {
  AtSignIcon,
  BrainIcon,
  CheckIcon,
  FileTextIcon,
  GlobeIcon,
  LockKeyholeIcon,
  SparklesIcon,
  WrenchIcon,
  ZapIcon,
  type LucideIcon,
} from "lucide-react";
import {
  ComposerContext,
  ComposerModelTrigger,
} from "@/components/elements/composer";
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
import { surfaceClasses } from "@/lib/surface-classes";

export type EffortLevel = "Low" | "Medium" | "High";
export type ComposerSpeed = "Fast" | "Standard";
export type ComposerAccess = "Full access" | "Read-only";

export interface ModelOption {
  id: string;
  name: string;
  shortName: string;
  meta: string;
}

export interface ComposerPreferences {
  model: ModelOption;
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
    description: "Search project documentation and web evidence",
    icon: GlobeIcon,
  },
  {
    name: "report",
    description: "Generate structured Markdown research report",
    icon: FileTextIcon,
  },
  {
    name: "optimize",
    description: "Launch DSPy GEPA prompt & architecture evolution",
    icon: SparklesIcon,
  },
  {
    name: "tools",
    description: "Inspect registered tools and execution policies",
    icon: WrenchIcon,
  },
];

const AVAILABLE_MODELS: ModelOption[] = [
  { id: "luna", name: "5.6 Luna", shortName: "5.6 Luna", meta: "Default • Fast" },
  {
    id: "gpt-4o-mini",
    name: "openai/gpt-4o-mini",
    shortName: "GPT-4o mini",
    meta: "OpenAI • Balanced",
  },
  { id: "o3-mini", name: "openai/o3-mini", shortName: "o3-mini", meta: "Reasoning • Staged" },
  {
    id: "claude-3-5",
    name: "anthropic/claude-3-5-sonnet",
    shortName: "Claude 3.5",
    meta: "Anthropic • Deep",
  },
];

const DEFAULT_PREFERENCES: ComposerPreferences = {
  model: AVAILABLE_MODELS[0]!,
  effort: "High",
  speed: "Fast",
  access: "Full access",
};

interface ComposerPreferencesContextValue {
  preferences: ComposerPreferences;
  setModel: (model: ModelOption) => void;
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
  const [model, setModel] = useState(DEFAULT_PREFERENCES.model);
  const [effort, setEffort] = useState<EffortLevel>(DEFAULT_PREFERENCES.effort);
  const [speed, setSpeed] = useState<ComposerSpeed>(DEFAULT_PREFERENCES.speed);
  const [access, setAccess] = useState<ComposerAccess>(DEFAULT_PREFERENCES.access);

  const value = useMemo<ComposerPreferencesContextValue>(
    () => ({
      preferences: { model, effort, speed, access },
      setModel,
      setEffort,
      setSpeed,
      setAccess,
    }),
    [model, effort, speed, access],
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

export const ComposerModelPicker: FC = () => {
  const { preferences, setModel, setEffort, setSpeed } = useComposerPreferences();
  const [open, setOpen] = useState(false);

  const triggerLabel = `${preferences.model.shortName} ${preferences.effort}${
    preferences.speed === "Fast" ? "" : " (Standard)"
  }`;

  return (
    <DropdownMenu onOpenChange={setOpen}>
      <DropdownMenuTrigger
        render={
          <ComposerModelTrigger
            model={triggerLabel}
            open={open}
            aria-label="Model and reasoning preferences"
            className="h-7 max-w-[15rem] bg-muted/30 px-2.5 text-xs hover:bg-muted/60 max-sm:max-w-[8rem]"
          />
        }
      />
      <DropdownMenuContent align="end" className="w-72 max-w-[calc(100vw-1rem)] space-y-1 p-1.5 text-xs">
        <DropdownMenuGroup>
          <DropdownMenuLabel className="px-2 py-1 text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
            Model
          </DropdownMenuLabel>
          <DropdownMenuRadioGroup
            value={preferences.model.id}
            onValueChange={(value) => {
              const model = AVAILABLE_MODELS.find((entry) => entry.id === value);
              if (model) setModel(model);
            }}
          >
            {AVAILABLE_MODELS.map((model) => (
              <DropdownMenuRadioItem
                key={model.id}
                value={model.id}
                className="flex cursor-pointer items-center justify-between py-1.5"
              >
                <span className="flex min-w-0 flex-col">
                  <span className="truncate font-medium">{model.name}</span>
                  <span className="text-[10px] text-muted-foreground">{model.meta}</span>
                </span>
              </DropdownMenuRadioItem>
            ))}
          </DropdownMenuRadioGroup>
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

export const ComposerAccessPicker: FC = () => {
  const { preferences, setAccess } = useComposerPreferences();
  const [open, setOpen] = useState(false);

  return (
    <DropdownMenu onOpenChange={setOpen}>
      <DropdownMenuTrigger
        render={
          <button
            type="button"
            aria-label="Access mode"
            aria-expanded={open}
            className="inline-flex h-7 max-w-[9rem] items-center gap-1.5 rounded-full border border-border/40 bg-muted/40 px-2.5 text-[11px] font-medium text-muted-foreground transition-colors hover:bg-muted/70 hover:text-foreground max-sm:max-w-8 max-sm:justify-center max-sm:px-0"
          />
        }
      >
        <LockKeyholeIcon className="size-3 shrink-0" />
        <span className="truncate max-sm:sr-only">{preferences.access}</span>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="start" className="w-64 max-w-[calc(100vw-1rem)] p-1.5 text-xs">
        <DropdownMenuGroup>
          <DropdownMenuLabel className="px-2 py-1 text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
            Access
          </DropdownMenuLabel>
          <DropdownMenuRadioGroup
            value={preferences.access}
            onValueChange={(value) => setAccess(value as ComposerAccess)}
          >
            <DropdownMenuRadioItem value="Full access" className="cursor-pointer py-1.5">
              <span className="flex flex-col">
                <span className="font-medium">Full access</span>
                <span className="text-[10px] text-muted-foreground">
                  Session preference only
                </span>
              </span>
            </DropdownMenuRadioItem>
            <DropdownMenuRadioItem value="Read-only" className="cursor-pointer py-1.5">
              <span className="flex flex-col">
                <span className="font-medium">Read-only</span>
                <span className="text-[10px] text-muted-foreground">
                  Session preference only
                </span>
              </span>
            </DropdownMenuRadioItem>
          </DropdownMenuRadioGroup>
        </DropdownMenuGroup>
        <p className="px-2 pb-1 pt-2 text-[10px] leading-4 text-muted-foreground">
          These controls are local UI preferences and are not sent to the agent.
        </p>
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
