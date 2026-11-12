import { useHasAgUiRuntime } from "./ag-ui-presence";
import { useAgUiState } from "@assistant-ui/react-ag-ui";
import type { AgentWorkspaceState } from "@/contracts/generated";
import { UnsavedAnswer } from "@/features/process-panel/run-activity-inline";
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
