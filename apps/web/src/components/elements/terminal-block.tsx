"use client";

import { CheckIcon, CopyIcon } from "lucide-react";
import {
  type ComponentProps,
  type ReactNode,
  useCallback,
  useState,
} from "react";

import { cn } from "@/lib/utils";
import { useShape } from "@/lib/shape-context";
import { codeScroll, codeSurface, mono, paper } from "@/lib/surfaces";

interface TerminalBlockProps
  extends Omit<ComponentProps<"div">, "title"> {
  /** Window title shown in the header bar. */
  title?: ReactNode;
  /** Text copied by the header's copy button. Defaults to the rendered body. */
  copyText?: string;
  /** Children render inside the scroll region. Keep it as inline `<pre>`-style content. */
  children: ReactNode;
  /** Hide the header bar (and its copy button) entirely. */
  bare?: boolean;
}

/**
 * Framed code/terminal surface: header bar with title and copy button, body
 * that scrolls horizontally to keep its whitespace. Uses the project's
 * `paper` surface and `mono` font tokens so it sits inside the design
 * system rather than overriding it.
 */
export function TerminalBlock({
  title,
  copyText,
  children,
  bare = false,
  className,
  ...props
}: TerminalBlockProps) {
  // Nested code surface: the shape ladder's middle (`mergedBg`) step, so it
  // reads between the 8px rows and the 20px stream cards in pill mode.
  const shape = useShape()
  return (
    <div
      data-slot="terminal-block"
      className={cn(paper, shape.mergedBg, !bare && "overflow-hidden", className)}
      {...props}
    >
      {!bare && (
        <TerminalHeader title={title} copyText={copyText} children={children} />
      )}
      <div className={cn(codeScroll, "max-w-full")}>
        <div className={cn(codeSurface, mono, "px-3 py-2")}>{children}</div>
      </div>
    </div>
  );
}

function TerminalHeader({
  title,
  copyText,
  children,
}: {
  title: ReactNode;
  copyText?: string;
  children: ReactNode;
}) {
  const [copied, setCopied] = useState(false);
  const onCopy = useCallback(() => {
    const text = copyText ?? extractText(children);
    if (!text) return;
    void navigator.clipboard
      .writeText(text)
      .then(() => {
        setCopied(true);
        setTimeout(() => setCopied(false), 1500);
      })
      .catch(() => {
        /* ignore — clipboard permission denied */
      });
  }, [copyText, children]);

  return (
    <div className="flex items-center justify-between gap-2 border-b border-border/60 bg-muted/30 px-2.5 py-1">
      <div className="flex min-w-0 items-center gap-1.5">
        <span
          aria-hidden
          className="flex shrink-0 items-center gap-1"
        >
          <span className="size-2 rounded-full bg-muted-foreground/30" />
          <span className="size-2 rounded-full bg-muted-foreground/30" />
          <span className="size-2 rounded-full bg-muted-foreground/30" />
        </span>
        {title && (
          <span className="truncate text-xs font-medium text-muted-foreground">
            {title}
          </span>
        )}
      </div>
      <button
        type="button"
        onClick={onCopy}
        aria-label={copied ? "Copied" : "Copy terminal contents"}
        className="flex size-5 shrink-0 items-center justify-center rounded text-muted-foreground transition-colors hover:bg-muted hover:text-foreground motion-reduce:transition-none"
      >
        {copied ? (
          <CheckIcon className="size-3" />
        ) : (
          <CopyIcon className="size-3" />
        )}
      </button>
    </div>
  );
}

function extractText(node: ReactNode): string {
  if (node == null || typeof node === "boolean") return "";
  if (typeof node === "string" || typeof node === "number") return String(node);
  if (Array.isArray(node)) return node.map(extractText).join("");
  if (typeof node === "object" && "props" in node) {
    const props = (node as { props: { children?: ReactNode } }).props;
    return extractText(props.children);
  }
  return "";
}
