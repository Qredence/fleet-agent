import type { SVGProps } from 'react'

import { cn } from '@/lib/utils'

export interface OpenRouterLogoProps extends SVGProps<SVGSVGElement> {
  className?: string
  /**
   * Pixel size for the logo box, mapped to width/height like lucide's
   * `size` prop. Icon slots (e.g. `SidebarMenuButton`) size icons through
   * this prop rather than a class, so it must produce real dimensions.
   */
  size?: number | string
}

/**
 * OpenRouter SVG Logo component with monochrome currentColor fill.
 *
 * The viewBox is wider than tall (401.4×293.7), so a square `size` box
 * letterboxes the mark via the default `preserveAspectRatio` instead of
 * stretching it.
 */
export function OpenRouterLogo({
  className,
  size,
  ...props
}: OpenRouterLogoProps) {
  return (
    <svg
      viewBox="0 0 401.4 293.7"
      fill="currentColor"
      aria-hidden="true"
      width={size}
      height={size}
      className={cn(size == null && 'size-4', className)}
      {...props}
    >
      <path d="M303.9475,17.19926c42.79734,0,77.48933,34.69327,77.48933,77.48933s-34.69199,77.48933-77.48933,77.48933l76.86166,76.86244c9.76367,9.76313,2.84903,26.45667-10.95697,26.45667h-220.88335c-71.32686,0-129.14889-57.82202-129.14889-129.14889S77.64197,17.19926,148.96884,17.19926h154.97866ZM148.96884,68.85881c-42.79607,0-77.48933,34.69327-77.48933,77.48933s34.69327,77.48933,77.48933,77.48933,77.48933-34.69327,77.48933-77.48933-34.69327-77.48933-77.48933-77.48933Z" />
    </svg>
  )
}
