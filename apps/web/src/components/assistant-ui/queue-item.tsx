"use client";

import { XIcon } from "lucide-react";
import { type FC } from "react";

import {
  ComposerPrimitive,
  QueueItemPrimitive,
} from "@assistant-ui/react";

import { TooltipIconButton } from "@/components/assistant-ui/tooltip-icon-button";
import { cn } from "@/lib/utils";

/**
 * One pill per queued message. While a run is in flight, typed-and-sent
 * messages land here instead of being dropped. They auto-send in order when
 * the run finishes, or immediately via "Run now" (`Steer`).
 */
export const ComposerQueue: FC = () => (
  <ComposerPrimitive.Queue>
    {() => <QueuePill />}
  </ComposerPrimitive.Queue>
);

const QueuePill: FC = () => (
  <div
    data-slot="aui-composer-queue-item"
    className={cn(
      "border-border/60 bg-muted/30 text-muted-foreground",
      "motion-safe:animate-in motion-safe:fade-in motion-safe:slide-in-from-bottom-1 motion-safe:duration-150",
      "flex items-center gap-1.5 rounded-full border px-2 py-0.5 text-xs",
    )}
  >
    <QueueItemPrimitive.Text className="min-w-0 flex-1 truncate" />
    <QueueItemPrimitive.Steer
      render={
        <TooltipIconButton
          tooltip="Run now"
          variant="ghost"
          size="icon-xs"
          className="text-muted-foreground hover:text-foreground size-5 rounded-full"
          aria-label="Run now"
        />
      }
    >
      <span className="sr-only">Run now</span>
    </QueueItemPrimitive.Steer>
    <QueueItemPrimitive.Remove
      render={
        <TooltipIconButton
          tooltip="Remove from queue"
          variant="ghost"
          size="icon-xs"
          className="text-muted-foreground hover:text-foreground size-5 rounded-full"
          aria-label="Remove from queue"
        />
      }
    >
      <XIcon className="size-3" />
    </QueueItemPrimitive.Remove>
  </div>
);
