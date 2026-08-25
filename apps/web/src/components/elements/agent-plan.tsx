"use client";

import type { ComponentProps } from "react";
import { CheckIcon, Loader2Icon } from "lucide-react";
import { cn } from "@/lib/utils";
import { pct, progressOf } from "@/lib/range";
import { mono } from "@/lib/surfaces";

export type AgentPlanStepStatus =
  | "pending"
  | "running"
  | "completed"
  | "failed"
  | "skipped";

export function AgentPlan({
  steps,
  activeIndex,
  statuses,
  className,
  ...props
}: Omit<
  ComponentProps<"div">,
  "children" | "steps" | "activeIndex" | "statuses"
> & {
  steps: readonly string[];
  activeIndex: number;
  statuses?: readonly AgentPlanStepStatus[];
}) {
  const total = steps.length;
  const completed = statuses
    ? statuses.filter((status) => status === "completed").length
    : progressOf(activeIndex, total);
  const allDone = statuses
    ? statuses.every((status) =>
        ["completed", "failed", "skipped"].includes(status),
      )
    : completed >= total;
  const progress = pct(completed, total);

  return (
    <div
      data-slot="agent-plan"
      className={cn("flex w-full max-w-sm flex-col gap-3", className)}

      {...props}
    >
      <div className="flex items-center justify-between">
        <span className="text-[13.5px] font-medium">Plan</span>
        <span className={cn(mono, "text-foreground/35 tabular-nums")}>
          {completed} of {total}
        </span>
      </div>
      <div className="bg-foreground/[0.06] h-[3px] w-full overflow-hidden rounded-full">
        <span
          className="bg-foreground/80 block h-full rounded-full transition-[width] duration-500"
          style={{ width: `${progress}%` }}
        />
      </div>
      <ul className="flex flex-col gap-2.5">
        {steps.map((step, i) => {
          const status = statuses?.[i];
          const done = status
            ? status === "completed"
            : allDone || i < completed;
          const active = status
            ? status === "running"
            : !allDone && i === completed;
          const failed = status === "failed";
          const skipped = status === "skipped";
          return (
            <li key={`${i}-${step}`} className="flex items-center gap-2.5 text-[13.5px]">
              <span className="flex size-4 shrink-0 items-center justify-center">
                {done ? (
                  <CheckIcon className="text-foreground/35 size-3.5" />
                ) : failed ? (
                  <span className="text-destructive text-xs font-semibold">×</span>
                ) : skipped ? (
                  <span className="text-muted-foreground text-[10px]">—</span>
                ) : active ? (
                  <Loader2Icon className="text-foreground/90 size-3.5 animate-spin motion-reduce:animate-none" />
                ) : (
                  <span
                    aria-hidden
                    className="bg-foreground/15 size-1.5 rounded-full"
                  />
                )}
              </span>
              <span
                className={cn(
                  done && "text-foreground/40",
                  active && "text-foreground/90",
                  failed && "text-destructive",
                  skipped && "text-muted-foreground",
                  !done && !active && "text-foreground/35",
                )}
              >
                {step}
              </span>
            </li>
          );
        })}
      </ul>
    </div>
  );
}
