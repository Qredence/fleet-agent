"use client";

import {
  createContext,
  useContext,
  useState,
  useEffect,
  type ReactNode,
} from "react";
import { Tooltip as TooltipPrimitive } from "@base-ui/react/tooltip";
import { motion, useMotionValue } from "framer-motion";
import { cn } from "@/lib/utils";
import { spring } from "@/lib/springs";
import { fontWeights } from "@/lib/font-weight";
import { useShape } from "@/lib/shape-context";

// ---------------------------------------------------------------------------
// Portal container context
// ---------------------------------------------------------------------------

const TooltipPortalContainerContext = createContext<HTMLElement | null>(null);

function TooltipPortalContainer({
  value,
  children,
}: {
  value: HTMLElement | null;
  children: ReactNode;
}) {
  return (
    <TooltipPortalContainerContext.Provider value={value}>
      {children}
    </TooltipPortalContainerContext.Provider>
  );
}

// ---------------------------------------------------------------------------
// Provider
// ---------------------------------------------------------------------------

const DEFAULT_DELAY = 200;
const TooltipGroupContext = createContext(false);

interface TooltipProviderProps {
  children: ReactNode;
  delayDuration?: number;
  skipDelayDuration?: number;
  delay?: number;
  timeout?: number;
}

function TooltipProvider({
  children,
  delayDuration,
  skipDelayDuration = 300,
  delay = 0,
  timeout,
  ...props
}: TooltipProviderProps & TooltipPrimitive.Provider.Props) {
  const actualDelay = delayDuration ?? delay ?? DEFAULT_DELAY;
  const actualTimeout = skipDelayDuration ?? timeout ?? 300;
  return (
    <TooltipGroupContext.Provider value={true}>
      <TooltipPrimitive.Provider
        data-slot="tooltip-provider"
        delay={actualDelay}
        timeout={actualTimeout}
        {...props}
      >
        {children}
      </TooltipPrimitive.Provider>
    </TooltipGroupContext.Provider>
  );
}

// ---------------------------------------------------------------------------
// Primitive components
// ---------------------------------------------------------------------------

function TooltipRoot({ ...props }: TooltipPrimitive.Root.Props) {
  return <TooltipPrimitive.Root data-slot="tooltip" {...props} />;
}

function TooltipTrigger({ ...props }: TooltipPrimitive.Trigger.Props) {
  return <TooltipPrimitive.Trigger data-slot="tooltip-trigger" {...props} />;
}

function TooltipContent({
  className,
  side = "top",
  sideOffset = 4,
  align = "center",
  alignOffset = 0,
  children,
  ...props
}: TooltipPrimitive.Popup.Props &
  Pick<
    TooltipPrimitive.Positioner.Props,
    "align" | "alignOffset" | "side" | "sideOffset"
  >) {
  return (
    <TooltipPrimitive.Portal>
      <TooltipPrimitive.Positioner
        align={align}
        alignOffset={alignOffset}
        side={side}
        sideOffset={sideOffset}
        className="isolate z-50"
      >
        <TooltipPrimitive.Popup
          data-slot="tooltip-content"
          className={cn(
            "z-50 inline-flex w-fit max-w-xs origin-(--transform-origin) items-center gap-1.5 rounded-md bg-foreground px-3 py-1.5 text-xs text-background has-data-[slot=kbd]:pr-1.5 data-[side=bottom]:slide-in-from-top-2 data-[side=inline-end]:slide-in-from-left-2 data-[side=inline-start]:slide-in-from-right-2 data-[side=left]:slide-in-from-right-2 data-[side=right]:slide-in-from-left-2 data-[side=top]:slide-in-from-bottom-2 **:data-[slot=kbd]:relative **:data-[slot=kbd]:isolate **:data-[slot=kbd]:z-50 **:data-[slot=kbd]:rounded-sm data-[state=delayed-open]:animate-in data-[state=delayed-open]:fade-in-0 data-[state=delayed-open]:zoom-in-95 data-open:animate-in data-open:fade-in-0 data-open:zoom-in-95 data-closed:animate-out data-closed:fade-out-0 data-closed:zoom-out-95",
            className
          )}
          {...props}
        >
          {children}
          <TooltipPrimitive.Arrow className="z-50 size-2.5 translate-y-[calc(-50%-2px)] rotate-45 rounded-[2px] bg-foreground fill-foreground data-[side=bottom]:top-1 data-[side=inline-end]:top-1/2! data-[side=inline-end]:-left-1 data-[side=inline-end]:-translate-y-1/2 data-[side=inline-start]:top-1/2! data-[side=inline-start]:-right-1 data-[side=inline-start]:-translate-y-1/2 data-[side=left]:top-1/2! data-[side=left]:-right-1 data-[side=left]:-translate-y-1/2 data-[side=right]:top-1/2! data-[side=right]:-left-1 data-[side=right]:-translate-y-1/2 data-[side=top]:-bottom-2.5" />
        </TooltipPrimitive.Popup>
      </TooltipPrimitive.Positioner>
    </TooltipPrimitive.Portal>
  );
}

// ---------------------------------------------------------------------------
// High-level Tooltip wrapper
// ---------------------------------------------------------------------------

