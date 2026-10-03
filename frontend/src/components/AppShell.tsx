import { useEffect, useState, type ReactNode } from 'react'
import { useLocation } from 'react-router-dom'
import { Drawer, ToastHost } from './ui'

export default function AppShell({
  sidebar,
  topbar,
  children,
}: {
  sidebar: ReactNode
  topbar: (open: () => void) => ReactNode
  children: ReactNode
}) {
  const [open, setOpen] = useState(false),
    location = useLocation()
  useEffect(() => setOpen(false), [location.pathname, location.search])
  return (
    <div className="app-shell">
      <a className="skip-link" href="#main-content">
        跳到主内容
      </a>
      <aside className="app-sidebar">{sidebar}</aside>
      <div className="app-frame">
        <header className="app-topbar">{topbar(() => setOpen(true))}</header>
        <main id="main-content" className="app-main">
          {children}
        </main>
      </div>
      {open && (
        <Drawer title="创作导航" onClose={() => setOpen(false)}>
          <div className="mobile-nav">{sidebar}</div>
        </Drawer>
      )}
      <ToastHost />
    </div>
  )
}
