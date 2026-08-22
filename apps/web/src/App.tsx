import { RouterProvider } from 'react-router-dom'

import { appRouter } from '@/app/app-router'
import { AppProviders } from '@/app/providers'

export function App() {
  return (
    <AppProviders>
      <RouterProvider router={appRouter} />
    </AppProviders>
  )
}
