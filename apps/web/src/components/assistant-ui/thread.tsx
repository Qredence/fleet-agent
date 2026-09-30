"use client";

import {
  ComposerAddAttachment,
  ComposerAttachments,
  UserMessageAttachments,
} from "@/components/assistant-ui/attachment";
import { File } from "@/components/assistant-ui/file";
import { ThreadFollowupSuggestions } from "@/components/assistant-ui/follow-up-suggestions";
import { Image } from "@/components/assistant-ui/image";
import { MarkdownText } from "@/components/assistant-ui/markdown-text";
import {
  Reasoning,
  ReasoningContent,
  ReasoningRoot,
  ReasoningText,
  ReasoningTrigger,
} from "@/components/assistant-ui/reasoning";
import { ToolFallback } from "@/components/assistant-ui/tool-fallback";
import { ComposerQueue } from "@/components/assistant-ui/queue-item";
import { ScrollAnchor } from "@/components/assistant-ui/scroll-anchor";
import {
  ToolGroupContent,
  ToolGroupRoot,
  ToolGroupTrigger,
} from "@/components/assistant-ui/tool-group";
import { useRunReadiness } from "@/features/agent-runtime/agent-capabilities";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { useShape } from "@/lib/shape-context";
import { cn } from "@/lib/utils";
import {
  ActionBarMorePrimitive,
  ActionBarPrimitive,
  AuiIf,
  type AssistantState,
  BranchPickerPrimitive,
  ComposerPrimitive,
  ErrorPrimitive,
  groupPartByType,
  MessagePrimitive,
  SuggestionPrimitive,
  ThreadPrimitive,
  type FileMessagePartComponent,
  type ImageMessagePartComponent,
  type ToolCallMessagePartComponent,
  useAuiState,
} from "@assistant-ui/react";
import {
  ArrowUpIcon,
  CheckIcon,
  ChevronLeftIcon,
  ChevronRightIcon,
  CircleAlertIcon,
  CodeIcon,
  CopyIcon,
  DownloadIcon,
  GlobeIcon,
  MicIcon,
  MoreHorizontalIcon,
  PencilIcon,
  RefreshCwIcon,
  SparklesIcon,
  SquareIcon,
  TerminalIcon,
  ThumbsDown,
  ThumbsUp,
} from "lucide-react";
import {
  ComposerModelPicker,
  ComposerContextIndicator,
  ComposerTriggerPopovers,
  type ComposerWorkspaceContext,
} from "@/components/assistant-ui/composer-elements";
import {
  createContext,
  useContext,
  type ComponentType,
  type FC,
  type PropsWithChildren,
} from "react";

export type ThreadGroupPart = MessagePrimitive.GroupedParts.GroupPart;

export type ThreadComponents = {
  AssistantMessage?: ComponentType | undefined;
  Welcome?: ComponentType | undefined;
  ToolFallback?: ToolCallMessagePartComponent | undefined;
  ToolGroup?:
    | ComponentType<PropsWithChildren<{ group: ThreadGroupPart }>>
    | undefined;
  ReasoningGroup?:
    | ComponentType<PropsWithChildren<{ group: ThreadGroupPart }>>
    | undefined;
};

export type ThreadProps = {
  components?: ThreadComponents | undefined;
  workspaceContext?: ComposerWorkspaceContext | undefined;
};

const EMPTY_COMPONENTS: ThreadComponents = {};

const ThreadComponentsContext =
  createContext<ThreadComponents>(EMPTY_COMPONENTS);

const isNewChatView = (s: AssistantState) =>
  s.thread.messages.length === 0 &&
  (!s.thread.isLoading || s.threads.isLoading);

const isHistoryLoadingView = (s: AssistantState) =>
  s.thread.messages.length === 0 &&
  s.thread.isLoading &&
  !s.thread.isDisabled &&
  !s.threads.isLoading;

