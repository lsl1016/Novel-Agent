import { Navigate, Route, Routes } from 'react-router-dom'
import { useSession } from './stores/session'
import Layout from './components/Layout'
import Login from './pages/Login'
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
  const token = useSession((s) => s.token)
  const role = useSession((s) => s.role)
  const authorLayer = role !== 'viewer' // 作者层页面,viewer 不入
  const canCreate = role === 'planner' || role === 'admin'
  if (!token) return <Login />
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route path="/" element={<Home />} />
        <Route path="/runs" element={<RunCenter />} />
        <Route path="/runs/:runId" element={<RunCenter />} />
        <Route path="/studio/:chapter" element={<Studio />} />
        <Route path="/studio" element={<Navigate to="/" replace />} />
        <Route path="/wizard" element={canCreate ? <Wizard /> : <Navigate to="/" replace />} />
        <Route path="/world" element={authorLayer ? <World /> : <Navigate to="/" replace />} />
        <Route path="/board" element={authorLayer ? <Board /> : <Navigate to="/" replace />} />
        <Route path="/planner" element={authorLayer ? <Planner /> : <Navigate to="/" replace />} />
        <Route path="/reviews" element={authorLayer ? <Reviews /> : <Navigate to="/" replace />} />
        <Route path="/timeline" element={authorLayer ? <Timeline /> : <Navigate to="/" replace />} />
        <Route path="/settings" element={<Settings />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Route>
    </Routes>
  )
}
