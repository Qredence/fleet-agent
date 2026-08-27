"use client";

import {
  cloneElement,
  forwardRef,
  isValidElement,
  type ButtonHTMLAttributes,
  type ReactElement,
  type ReactNode,
} from "react";
import { Button as ButtonPrimitive } from "@base-ui/react/button";
import { cva, type VariantProps } from "class-variance-authority";
import type { IconComponent } from "@/lib/icon-context";
import { cn } from "@/lib/utils";
import { useShape } from "@/lib/shape-context";
import { useSizeVariant } from "@/lib/size-context";

const buttonVariants = cva(
  [
    "group relative isolate inline-flex items-center justify-center outline-none cursor-pointer",
    "transition-[color,background-color,border-color,transform] [transition-duration:80ms,80ms,80ms,150ms] [transition-timing-function:cubic-bezier(0.23,1,0.32,1)] active:scale-[0.96] motion-reduce:transition-none",
    "disabled:opacity-50 disabled:pointer-events-none",
    "aria-disabled:opacity-50 aria-disabled:pointer-events-none",
    "focus-visible:ring-1 focus-visible:ring-[color:var(--focus-ring,#6B97FF)]",
  ],
  {
    variants: {
      variant: {
        primary: "text-background",
        default: "text-background",
        secondary: "text-foreground",
        tertiary: "text-foreground",
        outline: "text-foreground",
        ghost: "text-muted-foreground hover:text-foreground",
        destructive: "text-destructive-foreground",
      },
      size: {
        default: "h-9 px-4 text-[13px] gap-1.5",
        compact: "h-7 px-3 text-[12px] gap-1",
        sm: "h-7 px-3 text-[12px] gap-1",
        md: "h-9 px-4 text-[13px] gap-1.5",
        lg: "h-10 px-5 text-sm gap-2",
        icon: "h-9 w-9 p-0 [&_svg]:h-4 [&_svg]:w-4",
        "icon-compact": "h-7 w-7 p-0 [&_svg]:h-3.5 [&_svg]:w-3.5",
        "icon-xs": "h-6 w-6 p-0 [&_svg]:h-3 [&_svg]:w-3",
        "icon-sm": "h-7 w-7 p-0 [&_svg]:h-3.5 [&_svg]:w-3.5",
        "icon-lg": "h-9 w-9 p-0 [&_svg]:h-4 [&_svg]:w-4",
      },
      iconLeft: { true: "" },
      iconRight: { true: "" },
    },
    compoundVariants: [
      { size: "compact", iconLeft: true, className: "pl-[6px]" },
      { size: "default", iconLeft: true, className: "pl-[10px]" },
      { size: "compact", iconRight: true, className: "pr-[6px]" },
      { size: "default", iconRight: true, className: "pr-[10px]" },
    ],
    defaultVariants: {
      variant: "primary",
      size: "default",
    },
  }
);

type ButtonSizeCanonical =
  | "default"
  | "compact"
  | "sm"
  | "md"
  | "lg"
  | "icon"
  | "icon-compact"
  | "icon-xs"
  | "icon-sm"
  | "icon-lg";

type ButtonSize = ButtonSizeCanonical;

interface ButtonProps
  extends ButtonHTMLAttributes<HTMLButtonElement>,
    Omit<VariantProps<typeof buttonVariants>, "size" | "variant"> {
  variant?:
    | "primary"
    | "default"
    | "secondary"
    | "tertiary"
    | "outline"
    | "ghost"
    | "destructive"
    | null;
  size?: ButtonSize;
  asChild?: boolean;
  render?: ReactElement;
  nativeButton?: boolean;
  role?: string;
  loading?: boolean;
  leadingIcon?: IconComponent;
  trailingIcon?: IconComponent;
  active?: boolean;
}

const bgVariants: Record<string, string> = {
  primary:
    "[--btn-bg:var(--foreground)] group-hover:[--btn-bg:color-mix(in_oklab,var(--foreground)_90%,var(--background))] group-active:[--btn-bg:color-mix(in_oklab,var(--foreground)_80%,var(--background))] bg-[var(--btn-bg)] shadow-[0_0_0_1px_var(--btn-bg)] group-active:shadow-[0_0_0_0px_var(--btn-bg)]",
  default:
    "[--btn-bg:var(--foreground)] group-hover:[--btn-bg:color-mix(in_oklab,var(--foreground)_90%,var(--background))] group-active:[--btn-bg:color-mix(in_oklab,var(--foreground)_80%,var(--background))] bg-[var(--btn-bg)] shadow-[0_0_0_1px_var(--btn-bg)] group-active:shadow-[0_0_0_0px_var(--btn-bg)]",
  destructive:
    "[--btn-bg:var(--color-destructive,red)] bg-destructive text-destructive-foreground shadow-[0_0_0_1px_var(--destructive)] group-hover:bg-destructive/90",
  secondary:
    "[--btn-bg:var(--accent)] group-hover:[--btn-bg:color-mix(in_oklab,var(--accent)_80%,var(--background))] group-active:[--btn-bg:var(--accent)] bg-[var(--btn-bg)] shadow-[0_0_0_1px_var(--btn-bg)] group-active:shadow-[0_0_0_0px_var(--btn-bg)]",
  tertiary:
    "bg-transparent shadow-[0_0_0_1px_var(--border),inset_0_0_0_0px_var(--border)] group-hover:bg-hover group-active:bg-active group-active:shadow-[0_0_0_0px_var(--border),inset_0_0_0_1px_var(--border)]",
  outline:
    "bg-transparent shadow-[0_0_0_1px_var(--border),inset_0_0_0_0px_var(--border)] group-hover:bg-hover group-active:bg-active group-active:shadow-[0_0_0_0px_var(--border),inset_0_0_0_1px_var(--border)]",
  ghost:
    "bg-transparent shadow-[0_0_0_1px_transparent] group-hover:bg-hover group-hover:shadow-[0_0_0_1px_var(--hover)] group-active:bg-active group-active:shadow-[0_0_0_0px_var(--active)]",
};