const ThreadHistorySkeleton: FC = () => (
  <div
    data-slot="aui_thread-history-skeleton"
    role="status"
    className="animate-in fade-in fill-mode-both flex flex-col gap-y-6 [animation-delay:150ms] [animation-duration:200ms]"
  >
    <span className="sr-only">Loading conversation</span>
    <Skeleton className="ms-auto h-9 w-2/5 rounded-xl motion-reduce:animate-none" />
    <div className="flex flex-col gap-y-2">
      <Skeleton className="h-4 w-11/12 motion-reduce:animate-none" />
      <Skeleton className="h-4 w-4/5 motion-reduce:animate-none" />
      <Skeleton className="h-4 w-3/5 motion-reduce:animate-none" />
    </div>
    <Skeleton className="ms-auto h-9 w-1/3 rounded-xl motion-reduce:animate-none" />
    <div className="flex flex-col gap-y-2">
      <Skeleton className="h-4 w-10/12 motion-reduce:animate-none" />
      <Skeleton className="h-4 w-2/3 motion-reduce:animate-none" />
    </div>
  </div>
);

const DEFAULT_WORKSPACE_CONTEXT: ComposerWorkspaceContext = {
  agentLabel: "Fleet Agent",
  projectLabel: "Current project",
  threadLabel: "Current thread",
};

interface StarterPrompt {
  prompt: string;
  label: string;
  icon: typeof SparklesIcon;
}

const STARTER_PROMPTS: StarterPrompt[] = [
  {
    prompt: "Research topics with Tavily",
    label: "Web research",
    icon: GlobeIcon,
  },
  {
    prompt: "Analyze codebase architecture",
    label: "Analyze code",
    icon: CodeIcon,
  },
  {
    prompt: "Synthesize findings & plan",
    label: "Synthesize plan",
    icon: SparklesIcon,
  },
  {
    prompt: "Inspect available workspace tools",
    label: "Inspect tools",
    icon: TerminalIcon,
  },
];

export const Thread: FC<ThreadProps> = ({
  components = EMPTY_COMPONENTS,
  workspaceContext = DEFAULT_WORKSPACE_CONTEXT,
}) => {
  const isEmpty = useAuiState(isNewChatView);

  return (
    <ThreadComponentsContext.Provider value={components}>
      <ThreadRoot isEmpty={isEmpty} workspaceContext={workspaceContext} />
    </ThreadComponentsContext.Provider>
  );
};

const ThreadRoot: FC<{
  isEmpty: boolean;
  workspaceContext: ComposerWorkspaceContext;
}> = ({ isEmpty, workspaceContext }) => {
  const { Welcome = ThreadWelcome } = useContext(ThreadComponentsContext);

  return (
    <ThreadPrimitive.Root
      className="aui-root aui-thread-root bg-surface-1 @container flex h-full flex-col"
      style={{
        ["--thread-max-width" as string]: "48rem",
        ["--composer-bg" as string]: "var(--color-surface-2)",
        ["--composer-radius" as string]: "1.25rem",
        ["--composer-padding" as string]: "12px",
      }}
    >
      <ThreadPrimitive.Viewport
        turnAnchor="top"
        data-slot="aui_thread-viewport"
        className="relative flex flex-1 flex-col overflow-x-auto overflow-y-scroll scroll-smooth"
      >
        <div
          className={cn(
            "mx-auto flex w-full max-w-(--thread-max-width) flex-1 flex-col px-4 sm:px-6 pt-4",
            isEmpty && "justify-center",
          )}
        >
          <AuiIf condition={isNewChatView}>
            <Welcome />
          </AuiIf>
          <AuiIf condition={isHistoryLoadingView}>
            <ThreadHistorySkeleton />
          </AuiIf>

          <div
            data-slot="aui_message-group"
            className="mb-8 flex flex-col gap-y-5 empty:hidden"
          >
            <ThreadPrimitive.Messages>
              {() => <ThreadMessage />}
            </ThreadPrimitive.Messages>
          </div>

          <ThreadPrimitive.ViewportFooter
            className={cn(
              "aui-thread-viewport-footer bg-surface-1/90 backdrop-blur-xs flex flex-col gap-3 overflow-visible pb-[max(1rem,env(safe-area-inset-bottom))] md:pb-[max(1.5rem,env(safe-area-inset-bottom))]",
              !isEmpty &&
                "sticky bottom-0 mt-auto rounded-t-(--composer-radius)",
            )}
          >
            <ScrollAnchor />
            <ThreadFollowupSuggestions />
            <ComposerQueue />
            <Composer workspaceContext={workspaceContext} />
            <AuiIf condition={(s) => isNewChatView(s) && s.composer.isEmpty}>
              <ThreadSuggestions />
            </AuiIf>
          </ThreadPrimitive.ViewportFooter>
        </div>
      </ThreadPrimitive.Viewport>
    </ThreadPrimitive.Root>
  );
};

