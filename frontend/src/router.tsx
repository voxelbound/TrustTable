import { createBrowserRouter } from 'react-router'
import { PlaceholderRoute } from './routes/PlaceholderRoute'

/**
 * React Router Data Mode router (FND-01). A single placeholder route —
 * real screens are out of scope for the repository-foundation stage.
 */
export const router = createBrowserRouter([
  {
    path: '/',
    element: <PlaceholderRoute />,
  },
])
