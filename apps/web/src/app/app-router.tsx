import { createBrowserRouter, Navigate } from 'react-router-dom'

import { WorkspaceBootstrapRoute } from '@/app/routes/workspace-bootstrap-route'
import { WorkspaceRoute } from '@/app/routes/workspace-route'

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
    path: '*',
    element: <Navigate to="/" replace />,
  },
])