const ThreadMessage: FC = () => {
  const { AssistantMessage: AssistantMessageComponent = AssistantMessage } =
    useContext(ThreadComponentsContext);
  const role = useAuiState((s) => s.message.role);
  const isEditing = useAuiState((s) => s.message.composer.isEditing);

  if (isEditing) return <EditComposer />;
  if (role === "user") return <UserMessage />;
  return <AssistantMessageComponent />;
};

const ThreadWelcome: FC = () => {
  return (
    <div className="aui-thread-welcome-root mb-8 flex flex-col items-center px-4 text-center">
      <div className="mb-3.5 inline-flex items-center gap-1.5 rounded-full border border-border/50 bg-surface-2/80 px-3 py-1 text-xs font-medium text-muted-foreground shadow-2xs backdrop-blur-xs">
        <SparklesIcon className="size-3.5 text-primary" />
        <span>Fleet Agent</span>
      </div>
      <h1 className="aui-thread-welcome-message-inner fade-in slide-in-from-bottom-2 animate-in fill-mode-both text-2xl font-semibold tracking-tight text-foreground sm:text-3xl duration-200">
        How can I help you today?
      </h1>
      <p className="mt-2 text-sm text-muted-foreground max-w-md leading-normal">
        Ask questions, analyze codebase architecture, or run live multi-step research.
      </p>

      <div className="mt-6 flex w-full max-w-xl flex-wrap items-center justify-center gap-2">
        {STARTER_PROMPTS.map((item, idx) => {
          const Icon = item.icon;
          return (
            <ThreadPrimitive.Suggestion
              key={idx}
              prompt={item.prompt}
              method="replace"
              autoSend={false}
              className="aui-thread-starter-pill bg-surface-2/90 hover:bg-surface-3 border-border/50 text-foreground/80 hover:text-foreground inline-flex items-center gap-2 rounded-full border px-3.5 py-1.5 text-xs font-medium transition-all shadow-2xs hover:shadow-xs active:scale-95 cursor-pointer"
            >
              <Icon className="size-3.5 text-muted-foreground" />
              <span>{item.label}</span>
            </ThreadPrimitive.Suggestion>
          );
        })}
      </div>
    </div>
  );
};

const ThreadSuggestions: FC = () => {
  return (
    <div className="aui-thread-welcome-suggestions flex w-full flex-wrap items-center justify-center gap-2 px-4">
      <ThreadPrimitive.Suggestions>
        {() => <ThreadSuggestionItem />}
      </ThreadPrimitive.Suggestions>
    </div>
  );
};

const ThreadSuggestionItem: FC = () => {
  return (
    <div className="aui-thread-welcome-suggestion-display fade-in slide-in-from-bottom-2 animate-in fill-mode-both duration-200">
      <SuggestionPrimitive.Trigger
        send
        render={
          <Button
            variant="ghost"
            className="aui-thread-welcome-suggestion text-foreground/80 hover:text-foreground hover:bg-surface-3 border-border/50 bg-surface-2/70 h-auto gap-1.5 rounded-full border px-3.5 py-1.5 text-xs font-medium whitespace-nowrap transition-all shadow-2xs hover:shadow-xs active:scale-95 cursor-pointer"
          />
        }
      >
        <SuggestionPrimitive.Title className="aui-thread-welcome-suggestion-text-1" />
        <SuggestionPrimitive.Description className="aui-thread-welcome-suggestion-text-2 empty:hidden" />
      </SuggestionPrimitive.Trigger>
    </div>
  );
};

