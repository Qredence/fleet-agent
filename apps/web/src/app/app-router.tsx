import { Suspense, lazy, type ReactNode } from 'react'
import { createBrowserRouter, Navigate } from 'react-router-dom'

const WorkspaceBootstrapRoute = lazy(() =>
  import('@/app/routes/workspace-bootstrap-route').then((m) => ({
    default: m.WorkspaceBootstrapRoute,
  })),
)
const WorkspaceRoute = lazy(() =>
  import('@/app/routes/workspace-route').then((m) => ({
    default: m.WorkspaceRoute,
  })),
)
const OptimizerRoute = lazy(() =>
  import('@/app/routes/optimizer-route').then((m) => ({
    default: m.OptimizerRoute,
  })),
)
const ToolsRoute = lazy(() =>
  import('@/app/routes/tools-route').then((m) => ({
    default: m.ToolsRoute,
  })),
)
const ConnectorsRoute = lazy(() =>
  import('@/app/routes/connectors-route').then((m) => ({
    default: m.ConnectorsRoute,
  })),
)

function RouteSuspense({ children }: { children: ReactNode }) {
  return (
    <Suspense
      fallback={
        <div
          role="status"
          aria-live="polite"
          className="flex min-h-screen items-center justify-center text-sm text-muted-foreground"
        >
          Loading workspace…
        </div>
      }
    >
      {children}
    </Suspense>
  )
}

export const appRouter = createBrowserRouter([
  {
    path: '/',
    element: (
      <RouteSuspense>
        <WorkspaceBootstrapRoute />
      </RouteSuspense>
    ),
  },
  {
    path: '/projects/:projectId',
    element: (
      <RouteSuspense>
        <WorkspaceRoute />
      </RouteSuspense>
    ),
  },
  {
    path: '/projects/:projectId/threads/:threadId',
    element: (
      <RouteSuspense>
        <WorkspaceRoute />
      </RouteSuspense>
    ),
  },
  {
    path: '/projects/:projectId/optimizer',
    element: (
      <RouteSuspense>
        <OptimizerRoute />
      </RouteSuspense>
    ),
  },
  {
    path: '/projects/:projectId/tools',
    element: (
      <RouteSuspense>
        <ToolsRoute />
      </RouteSuspense>
    ),
  },
  {
    path: '/projects/:projectId/connectors',
    element: (
      <RouteSuspense>
        <ConnectorsRoute />
      </RouteSuspense>
    ),
  },
  {
    path: '*',
    element: <Navigate to="/" replace />,
  },
])
