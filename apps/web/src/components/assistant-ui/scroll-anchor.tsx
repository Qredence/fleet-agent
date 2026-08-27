"use client";

import {
  ThreadPrimitive,
  useAuiState,
  useThreadViewport,
} from "@assistant-ui/react";
import { ArrowDownIcon } from "lucide-react";
import { useEffect, useRef } from "react";

import { TooltipIconButton } from "@/components/assistant-ui/tooltip-icon-button";
import { cn } from "@/lib/utils";

/**
 * Scroll-to-bottom anchor with a "N new" badge for messages that arrive
 * while the user is scrolled up. Hides entirely when at the bottom of
 * the thread, matching the rest of the message group's behavior.
 *
 * The unread count is tracked in a ref because the viewport store does
 * not expose one. The reference count is taken when the user scrolls away
 * from the bottom, and reset to 0 when they return to the bottom (via the
 * click handler).
 */
export function ScrollAnchor() {
  const messageCount = useAuiState((s) => s.thread.messages.length);
  const isAtBottom = useThreadViewport((s) => s.isAtBottom);
  const lastSeenCountRef = useRef(messageCount);
  const lastEmittedCountRef = useRef(0);
  const isAtBottomRef = useRef(isAtBottom);

  // When the user scrolls up, lock the current message count as the
  // baseline. New messages from this point on count as "unread".
  useEffect(() => {
    if (isAtBottom) {
      lastSeenCountRef.current = messageCount;
    }
  }, [isAtBottom, messageCount]);

  // Keep ref in sync so the click handler can read the latest value
  // without re-binding the action button's onClick.
  useEffect(() => {
    isAtBottomRef.current = isAtBottom;
  }, [isAtBottom]);

  const unread = isAtBottom ? 0 : Math.max(0, messageCount - lastSeenCountRef.current);
  const showBadge = unread > 0;
  // Track last emitted count so the badge only animates in when it changes.
  if (lastEmittedCountRef.current !== unread) {
    lastEmittedCountRef.current = unread;
  }

  return (
    <ThreadPrimitive.ScrollToBottom
      render={
        <TooltipIconButton
          tooltip={showBadge ? `Scroll to bottom (${unread} new)` : "Scroll to bottom"}
          variant="outline"
          className={cn(
            "aui-thread-scroll-to-bottom dark:border-border dark:bg-background dark:hover:bg-accent",
            "absolute -top-12 z-10 self-center rounded-full p-4 disabled:invisible",
          )}
        />
      }
    >
      <span className="relative inline-flex items-center justify-center">
        <ArrowDownIcon
          className={cn(
            showBadge &&
              "motion-safe:animate-in motion-safe:fade-in motion-safe:zoom-in-50 motion-safe:duration-200",
          )}
        />
        {showBadge && (
          <span
            aria-hidden
            className={cn(
              "absolute -top-2 -end-3 min-w-4 rounded-full bg-primary px-1 text-[10px] font-medium leading-4 text-primary-foreground tabular-nums",
              "motion-safe:animate-in motion-safe:fade-in motion-safe:zoom-in-50 motion-safe:duration-200",
            )}
          >
            {unread}
          </span>
        )}
      </span>
    </ThreadPrimitive.ScrollToBottom>
  );
}
