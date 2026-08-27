import { createBrowserRouter, Navigate } from 'react-router-dom'

import { WorkspaceBootstrapRoute } from '@/app/routes/workspace-bootstrap-route'
import { WorkspaceRoute } from '@/app/routes/workspace-route'
import { OptimizerRoute } from '@/app/routes/optimizer-route'
import { ToolsRoute } from '@/app/routes/tools-route'
import { ConnectorsRoute } from '@/app/routes/connectors-route'

export const appRouter = createBrowserRouter([
  {
    path: '/',
    element: <WorkspaceBootstrapRoute />,
  },
  {
    path: '/projects/:projectId',
    element: <WorkspaceRoute />,
  },
  {
    path: '/projects/:projectId/threads/:threadId',
    element: <WorkspaceRoute />,
  },
  {
    path: '/projects/:projectId/optimizer',
    element: <OptimizerRoute />,
  },
  {
    path: '/projects/:projectId/tools',
    element: <ToolsRoute />,
  },
  {
    path: '/projects/:projectId/connectors',
    element: <ConnectorsRoute />,
  },
  {
    path: '*',
    element: <Navigate to="/" replace />,
  },
])