const Composer: FC<{ workspaceContext: ComposerWorkspaceContext }> = ({
  workspaceContext,
}) => {
  const shape = useShape();
  const readiness = useRunReadiness();
  return (
    <ComposerPrimitive.Unstable_TriggerPopoverRoot>
      <ComposerPrimitive.Root className="aui-composer-root relative flex w-full flex-col overflow-visible">
        <ComposerTriggerPopovers workspaceContext={workspaceContext} />
        <ComposerPrimitive.AttachmentDropzone
          render={
            <div
              data-slot="aui_composer-shell"
              className={cn(
                "border border-border/40 bg-surface-2/95 backdrop-blur-md shadow-surface-2 transition-all focus-within:border-ring/50 focus-within:shadow-md flex min-w-0 w-full cursor-text flex-col gap-2 p-3 data-[dragging=true]:border-ring data-[dragging=true]:border-dashed",
                shape.container,
              )}
            />
          }
        >
          <ComposerAttachments />
          <ComposerPrimitive.Input
            placeholder="Ask anything"
            className="aui-composer-input caret-primary placeholder:text-muted-foreground/60 max-h-48 min-h-11 min-w-0 w-full resize-none bg-transparent px-2.5 py-1 text-[15px] leading-6 outline-none"
            rows={1}
            autoFocus
            enterKeyHint="send"
            submitMode={readiness.ready ? "enter" : "none"}
            cancelOnEscape
            unstable_insertNewlineOnTouchEnter
            addAttachmentOnPaste
            name="message"
            id="message-input"
            aria-label="Message input"
          />
          <ComposerAction />
        </ComposerPrimitive.AttachmentDropzone>
      </ComposerPrimitive.Root>
    </ComposerPrimitive.Unstable_TriggerPopoverRoot>
  );
};

const ComposerAction: FC = () => {
  const readiness = useRunReadiness();
  return (
    <div className="aui-composer-action-wrapper relative flex min-w-0 flex-wrap items-center justify-between gap-2 pt-0.5">
      <div className="flex min-w-0 items-center gap-1.5">
        <ComposerAddAttachment />
        <ComposerModelPicker />
      </div>

      <div className="flex min-w-0 flex-wrap items-center justify-end gap-1.5">
        <ComposerContextIndicator />

        <AuiIf condition={(s) => s.thread.capabilities.dictation}>
          <AuiIf condition={(s) => s.composer.dictation == null}>
            <ComposerPrimitive.Dictate
              render={
                <Button
                  type="button"
                  variant="ghost"
                  size="icon"
                  className="aui-composer-dictate text-muted-foreground hover:text-foreground size-8 rounded-full"
                  aria-label="Start voice input"
                />
              }
            >
              <MicIcon className="size-4" />
            </ComposerPrimitive.Dictate>
          </AuiIf>
          <AuiIf condition={(s) => s.composer.dictation != null}>
            <ComposerPrimitive.StopDictation
              render={
                <Button
                  type="button"
                  variant="ghost"
                  size="icon"
                  className="aui-composer-stop-dictation text-destructive size-8 rounded-full"
                  aria-label="Stop voice input"
                />
              }
            >
              <SquareIcon className="size-3.5 animate-pulse fill-current motion-reduce:animate-none" />
            </ComposerPrimitive.StopDictation>
          </AuiIf>
        </AuiIf>

        <AuiIf condition={(s) => !s.thread.isRunning}>
          <ComposerPrimitive.Send
            disabled={!readiness.ready}
            render={
              <Button
                type="submit"
                size="icon"
                className="aui-composer-send size-8 rounded-full bg-foreground text-background hover:opacity-90 active:scale-95 flex items-center justify-center cursor-pointer shadow-xs transition-transform"
                aria-label="Send message"
                title={readiness.ready ? undefined : readiness.message}
              />
            }
          >
            <ArrowUpIcon className="size-4 stroke-[2.5]" />
          </ComposerPrimitive.Send>
        </AuiIf>
        <AuiIf condition={(s) => s.thread.isRunning && s.composer.canCancel}>
          <ComposerPrimitive.Cancel
            render={
              <Button
                type="button"
                variant="default"
                size="icon"
                className="aui-composer-cancel size-8 rounded-full bg-foreground text-background active:scale-95 cursor-pointer shadow-xs transition-transform"
                aria-label="Stop generating"
              />
            }
          >
            <SquareIcon className="size-3.5 fill-current" />
          </ComposerPrimitive.Cancel>
        </AuiIf>
      </div>
    </div>
  );
};

const MessageError: FC = () => {
  return (
    <MessagePrimitive.Error>
      <ErrorPrimitive.Root className="aui-message-error-root border-destructive/40 bg-destructive/10 text-destructive dark:bg-destructive/5 mt-3 flex items-start gap-2.5 rounded-xl border p-3 text-xs dark:text-red-200">
        <CircleAlertIcon className="size-4 shrink-0 mt-0.5 text-destructive" />
        <div className="flex-1">
          <ErrorPrimitive.Message className="aui-message-error-message font-medium" />
        </div>
      </ErrorPrimitive.Root>
    </MessagePrimitive.Error>
  );
};

