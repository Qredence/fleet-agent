import { queryClient } from "@/lib/query-client";
import { createContext, useContext } from "react";
import { useQuery } from "@tanstack/react-query";
import { fetchTools } from "@/features/tools/tools-api";
export const ApprovalContext = createContext<{
  approved: string[];
  setApproved: (names: string[]) => void;
}>({ approved: [], setApproved: () => {} });
export function ToolPermissions() {
  const { approved, setApproved } = useContext(ApprovalContext);
  const catalog = useQuery(
    { queryKey: ["tools"], queryFn: fetchTools },
    queryClient,
  );
  const tools = catalog.data?.filter((tool) => tool.requires_approval) ?? [];
  if (!tools.length) return null;
  return (
    <details className="relative text-xs">
      <summary className="cursor-pointer rounded p-1">
        Tool permissions{approved.length ? ` (${approved.length})` : ""}
      </summary>
      <fieldset className="absolute bottom-full z-20 mb-2 w-72 rounded border bg-background p-3 shadow">
        <legend>Allow tools for the next run</legend>
        <p className="mb-2">
          These tools can change workspace files or execute commands. Selection
          resets after sending.
        </p>
        {tools.map((tool) => (
          <label key={tool.name} className="block py-1">
            <input
              type="checkbox"
              checked={approved.includes(tool.name)}
              onChange={(event) =>
                setApproved(
                  event.target.checked
                    ? [...approved, tool.name]
                    : approved.filter((name) => name !== tool.name),
                )
              }
            />{" "}
            {tool.name}
            <span className="block text-muted-foreground">
              {tool.description}
            </span>
          </label>
        ))}
      </fieldset>
    </details>
  );
}