const activeBgVariants: Record<string, string> = {
  primary:
    "[--btn-bg:color-mix(in_oklab,var(--foreground)_80%,var(--background))] bg-[var(--btn-bg)] shadow-[0_0_0_1px_var(--btn-bg)] group-active:shadow-[0_0_0_0px_var(--btn-bg)]",
  default:
    "[--btn-bg:color-mix(in_oklab,var(--foreground)_80%,var(--background))] bg-[var(--btn-bg)] shadow-[0_0_0_1px_var(--btn-bg)] group-active:shadow-[0_0_0_0px_var(--btn-bg)]",
  destructive:
    "bg-destructive/90 text-destructive-foreground shadow-[0_0_0_1px_var(--destructive)]",
  secondary:
    "[--btn-bg:var(--accent)] bg-[var(--btn-bg)] shadow-[0_0_0_1px_var(--btn-bg)] group-active:shadow-[0_0_0_0px_var(--btn-bg)]",
  tertiary:
    "bg-active shadow-[0_0_0_1px_var(--border),inset_0_0_0_0px_var(--border)] group-active:shadow-[0_0_0_0px_var(--border),inset_0_0_0_1px_var(--border)]",
  outline:
    "bg-active shadow-[0_0_0_1px_var(--border),inset_0_0_0_0px_var(--border)] group-active:shadow-[0_0_0_0px_var(--border),inset_0_0_0_1px_var(--border)]",
  ghost:
    "bg-active shadow-[0_0_0_1px_var(--active)] group-active:shadow-[0_0_0_0px_var(--active)]",
};