const AssistantMessage: FC = () => {
  const {
    ToolFallback: ToolFallbackComponent = ToolFallback,
    ToolGroup,
    ReasoningGroup,
  } = useContext(ThreadComponentsContext);

  const ACTION_BAR_PT = "pt-1.5";
  const ACTION_BAR_HEIGHT = `min-h-7.5 ${ACTION_BAR_PT}`;

  return (
    <MessagePrimitive.Root
      data-slot="aui_assistant-message-root"
      data-role="assistant"
      className="fade-in slide-in-from-bottom-1 animate-in relative -mb-7.5 pb-7.5 duration-150 [contain-intrinsic-size:auto_200px] [content-visibility:auto]"
    >
      <div className="mb-1.5 flex items-center gap-2 px-2">
        <div className="flex size-5.5 items-center justify-center rounded-md border border-border/50 bg-surface-2 text-foreground/70 shadow-2xs">
          <SparklesIcon className="size-3 text-primary" />
        </div>
        <span className="text-xs font-medium text-foreground/80">Fleet Agent</span>
      </div>

      <div
        data-slot="aui_assistant-message-content"
        className="text-foreground px-2 leading-relaxed wrap-break-word"
      >
        <MessagePrimitive.GroupedParts
          groupBy={groupPartByType({
            reasoning: ["group-chainOfThought", "group-reasoning"],
            "tool-call": ["group-chainOfThought", "group-tool"],
            "standalone-tool-call": [],
          })}
        >
          {({ part, children }) => {
            switch (part.type) {
              case "group-chainOfThought":
                return <div data-slot="aui_chain-of-thought" className="my-1.5">{children}</div>;
              case "group-tool":
                if (ToolGroup) {
                  return <ToolGroup group={part}>{children}</ToolGroup>;
                }
                return (
                  <ToolGroupRoot variant="ghost" className="my-1.5">
                    <ToolGroupTrigger
                      count={part.indices.length}
                      active={part.status.type === "running"}
                    />
                    <ToolGroupContent>{children}</ToolGroupContent>
                  </ToolGroupRoot>
                );
              case "group-reasoning": {
                if (ReasoningGroup) {
                  return (
                    <ReasoningGroup group={part}>{children}</ReasoningGroup>
                  );
                }
                const running = part.status.type === "running";
                return (
                  <ReasoningRoot streaming={running} className="my-1.5">
                    <ReasoningTrigger active={running} />
                    <ReasoningContent aria-busy={running}>
                      <ReasoningText>{children}</ReasoningText>
                    </ReasoningContent>
                  </ReasoningRoot>
                );
              }
              case "text":
                return <MarkdownText />;
              case "reasoning":
                return <Reasoning {...part} />;
              case "tool-call":
                return part.toolUI ?? <ToolFallbackComponent {...part} />;
              case "data":
                return part.dataRendererUI;
              case "file":
                return (
                  <div data-slot="aui_assistant-message-file" className="py-1">
                    <File {...part} />
                  </div>
                );
              case "image":
                return (
                  <div data-slot="aui_assistant-message-image" className="py-1">
                    <Image {...part} />
                  </div>
                );
              case "indicator":
                return (
                  <span
                    data-slot="aui_assistant-message-indicator"
                    className="inline-flex items-center gap-1.5 text-xs text-muted-foreground animate-pulse py-1"
                    aria-label="Assistant is working"
                  >
                    <span className="size-1.5 rounded-full bg-primary" />
                    <span className="font-mono text-[11px]">Thinking...</span>
                  </span>
                );
              default:
                return null;
            }
          }}
        </MessagePrimitive.GroupedParts>
        <MessageError />
      </div>

      <div
        data-slot="aui_assistant-message-footer"
        className={cn("ms-2 flex items-center gap-1", ACTION_BAR_HEIGHT)}
      >
        <BranchPicker />
        <AssistantActionBar />
      </div>
    </MessagePrimitive.Root>
  );
};

