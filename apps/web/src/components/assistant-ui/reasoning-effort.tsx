"use client";

import { useRef, type ComponentProps } from "react";
import { BrainIcon } from "lucide-react";
import { cn } from "@/lib/utils";
import { field, mono } from "@/lib/surfaces";
import { pct } from "@/lib/range";

const fmt = (n: number) => n.toLocaleString("en-US");

export interface ReasoningEffortLevel<TKey extends string = string> {
  key: TKey;
  label: string;
  description?: string;
  budget?: number;
}

export function ReasoningEffort<TKey extends string = string>({
  levels,
  selectedKey,
  spent,
  onSelect,
  className,
  ...props
}: Omit<
  ComponentProps<"div">,
  "children" | "levels" | "selectedKey" | "spent" | "onSelect"
> & {
  levels: readonly ReasoningEffortLevel<TKey>[];
  selectedKey: TKey;
  spent?: number;
  onSelect?: (key: TKey) => void;
}) {
  const optionRefs = useRef<(HTMLButtonElement | null)[]>([]);
  const selected = levels.find((level) => level.key === selectedKey);
  const budget = selected?.budget ?? 0;
  const hasBudget = budget > 0 && spent !== undefined && spent >= 0;
  const used = hasBudget ? pct(spent, budget) : 0;

  return (
    <div
      data-slot="reasoning-effort"
      className={cn("flex w-full flex-col gap-2", className)}
      {...props}
    >
      <div className="flex items-center justify-between px-0.5">
        <span className="flex items-center gap-1.5 text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
          <BrainIcon className="size-3" />
          Reasoning effort
        </span>
        {hasBudget ? (
          <span className={cn(mono, "text-foreground/35 tabular-nums text-[10px]")}>
            {fmt(spent)} / {fmt(budget)}
          </span>
        ) : (
          <span className="text-[10px] text-muted-foreground">
            {selected?.description}
          </span>
        )}
      </div>

      <div
        role="radiogroup"
        aria-label="Reasoning effort"
        className={cn(field, "flex gap-0.5 rounded-lg p-0.5 border border-border/40")}
      >
        {levels.map((level) => {
          const active = level.key === selectedKey;
          const buttonClass = cn(
            "flex-1 rounded-md py-1.5 text-xs font-medium transition-[background-color,color,scale] duration-150 text-center",
            onSelect && "active:scale-[0.97]",
            active
              ? "bg-background text-foreground shadow-xs font-semibold"
              : onSelect
                ? "text-foreground/50 hover:text-foreground/80 hover:bg-foreground/[0.04]"
                : "text-foreground/50",
          );
          return onSelect ? (
            <button
              key={level.key}
              type="button"
              role="radio"
              aria-checked={active}
              tabIndex={active ? 0 : -1}
              ref={(node) => {
                optionRefs.current[levels.indexOf(level)] = node;
              }}
              onClick={() => onSelect(level.key)}
              onKeyDown={(event) => {
                const next =
                  event.key === "ArrowRight" || event.key === "ArrowDown";
                const previous =
                  event.key === "ArrowLeft" || event.key === "ArrowUp";
                if ((!next && !previous) || levels.length === 0) return;

                event.preventDefault();
                const currentIndex = levels.findIndex(
                  (option) => option.key === level.key
                );
                const step = next ? 1 : -1;
                const nextIndex =
                  (currentIndex + step + levels.length) % levels.length;
                onSelect(levels[nextIndex].key);
                optionRefs.current[nextIndex]?.focus();
              }}
              className={buttonClass}
              title={level.description}
            >
              {level.label}
            </button>
          ) : (
            <span
              key={level.key}
              aria-current={active ? "true" : undefined}
              className={buttonClass}
              title={level.description}
            >
              {level.label}
            </span>
          );
        })}
      </div>

      {hasBudget && (
        <span
          role="progressbar"
          aria-label="Thinking budget used"
          aria-valuemin={0}
          aria-valuemax={100}
          aria-valuenow={Math.round(used)}
          aria-valuetext={`${fmt(spent)} of ${fmt(budget)}`}
          className="bg-foreground/[0.06] h-[3px] w-full overflow-hidden rounded-full"
        >
          <span
            className="block h-full rounded-full bg-blue-500 transition-[width] duration-500 motion-reduce:transition-none dark:bg-blue-400"
            style={{ width: `${used}%` }}
          />
        </span>
      )}
    </div>
  );
}
