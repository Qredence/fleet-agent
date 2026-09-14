"use client";

import { type ComponentProps } from "react";
import { ChevronDownIcon } from "lucide-react";
import { cn } from "@/lib/utils";
import { field, ghostButton, mono } from "@/lib/surfaces";
import { surfaceClasses } from "@/lib/surface-classes";
import { clamp, pct } from "@/lib/range";



export interface ComposerUsage {
  system: number;
  tools: number;
  messages: number;
  total: number;
  estimated?: boolean;
  description?: string;
}



/**
 * Renders the outer container for a message composer.
 *
 * @param className - Additional CSS classes for the container
 * @returns The composer container element
 */
export function Composer({ className, ...props }: ComponentProps<"div">) {
  return (
    <div
      data-slot="composer"
      className={cn("relative w-full max-w-lg", className)}
      {...props}
    />
  );
}



/**
 * Renders a selectable button within a composer menu.
 *
 * @param active - Whether the menu item is currently highlighted.
 */
export function ComposerMenuItem({
  active = false,
  className,
  ...props
}: ComponentProps<"button"> & { active?: boolean }) {
  return (
    <button
      type="button"
      data-slot="composer-menu-item"
      data-active={active || undefined}
      className={cn(
        "flex w-full items-center gap-2.5 rounded-[10px] px-2.5 py-2 text-[13.5px] transition-colors",
        active ? field : "hover:bg-foreground/[0.04]",
        className,
      )}
      {...props}
    />
  );
}



/**
 * Groups composer attachment elements in a wrapping layout.
 */
export function ComposerAttachments({
  className,
  ...props
}: ComponentProps<"div">) {
  return (
    <div
      data-slot="composer-attachments"
      className={cn("flex flex-wrap gap-2", className)}
      {...props}
    />
  );
}



/**
 * Renders a button that displays the selected model and its expanded state.
 *
 * @param model - The model name displayed by the button
 * @param open - Whether the associated model menu is expanded
 */
export function ComposerModelTrigger({
  model,
  open,
  className,
  ...props
}: Omit<ComponentProps<"button">, "children"> & {
  model: string;
  open: boolean;
}) {
  return (
    <button
      type="button"
      aria-expanded={open}
      data-slot="composer-model-trigger"
      className={cn(
        "text-foreground/55 hover:bg-foreground/[0.06] hover:text-foreground/90 dark:hover:bg-foreground/[0.09] flex h-8 items-center gap-1.5 rounded-full px-3 text-[12.5px] transition-colors",
        className,
      )}
      {...props}
    >
      {model}
      <ChevronDownIcon className="size-3 opacity-60" />
    </button>
  );
}



/**
 * Displays context usage as a progress indicator with a detailed breakdown.
 *
 * @param usage - Context usage totals and optional display metadata
 */
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