const AssistantActionBar: FC = () => {
  return (
    <ActionBarPrimitive.Root
      hideWhenRunning
      autohide="not-last"
      className="aui-assistant-action-bar-root text-muted-foreground animate-in fade-in flex items-center gap-0.5 pt-1.5 duration-200 opacity-80 hover:opacity-100"
    >
      <ActionBarPrimitive.Copy
        render={
          <Button
            variant="ghost"
            size="icon"
            className="size-7 rounded-md text-muted-foreground hover:bg-surface-2 hover:text-foreground transition-colors"
            aria-label="Copy message"
          />
        }
      >
        <AuiIf condition={(s) => s.message.isCopied}>
          <CheckIcon className="size-3.5 text-green-500 animate-in zoom-in-50 duration-200" />
        </AuiIf>
        <AuiIf condition={(s) => !s.message.isCopied}>
          <CopyIcon className="size-3.5" />
        </AuiIf>
      </ActionBarPrimitive.Copy>

      <ActionBarPrimitive.FeedbackPositive
        render={
          <Button
            variant="ghost"
            size="icon"
            className="size-7 rounded-md text-muted-foreground hover:bg-surface-2 hover:text-foreground data-[submitted]:text-primary transition-colors"
            aria-label="Good response"
          />
        }
      >
        <ThumbsUp className="size-3.5" />
      </ActionBarPrimitive.FeedbackPositive>

      <ActionBarPrimitive.FeedbackNegative
        render={
          <Button
            variant="ghost"
            size="icon"
            className="size-7 rounded-md text-muted-foreground hover:bg-surface-2 hover:text-foreground data-[submitted]:text-destructive transition-colors"
            aria-label="Bad response"
          />
        }
      >
        <ThumbsDown className="size-3.5" />
      </ActionBarPrimitive.FeedbackNegative>

      <ActionBarPrimitive.Reload
        render={
          <Button
            variant="ghost"
            size="icon"
            className="size-7 rounded-md text-muted-foreground hover:bg-surface-2 hover:text-foreground transition-colors"
            aria-label="Regenerate response"
          />
        }
      >
        <RefreshCwIcon className="size-3.5" />
      </ActionBarPrimitive.Reload>

      <ActionBarMorePrimitive.Root>
        <ActionBarMorePrimitive.Trigger
          render={
            <Button
              variant="ghost"
              size="icon"
              className="size-7 rounded-md text-muted-foreground hover:bg-surface-2 hover:text-foreground data-[state=open]:bg-surface-2 transition-colors"
              aria-label="More actions"
            />
          }
        >
          <MoreHorizontalIcon className="size-3.5" />
        </ActionBarMorePrimitive.Trigger>
        <ActionBarMorePrimitive.Content
          side="bottom"
          align="start"
          sideOffset={6}
          className="aui-action-bar-more-content bg-popover text-popover-foreground z-50 min-w-[9rem] overflow-hidden rounded-xl border border-border/50 p-1 shadow-md"
        >
          <ActionBarPrimitive.ExportMarkdown
            render={
              <ActionBarMorePrimitive.Item className="aui-action-bar-more-item hover:bg-accent hover:text-accent-foreground flex cursor-pointer items-center gap-2 rounded-lg px-2.5 py-1.5 text-xs outline-none select-none transition-colors" />
            }
          >
            <DownloadIcon className="size-3.5" />
            Export as Markdown
          </ActionBarPrimitive.ExportMarkdown>
        </ActionBarMorePrimitive.Content>
      </ActionBarMorePrimitive.Root>
    </ActionBarPrimitive.Root>
  );
};

const UserFilePart: FileMessagePartComponent = (part) => (
  <div data-slot="aui_user-message-file" className="py-1">
    <File {...part} />
  </div>
);

const UserImagePart: ImageMessagePartComponent = (part) => (
  <div data-slot="aui_user-message-image" className="py-1">
    <Image {...part} />
  </div>
);

