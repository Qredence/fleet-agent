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
 * Provides a surface level to descendant components, clamped to the inclusive range 1–8.
 *
 * @param value - The surface level to provide
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
