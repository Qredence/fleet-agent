import { forwardRef, type ButtonHTMLAttributes, type ReactNode } from 'react'
import { Loader2 } from 'lucide-react'
import { cva, type VariantProps } from 'class-variance-authority'

import { OpenRouterLogo } from '@/components/auth/openrouter-logo'
import { useOpenRouterAuth } from '@/hooks/use-openrouter-auth'
import { cn } from '@/lib/utils'

export const openRouterButtonVariants = cva(
  'inline-flex items-center justify-center font-medium transition-all cursor-pointer disabled:opacity-50 disabled:pointer-events-none select-none outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2',
  {
    variants: {
      variant: {
        default:
          'rounded-lg border border-neutral-300 bg-white text-neutral-900 shadow-sm hover:bg-neutral-50 dark:border-neutral-700 dark:bg-neutral-900 dark:text-white dark:hover:bg-neutral-800',
        minimal:
          'text-neutral-700 dark:text-neutral-300 underline-offset-4 hover:underline hover:text-foreground bg-transparent',
        branded:
          'rounded-lg bg-neutral-900 text-white shadow hover:bg-neutral-800 dark:bg-white dark:text-neutral-900 dark:hover:bg-neutral-100',
        icon: 'rounded-lg border border-neutral-300 bg-white text-neutral-900 shadow-sm hover:bg-neutral-50 dark:border-neutral-700 dark:bg-neutral-900 dark:text-white dark:hover:bg-neutral-800 aspect-square p-0',
        cta: 'rounded-xl bg-neutral-900 text-white shadow-lg hover:bg-neutral-800 hover:scale-[1.02] active:scale-[0.98] dark:bg-white dark:text-neutral-900 dark:hover:bg-neutral-100',
      },
      size: {
        sm: 'h-8 px-3 text-xs gap-1.5',
        default: 'h-10 px-5 text-sm gap-2',
        lg: 'h-12 px-8 text-base gap-2.5',
        xl: 'h-14 px-10 text-lg gap-3',
      },
    },
    defaultVariants: {
      variant: 'default',
      size: 'default',
    },
  },
)

export interface OpenRouterButtonProps
  extends ButtonHTMLAttributes<HTMLButtonElement>,
    VariantProps<typeof openRouterButtonVariants> {
  callbackUrl?: string
  loading?: boolean
  showLogo?: boolean
  children?: ReactNode
}

/**
 * Sign in with OpenRouter OAuth Button component.
 *
 * Initiates the PKCE OAuth flow on click and exchanges the code for a user API key.
 */
export const OpenRouterButton = forwardRef<
  HTMLButtonElement,
  OpenRouterButtonProps
>(
  (
    {
      variant = 'default',
      size = 'default',
      callbackUrl,
      loading = false,
      showLogo = true,
      children,
      className,
      onClick,
      disabled,
      ...props
    },
    ref,
  ) => {
    const { signIn, isLoading } = useOpenRouterAuth()
    const isPending = loading || isLoading

    const handleClick = (e: React.MouseEvent<HTMLButtonElement>) => {
      if (onClick) {
        onClick(e)
      } else {
        void signIn(callbackUrl)
      }
    }

    const isIconVariant = variant === 'icon'

    const logoSizeClass =
      size === 'sm'
        ? 'size-3.5'
        : size === 'lg'
          ? 'size-5'
          : size === 'xl'
            ? 'size-6'
            : 'size-4'

    return (
      <button
        ref={ref}
        type="button"
        className={cn(
          openRouterButtonVariants({ variant, size }),
          className,
        )}
        onClick={handleClick}
        disabled={disabled || isPending}
        aria-busy={isPending}
        {...props}
      >
        {isPending ? (
          <Loader2 className={cn('animate-spin', logoSizeClass)} />
        ) : showLogo ? (
          <OpenRouterLogo className={logoSizeClass} />
        ) : null}

        {!isIconVariant && (
          <span>{children ?? 'Sign in with OpenRouter'}</span>
        )}
        {isIconVariant && (
          <span className="sr-only">Sign in with OpenRouter</span>
        )}
      </button>
    )
  },
)

OpenRouterButton.displayName = 'OpenRouterButton'