const UserMessage: FC = () => {
  const shape = useShape();
  return (
    <MessagePrimitive.Root
      data-slot="aui_user-message-root"
      className="fade-in slide-in-from-bottom-1 animate-in flex flex-col items-end gap-y-1.5 px-2 duration-150 [contain-intrinsic-size:auto_200px] [content-visibility:auto]"
      data-role="user"
    >
      <UserMessageAttachments />

      <div className="group relative max-w-[85%]">
        <div
          className={cn(
            "aui-user-message-content peer bg-surface-2 shadow-surface-1 text-foreground px-4 py-2.5 text-[14.5px] leading-relaxed wrap-break-word empty:hidden border border-border/40 transition-shadow",
            shape.bg
          )}
        >
          <MessagePrimitive.Parts
            components={{ File: UserFilePart, Image: UserImagePart }}
          />
        </div>
        <div className="aui-user-action-bar-wrapper absolute start-0 top-1/2 -translate-x-full -translate-y-1/2 pe-2 opacity-0 transition-opacity duration-150 group-hover:opacity-100 focus-within:opacity-100 peer-empty:hidden rtl:translate-x-full">
          <UserActionBar />
        </div>
      </div>

      <BranchPicker
        data-slot="aui_user-branch-picker"
        className="justify-end -me-1"
      />
    </MessagePrimitive.Root>
  );
};

const UserActionBar: FC = () => {
  return (
    <ActionBarPrimitive.Root
      hideWhenRunning
      autohide="not-last"
      className="aui-user-action-bar-root flex flex-col items-end"
    >
      <ActionBarPrimitive.Edit
        render={
          <Button
            variant="ghost"
            size="icon"
            className="aui-user-action-edit size-7 text-muted-foreground hover:text-foreground"
            aria-label="Edit"
          />
        }
      >
        <PencilIcon className="size-3.5" />
      </ActionBarPrimitive.Edit>
    </ActionBarPrimitive.Root>
  );
};

const EditComposer: FC = () => {
  const readiness = useRunReadiness();
  return (
    <MessagePrimitive.Root
      data-slot="aui_edit-composer-wrapper"
      className="flex flex-col px-2 [contain-intrinsic-size:auto_200px] [content-visibility:auto]"
    >
      <ComposerPrimitive.Root className="aui-edit-composer-root border-border/60 dark:border-muted-foreground/15 ms-auto flex w-full max-w-[85%] cursor-text flex-col rounded-(--composer-radius) border bg-(--composer-bg)">
        <ComposerPrimitive.Input
          className="aui-edit-composer-input text-foreground min-h-14 w-full resize-none bg-transparent px-4 pt-3 pb-1 text-base outline-none"
          autoFocus
          submitMode={readiness.ready ? "enter" : "none"}
          name="edited-message"
          id="edited-message-input"
        />
        <div className="aui-edit-composer-footer mx-2.5 mb-2.5 flex items-center gap-1.5 self-end">
          <ComposerPrimitive.Cancel
            render={
              <Button
                variant="ghost"
                size="sm"
                className="h-8 rounded-full px-3.5"
              >
                Cancel
              </Button>
            }
          >
            Cancel
          </ComposerPrimitive.Cancel>
          <ComposerPrimitive.Send
            disabled={!readiness.ready}
            render={
              <Button size="sm" className="h-8 rounded-full px-3.5" title={readiness.ready ? undefined : readiness.message}>
                Update
              </Button>
            }
          >
            Update
          </ComposerPrimitive.Send>
        </div>
      </ComposerPrimitive.Root>
    </MessagePrimitive.Root>
  );
};

const BranchPicker: FC<BranchPickerPrimitive.Root.Props> = ({
  className,
  ...rest
}) => {
  return (
    <BranchPickerPrimitive.Root
      hideWhenSingleBranch
      className={cn(
        "aui-branch-picker-root text-muted-foreground inline-flex items-center gap-0.5 rounded-full border border-border/40 bg-surface-2/60 px-1 py-0.5 text-xs shadow-2xs",
        className,
      )}
      {...rest}
    >
      <BranchPickerPrimitive.Previous
        render={
          <Button
            variant="ghost"
            size="icon"
            className="size-5 rounded-full text-muted-foreground hover:text-foreground p-0"
            aria-label="Previous version"
          />
        }
      >
        <ChevronLeftIcon className="size-3" />
      </BranchPickerPrimitive.Previous>
      <span className="aui-branch-picker-state font-mono text-[11px] px-1 font-medium">
        <BranchPickerPrimitive.Number /> / <BranchPickerPrimitive.Count />
      </span>
      <BranchPickerPrimitive.Next
        render={
          <Button
            variant="ghost"
            size="icon"
            className="size-5 rounded-full text-muted-foreground hover:text-foreground p-0"
            aria-label="Next version"
          />
        }
      >
        <ChevronRightIcon className="size-3" />
      </BranchPickerPrimitive.Next>
    </BranchPickerPrimitive.Root>
  );
};
