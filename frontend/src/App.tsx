import { Navigate, Route, Routes, useLocation } from 'react-router-dom'
import { BookScope } from './api/scope'
import Layout from './components/Layout'
import { ErrorBoundary } from './components/ui'
import Home from './pages/Home'
import RunCenter from './pages/RunCenter'
import Studio from './pages/Studio'
import World from './pages/World'
import Board from './pages/Board'
import Timeline from './pages/Timeline'
import Reviews from './pages/Reviews'
import Planner from './pages/Planner'
import Wizard from './pages/Wizard'
import Settings from './pages/Settings'

export default function App() {
  const location = useLocation()
  const book = new URLSearchParams(location.search).get('book') || null
  return (
    <ErrorBoundary key={JSON.stringify(book)}>
      <BookScope key={JSON.stringify(book)} book={book}>
        <Routes>
          <Route element={<Layout />}>
            <Route path="/" element={<Home />} />
            <Route path="/runs" element={<RunCenter />} />
            <Route path="/runs/:runId" element={<RunCenter />} />
            <Route path="/studio/:chapter" element={<Studio />} />
            <Route path="/studio" element={<Navigate to={'/studio/latest' + location.search} replace />} />
            <Route path="/wizard" element={<Wizard />} />
            <Route path="/world" element={<World />} />
            <Route path="/board" element={<Board />} />
            <Route path="/planner" element={<Planner />} />
            <Route path="/reviews" element={<Reviews />} />
            <Route path="/timeline" element={<Timeline />} />
            <Route path="/settings" element={<Settings />} />
            <Route path="*" element={<Navigate to={'/' + location.search} replace />} />
          </Route>
        </Routes>
      </BookScope>
    </ErrorBoundary>
  )
}
