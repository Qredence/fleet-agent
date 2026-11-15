import { FeedbackThreadContext } from "./message-feedback-controls";
import { attachmentAdapter } from "./text-attachments";
export { attachmentAdapter } from "./text-attachments";
import { HttpAgent } from "@ag-ui/client";
import { AssistantRuntimeProvider } from "@assistant-ui/react";
import { useAgUiRuntime } from "@assistant-ui/react-ag-ui";
import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";

import {
  buildHistoryAdapter,
  HistoryHeadSync,
  type UserMessagePersistedHandler,
  waitForThreadHistoryWrites,
} from "@/features/threads/assistant-thread-adapter";
import {
  resolveRunTarget,
  runTargetSendsProviderHeaders,
} from "@/features/agent-runtime/run-target";
import { AgUiRuntimePresenceProvider } from "@/features/agent-runtime/ag-ui-presence";
import { ArtifactDataUIRegistration } from "@/features/artifacts/artifact-data-ui";
import { InlineAgentDataUIRegistration } from "@/features/agent-runtime/inline-agent-data-ui";
import type { ThreadBootstrap } from "@/features/threads/threads-api";
import { ApprovalContext } from "./tool-permissions";
import { API_BASE_URL, API_KEY } from "@/lib/env";
import { refreshAgentCapabilities } from "@/features/agent-runtime/agent-capabilities";
import type { AgentCapabilities } from "@/contracts/agent-capabilities";
import { getAgentProviderHeaders, getActiveProviderId, getProviderReadiness, ProviderNotReadyError } from "@/features/providers/providers-store";

const AGENT_URL = `${API_BASE_URL}/api/agent`;
const AGENT_PATHNAME = new URL(AGENT_URL).pathname;

function isAgentRunRequest(
  url: string | URL,
  requestInit: RequestInit,
): boolean {
  if (requestInit.method?.toUpperCase() !== "POST") return false;
  try {
    // Compare against the agent URL's own pathname so path-prefixed API
    // base URLs (e.g. VITE_API_BASE_URL="https://host/fleet") still match.
    return new URL(String(url), AGENT_URL).pathname === AGENT_PATHNAME;
  } catch {
    return String(url).split("?", 1)[0].endsWith(AGENT_PATHNAME);
  }
}

/** Add browser-owned provider headers only to the agent POST request. */
export function createAgentFetch(
  threadId?: string,
  getApprovals: () => string[] = () => [],
  onApprovalsCommitted?: (approvedTools: string[]) => void,
): (url: string, requestInit: RequestInit) => Promise<Response> {
  return async (url, requestInit) => {
    const isAgentRequest = isAgentRunRequest(url, requestInit);
    if (threadId && isAgentRequest) {
      await waitForThreadHistoryWrites(threadId);
    }
    const headers = new Headers(requestInit.headers);
    let sentApprovals: string[] = [];
    if (isAgentRequest) {
      // A failed capabilities lookup must not escape as a raw query error: the
      // route resolver owns that message, and an unresolved route has to fail
      // closed here rather than producing a run the server cannot serve.
      let capabilities: AgentCapabilities | undefined;
      let capabilitiesError = false;
      try {
        capabilities = await refreshAgentCapabilities();
      } catch (error) {
        // Keep the cause visible: the user sees the routed message, not this.
        console.error("[ag-ui] capabilities lookup failed", error);
        capabilitiesError = true;
      }
      // Never send stored credentials to fixture runs, including caller-supplied headers.
      const providerHeaderNames = Array.from(headers.keys()).filter((name) =>
        name.startsWith("x-llm-"),
      );
      for (const name of providerHeaderNames) headers.delete(name);
      // Only a verified route proceeds. A BYOK profile carries browser
      // credentials; fixture and server gateway runs must never receive a key
      // they would not use. An unresolved route (for example engine mode with
      // no browser profile and no confirmed server gateway) fails closed here
      // instead of producing a run the server cannot serve.
      const providerReadiness = getProviderReadiness();
      const target = resolveRunTarget({
        capabilitiesError,
        capabilities,
        providerReadiness,
        activeProviderId: getActiveProviderId(),
      });
      if (!target.ready) throw new ProviderNotReadyError(target.message);
      // Snapshot approvals only after capability and readiness preflight pass so
      // a blocked run never loses pending approvals.
      sentApprovals = [...getApprovals()];
      // Browser-owned provider profile headers (BYOK): only ever attached to
      // the agent run POST, never to other Fleet API resources.
      const body = JSON.parse(
        typeof requestInit.body === "string" ? requestInit.body : "{}",
      );
      body.forwardedProps = {
        ...body.forwardedProps,
        approvedTools: sentApprovals,
      };
      requestInit = { ...requestInit, body: JSON.stringify(body) };
      const providerHeaders = runTargetSendsProviderHeaders(target)
        ? getAgentProviderHeaders()
        : {};
      for (const [k, v] of Object.entries(providerHeaders)) {
        headers.set(k, v);
      }
    }
    const response = await fetch(url, { ...requestInit, headers });
    if (isAgentRequest && response.ok && sentApprovals.length > 0) {
      onApprovalsCommitted?.(sentApprovals);
    }
    return response;
  };
}