const Button = forwardRef<HTMLButtonElement, ButtonProps>(
  (
    {
      className,
      variant = "primary",
      size,
      asChild = false,
      render,
      nativeButton: _nativeButton,
      loading = false,
      leadingIcon: LeadingIcon,
      trailingIcon: TrailingIcon,
      active = false,
      disabled,
      children,
      style,
      ...props
    },
    ref
  ) => {
    const asChildElement =
      asChild && isValidElement(children)
        ? (children as ReactElement<{
            children?: ReactNode;
            className?: string;
            style?: React.CSSProperties;
            ref?: React.Ref<HTMLButtonElement>;
            disabled?: boolean;
            "aria-disabled"?: boolean;
            tabIndex?: number;
            onClick?: React.MouseEventHandler<HTMLElement>;
            onKeyDown?: React.KeyboardEventHandler<HTMLElement>;
          }>)
        : null;
    const label = asChildElement ? asChildElement.props.children : children;
    const contextSize = useSizeVariant();
    const resolvedSize: ButtonSizeCanonical = size
      ? size
      : contextSize === "compact"
        ? "compact"
        : "default";
    const isIconOnly =
      resolvedSize === "icon" ||
      resolvedSize === "icon-compact" ||
      resolvedSize === "icon-xs" ||
      resolvedSize === "icon-sm" ||
      resolvedSize === "icon-lg";
    const isCompact =
      resolvedSize === "compact" ||
      resolvedSize === "icon-compact" ||
      resolvedSize === "sm" ||
      resolvedSize === "icon-xs" ||
      resolvedSize === "icon-sm";
    const iconSize = isCompact ? 14 : 16;
    const spinnerSizeClass = isCompact ? "h-7 w-7" : "h-9 w-9";
    const shape = useShape();
    const effectiveVariant = variant ?? "primary";
    const bgClass = active
      ? activeBgVariants[effectiveVariant] ?? activeBgVariants.primary
      : bgVariants[effectiveVariant] ?? bgVariants.primary;

    const internals = (
      <>
        <span
          aria-hidden
          className={cn(
            "absolute inset-px rounded-[inherit] transition-[box-shadow,background-color] [transition-duration:180ms,80ms] [transition-timing-function:cubic-bezier(0.23,1,0.32,1),ease] group-active:[transition-duration:80ms,80ms]",
            bgClass
          )}
        />
        <span className="relative inline-flex items-center justify-center gap-[inherit]">
          {loading ? (
            <>
              <span className="flex items-center justify-center gap-[inherit] opacity-0">
                {LeadingIcon && !isIconOnly && (
                  <LeadingIcon size={iconSize} strokeWidth={2} />
                )}
                {label}
                {TrailingIcon && !isIconOnly && (
                  <TrailingIcon size={iconSize} strokeWidth={2} />
                )}
              </span>
              <span className="absolute inset-0 flex items-center justify-center">
                <svg
                  className={spinnerSizeClass}
                  viewBox="0 0 24 24"
                  fill="none"
                >
                  <path
                    d="M 12 12 C 14 8.5 19 8.5 19 12 C 19 15.5 14 15.5 12 12 C 10 8.5 5 8.5 5 12 C 5 15.5 10 15.5 12 12 Z"
                    stroke="currentColor"
                    strokeWidth="1.125"
                    strokeLinecap="round"
                    pathLength="100"
                    style={{
                      strokeDasharray: "15 85",
                      animation:
                        "spinner-move 2s linear infinite, spinner-dash 4s ease-in-out infinite",
                    }}
                  />
                </svg>
              </span>
            </>
          ) : isIconOnly ? (
            <span className="[&_svg]:stroke-[1.5] [&_svg]:transition-[stroke-width] [&_svg]:duration-80 group-hover:[&_svg]:stroke-[2]">
              {label}
            </span>
          ) : (
            <>
              {LeadingIcon && (
                <LeadingIcon
                  size={iconSize}
                  strokeWidth={1.5}
                  className="transition-[stroke-width] duration-80 group-hover:stroke-[2]"
                />
              )}
              <span className="[text-box:trim-both_cap_alphabetic]">{label}</span>
              {TrailingIcon && (
                <TrailingIcon
                  size={iconSize}
                  strokeWidth={1.5}
                  className="transition-[stroke-width] duration-80 group-hover:stroke-[2]"
                />
              )}
            </>
          )}
        </span>
      </>
    );

    const rootClassName = cn(
      buttonVariants({
        variant: effectiveVariant,
        size: resolvedSize,
        iconLeft: !isIconOnly && !!LeadingIcon,
        iconRight: !isIconOnly && !!TrailingIcon,
      }),
      shape?.button,
      className
    );

    const isDisabled = disabled || loading;

    // Anchors have no native disabled state, and aria-disabled does not stop
    // keyboard activation: a disabled Button rendered as an anchor must
    // suppress click/Enter navigation and leave the tab order.
    const disabledAnchorProps = isDisabled
      ? {
          tabIndex: -1,
          onClick: (event: React.MouseEvent<HTMLElement>) => {
            event.preventDefault();
          },
          onKeyDown: (event: React.KeyboardEvent<HTMLElement>) => {
            if (event.key === "Enter") event.preventDefault();
          },
        }
      : null;

    if (render && isValidElement(render)) {
      const renderEl = render as ReactElement<{
        className?: string;
        style?: React.CSSProperties;
        children?: ReactNode;
        disabled?: boolean;
        "aria-disabled"?: boolean;
        tabIndex?: number;
        onClick?: React.MouseEventHandler<HTMLElement>;
        onKeyDown?: React.KeyboardEventHandler<HTMLElement>;
        ref?: React.Ref<HTMLButtonElement>;
      }>;
      const isAnchor = renderEl.type === "a";
      return cloneElement(
        renderEl,
        {
          ...props,
          ref,
          // Anchors have no native disabled state; the effective disabled
          // state is conveyed via aria-disabled (styled by the variants).
          disabled: isAnchor ? undefined : isDisabled || undefined,
          "aria-disabled": isDisabled || undefined,
          ...(isAnchor && disabledAnchorProps ? disabledAnchorProps : {}),
          className: cn(rootClassName, renderEl.props.className),
          style: { ...style, ...renderEl.props.style },
        },
        internals
      );
    }

    if (asChildElement) {
      const childProps = asChildElement.props;
      const isAnchor = asChildElement.type === "a";
      return cloneElement(
        asChildElement,
        {
          ...props,
          ref,
          disabled: isAnchor ? undefined : isDisabled || undefined,
          "aria-disabled": isDisabled || undefined,
          ...(isAnchor && disabledAnchorProps ? disabledAnchorProps : {}),
          className: cn(rootClassName, childProps.className),
          style: { ...style, ...childProps.style },
        },
        internals
      );
    }

    return (
      <ButtonPrimitive
        ref={ref as React.Ref<HTMLButtonElement>}
        className={rootClassName}
        disabled={disabled || loading}
        style={style}
        {...props}
      >
        {internals}
      </ButtonPrimitive>
    );
  }
);

Button.displayName = "Button";

export { Button, buttonVariants };
export type { ButtonProps, ButtonSize };
