import { useAuiState } from "@assistant-ui/react";
import { useAgUiState } from "@assistant-ui/react-ag-ui";
import { useHasAgUiRuntime } from "./ag-ui-presence";
import type { AgentWorkspaceState } from "@/contracts/generated";

export function UnsavedAnswer() {
  const answer = useAuiState(
    (state) =>
      state.thread.messages
        .filter((message) => message.role === "assistant")
        .at(-1)
        ?.content.filter((part) => part.type === "text")
        .map((part) => (part.type === "text" ? part.text : ""))
        .join("\n") ?? "",
  );
  const download = () => {
    const url = URL.createObjectURL(
      new Blob([answer], { type: "text/markdown;charset=utf-8" }),
    );
    const link = document.createElement("a");
    link.href = url;
    link.download = "fleet-agent-answer.md";
    document.body.appendChild(link);
    link.click();
    link.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  };
  return (
    <div role="alert" className="mb-3 rounded border border-amber-500/30 p-3 text-sm">
      <p>Saving failed. Reloading may lose this answer and its process state.</p>
      <button
        type="button"
        onClick={() => {
          navigator.clipboard?.writeText(answer).catch(() => {});
        }}
        className="me-3 underline"
      >
        Copy answer
      </button>
      <button type="button" onClick={download} className="underline">
        Download Markdown
      </button>
    </div>
  );
}

export function RunSaveNotice() {
  return useHasAgUiRuntime() ? <LiveSaveNotice /> : null;
}
function LiveSaveNotice() {
  const state = useAgUiState<AgentWorkspaceState>();
  const run = state?.run;
  const evidence = run?.evidenceStatus;
  const evidenceNotice =
    evidence && evidence !== "complete" ? (
      <p role="status" className="text-xs text-muted-foreground">
        {evidence === "partial"
          ? "Evidence collection stopped early."
          : "Evidence is insufficient for external verification."}
      </p>
    ) : null;
  if (run?.saveStatus === "failed")
    return (
      <>
        {evidenceNotice}
        <UnsavedAnswer />
      </>
    );
  if (run?.saveStatus === "saved")
    return (
      <>
        {evidenceNotice}
        <p role="status" className="text-xs text-muted-foreground">
          Saved
        </p>
      </>
    );
  if (run?.saveStatus === "pending" && run.status === "completed")
    return (
      <p role="status" className="text-xs text-muted-foreground">
        Saving answer…
      </p>
    );
  return evidenceNotice;
}