/**
 * Provides the AG-UI runtime for a workspace conversation.
 *
 * @param threadId - The persisted conversation identifier.
 * @param bootstrap - Initial state used to restore the conversation.
 * @param onUserMessagePersisted - Callback invoked after a user message is persisted.
 * @param children - Content rendered within the runtime provider.
 * @returns The runtime provider containing the workspace content.
 */
export function AgentRuntimeProvider({
  threadId,
  bootstrap,
  onUserMessagePersisted,
  children,
}: {
  threadId?: string;
  bootstrap?: ThreadBootstrap;
  onUserMessagePersisted?: UserMessagePersistedHandler;
  children: ReactNode;
}) {
  const onUserMessagePersistedRef = useRef(onUserMessagePersisted);

  useEffect(() => {
    onUserMessagePersistedRef.current = onUserMessagePersisted;
  }, [onUserMessagePersisted]);

  const [approved, setApproved] = useState<string[]>([]);
  const approvalRef = useRef(approved);
  approvalRef.current = approved;
  const agent = useMemo(
    () =>
      new HttpAgent({
        url: AGENT_URL,
        fetch: createAgentFetch(
          threadId,
          () => approvalRef.current,
          (committed) => {
            const committedSet = new Set(committed);
            const remaining = approvalRef.current.filter(
              (tool) => !committedSet.has(tool),
            );
            approvalRef.current = remaining;
            setApproved(remaining);
          },
        ),
        ...(API_KEY ? { headers: { "X-API-Key": API_KEY } } : {}),
      }),
    [threadId],
  );

  // Bind the agent's wire threadId to the URL thread. Without this the client
  // invents a fresh id and engine mode 404s (runs belong to persisted threads).
  useEffect(() => {
    if (threadId) {
      agent.threadId = threadId;
    }
  }, [agent, threadId]);

  const adapters = useMemo(
    () => ({
      attachments: attachmentAdapter,
      ...(threadId
        ? {
            history: buildHistoryAdapter(threadId, bootstrap, {
              onUserMessagePersisted: (message) =>
                onUserMessagePersistedRef.current?.(message),
            }),
          }
        : {}),
    }),
    // Bootstrap is fetched before this keyed provider mounts. Keep the
    // adapter identity stable after mount so cache invalidation from an
    // append/update cannot trigger a second runtime load.
    [threadId],
  );

  const runtime = useAgUiRuntime({
    agent,
    showThinking: false,
    adapters,
    unstable_enableMessageQueue: true,
    onError: (error) => {
      // Structured client error reporting arrives with observability (PR 9).
      console.error("[ag-ui] run error", error);
    },
    onCancel: () => {
      console.info("[ag-ui] run cancelled");
    },
  });

  return (
    <FeedbackThreadContext.Provider value={threadId}>
      <ApprovalContext.Provider value={{ approved, setApproved }}>
        <AssistantRuntimeProvider runtime={runtime}>
          <AgUiRuntimePresenceProvider>
            <ArtifactDataUIRegistration />
            <InlineAgentDataUIRegistration />
            {threadId ? (
              <HistoryHeadSync
                threadId={threadId}
                initialHeadId={bootstrap?.messageRepository?.headId ?? null}
              />
            ) : null}
            {children}
          </AgUiRuntimePresenceProvider>
        </AssistantRuntimeProvider>
      </ApprovalContext.Provider>
    </FeedbackThreadContext.Provider>
  );
}
