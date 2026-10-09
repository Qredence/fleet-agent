import { createContext, useContext } from "react";
import { useAuiState } from "@assistant-ui/react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { ThumbsUp, ThumbsDown, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import type { MessageFeedback } from "@/contracts/message-feedback";
import { apiFetch, apiJsonFetch } from "@/lib/api-client";
import { queryClient } from "@/lib/query-client";

export const FeedbackThreadContext = createContext<string | undefined>(
  undefined,
);

export function MessageFeedbackControls() {
  const threadId = useContext(FeedbackThreadContext);
  return threadId ? <PersistedFeedback threadId={threadId} /> : null;
}

function PersistedFeedback({ threadId }: { threadId: string }) {
  const messageId = useAuiState((state) => state.message.id);
  const running = useAuiState((state) => state.message.status?.type === "running");
  const key = ["message-feedback", threadId];
  const feedback = useQuery(
    {
      queryKey: key,
      queryFn: () =>
        apiFetch<Record<string, MessageFeedback>>(
          `/api/threads/${threadId}/feedback`,
        ),
    },
    queryClient,
  );
  const selected = feedback.data?.[messageId]?.type;
  const write = useMutation(
    {
      mutationFn: (type: "positive" | "negative" | null) =>
        type
          ? apiJsonFetch(
              `/api/threads/${threadId}/messages/${encodeURIComponent(messageId)}/feedback`,
              "PUT",
              { messageId, type },
            )
          : apiFetch(
              `/api/threads/${threadId}/messages/${encodeURIComponent(messageId)}/feedback`,
              { method: "DELETE" },
            ),
      onSuccess: () => queryClient.invalidateQueries({ queryKey: key }),
    },
    queryClient,
  );
  return (
    <>
      <Button
        variant="ghost"
        size="icon"
        className="size-7 aria-pressed:bg-muted aria-pressed:text-primary"
        aria-label="Good response"
        aria-pressed={selected === "positive"}
        disabled={write.isPending || running}
        onClick={() => write.mutate("positive")}
      >
        <ThumbsUp className="size-3.5" />
      </Button>
      <Button
        variant="ghost"
        size="icon"
        className="size-7 aria-pressed:bg-muted aria-pressed:text-primary"
        aria-label="Bad response"
        aria-pressed={selected === "negative"}
        disabled={write.isPending || running}
        onClick={() => write.mutate("negative")}
      >
        <ThumbsDown className="size-3.5" />
      </Button>
      {selected && (
        <Button
          variant="ghost"
          size="icon"
          className="size-7 aria-pressed:bg-muted aria-pressed:text-primary"
          aria-label="Clear feedback"
          disabled={write.isPending || running}
          onClick={() => write.mutate(null)}
        >
          <X className="size-3.5" />
        </Button>
      )}
      {write.isError && (
        <p role="alert">Feedback could not be saved. Try again.</p>
      )}
      {feedback.isError && (
        <p role="alert">Saved feedback could not be loaded.</p>
      )}
    </>
  );
}