type TooltipSide = "top" | "right" | "bottom" | "left";

interface CustomTooltipProps {
  content?: ReactNode;
  children?: ReactNode;
  side?: TooltipSide;
  sideOffset?: number;
  delayDuration?: number;
  className?: string;
  forceOpen?: boolean;
  followCursor?: "x" | "y";
  onOpenChange?: (open: boolean) => void;
}

function getSlideOffset(side: TooltipSide) {
  switch (side) {
    case "top":
      return { y: 4 };
    case "bottom":
      return { y: -4 };
    case "left":
      return { x: 4 };
    case "right":
      return { x: -4 };
  }
}

function Tooltip(props: TooltipPrimitive.Root.Props & CustomTooltipProps) {
  // If invoked as <Tooltip content="...">children</Tooltip>
  if ("content" in props && props.content !== undefined) {
    const {
      content,
      children,
      side = "top",
      sideOffset = 8,
      delayDuration,
      className,
      forceOpen,
      onOpenChange: onOpenChangeProp,
      followCursor,
      ...rootProps
    } = props as CustomTooltipProps;

    return (
      <CustomTooltipWrapper
        content={content}
        side={side}
        sideOffset={sideOffset}
        delayDuration={delayDuration}
        className={className}
        forceOpen={forceOpen}
        onOpenChange={onOpenChangeProp}
        followCursor={followCursor}
        {...rootProps}
      >
        {children as React.ReactElement}
      </CustomTooltipWrapper>
    );
  }

  // Standard Primitive Tooltip Root
  return <TooltipRoot {...props} />;
}

function CustomTooltipWrapper({
  content,
  children,
  side = "top",
  sideOffset = 8,
  delayDuration,
  className,
  forceOpen,
  onOpenChange: onOpenChangeProp,
  followCursor,
}: CustomTooltipProps & { children: React.ReactElement }) {
  const [internalOpen, setInternalOpen] = useState(false);
  const open = forceOpen !== undefined ? forceOpen : internalOpen;
  const shape = useShape();
  const portalContainer = useContext(TooltipPortalContainerContext);
  const hasAmbientProvider = useContext(TooltipGroupContext);

  const slideOffset = getSlideOffset(side);
  const followOffset = useMotionValue(0);

  useEffect(() => {
    if (forceOpen && followCursor) followOffset.set(0);
  }, [forceOpen, followCursor, followOffset]);

  const handleFollowMove = (event: React.PointerEvent) => {
    if (!followCursor) return;
    const rect = event.currentTarget.getBoundingClientRect();
    followOffset.set(
      followCursor === "y"
        ? event.clientY - (rect.top + rect.height / 2)
        : event.clientX - (rect.left + rect.width / 2)
    );
  };

  const tooltipElement = (
    <TooltipPrimitive.Root
      open={open}
      onOpenChange={(v) => {
        setInternalOpen(v);
        onOpenChangeProp?.(v);
      }}
    >
      <TooltipPrimitive.Trigger
        render={children}
        delay={delayDuration}
        onPointerMove={followCursor ? handleFollowMove : undefined}
      />
      <TooltipPrimitive.Portal container={portalContainer ?? undefined}>
        <TooltipPrimitive.Positioner
          side={side}
          sideOffset={sideOffset}
          className="z-50"
        >
          <TooltipPrimitive.Popup
            render={(popupProps, state) => {
              const exiting = state.transitionStatus === "ending";
              const {
                style: baseStyle,
                onDrag: _onDrag,
                onDragStart: _onDragStart,
                onDragEnd: _onDragEnd,
                onAnimationStart: _onAnimationStart,
                onAnimationEnd: _onAnimationEnd,
                onAnimationIteration: _onAnimationIteration,
                ...rest
              } = popupProps as React.HTMLAttributes<HTMLDivElement>;
              return (
                <motion.div
                  {...rest}
                  style={{
                    ...(baseStyle as React.CSSProperties | undefined),
                    ...(followCursor === "y"
                      ? { y: followOffset }
                      : followCursor === "x"
                        ? { x: followOffset }
                        : {}),
                  }}
                >
                  <motion.div
                    className={cn(
                      "bg-foreground text-background text-[12px] px-2 py-1",
                      shape.bg,
                      className
                    )}
                    style={{ fontVariationSettings: fontWeights.medium }}
                    initial={{ opacity: 0, ...slideOffset }}
                    animate={
                      exiting
                        ? { opacity: 0, ...slideOffset }
                        : { opacity: 1, x: 0, y: 0 }
                    }
                    transition={exiting ? spring.fast.exit : spring.fast}
                  >
                    {content}
                  </motion.div>
                </motion.div>
              );
            }}
          />
        </TooltipPrimitive.Positioner>
      </TooltipPrimitive.Portal>
    </TooltipPrimitive.Root>
  );

  if (hasAmbientProvider) return tooltipElement;

  return (
    <TooltipPrimitive.Provider delay={delayDuration ?? DEFAULT_DELAY}>
      {tooltipElement}
    </TooltipPrimitive.Provider>
  );
}

export {
  Tooltip,
  TooltipTrigger,
  TooltipContent,
  TooltipProvider,
  TooltipPortalContainer,
};
export type { TooltipProviderProps, TooltipSide };
