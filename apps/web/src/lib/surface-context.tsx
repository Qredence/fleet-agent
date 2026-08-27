"use client";

import { createContext, useContext, type ReactNode } from "react";

const SurfaceContext = createContext<number>(1);

/**
 * Retrieves the current surface level from the surrounding context.
 *
 * @returns The current surface level.
 */
export function useSurface(): number {
  return useContext(SurfaceContext);
}

/**
 * Provides a clamped surface level to descendant components.
 *
 * @param value - The surface level, clamped to the range 1–8
 * @param children - The descendant content that receives the surface level
 */
export function SurfaceProvider({
  value,
  children,
}: {
  value: number;
  children: ReactNode;
}) {
  return (
    <SurfaceContext.Provider value={Math.max(1, Math.min(8, value))}>
      {children}
    </SurfaceContext.Provider>
  );
}
