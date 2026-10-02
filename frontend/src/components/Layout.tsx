import { NavLink, Outlet, useNavigate } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { api } from '../api/client'
import { useSession } from '../stores/session'
import { useCursor } from '../stores/cursor'
import { Pill, ToastHost } from './ui'

const I = {
  home: '⌂', run: '▶', studio: '✎', wizard: '✦', world: '◈', board: '坪', planner: '◫', review: '✓', time: '⏱', gear: '⚙',
}

const NAV_SECTIONS: { sec: string; items: { to?: string; label: string; icon: string; ready?: boolean; author?: boolean; create?: boolean }[] }[] = [
  { sec: '监控', items: [
    { to: '/', label: '项目主页', icon: I.home, ready: true },
    { to: '/runs', label: '运行中心', icon: I.run, ready: true },
  ]},
  { sec: '创作', items: [
    { to: '/wizard', label: '开书向导', icon: I.wizard, ready: true, create: true },
    { to: '/studio/latest', label: '写作工作室', icon: I.studio, ready: true },
  ]},
  { sec: '图谱', items: [
    { to: '/world', label: '世界观设定集', icon: I.world, ready: true, author: true },
    { to: '/board', label: '叙事看板', icon: I.board, ready: true, author: true },
    { to: '/planner', label: '规划器', icon: I.planner, ready: true, author: true },
    { to: '/reviews', label: '审校中心', icon: I.review, ready: true, author: true },
    { to: '/timeline', label: '时间线', icon: I.time, ready: true, author: true },
  ]},
  { sec: '系统', items: [{ to: '/settings', label: '设置', icon: I.gear, ready: true }]},
]

export default function Layout() {
  const { role, logout, book, setBook } = useSession()
  const navigate = useNavigate()
  const cursor = useCursor((s) => s.chapter)
  const setCursor = useCursor((s) => s.setChapter)
  const { data: home } = useQuery({ queryKey: ['home-mini', book], queryFn: () => api.get('/api/v1/home'), refetchInterval: 15000 })
  const { data: booksData } = useQuery({ queryKey: ['books'], queryFn: () => api.get('/api/v1/books'), refetchInterval: 60000 })
  const run = home?.run
  const progress = home?.progress
  const latest = progress?.latest_chapter || 1
  const at = cursor ?? latest
  const isToday = at === latest

  return (
    <div style={{ display: 'grid', gridTemplateColumns: '200px 1fr', height: '100%' }}>
      <ToastHost />
      <aside style={{ borderRight: '1px solid var(--line)', background: 'var(--panel)', padding: '16px 0', display: 'flex', flexDirection: 'column', overflow: 'auto' }}>
        <div style={{ padding: '2px 16px 16px', fontWeight: 700, letterSpacing: '.1em', fontSize: 15 }}>
          NOVEL<span style={{ color: 'var(--accent)' }}>·</span>AGENT
          <div style={{ fontSize: 10, color: 'var(--muted)', letterSpacing: '.22em', marginTop: 3, fontWeight: 400 }}>NARRATIVE RUNTIME</div>
        </div>
        {NAV_SECTIONS.map((g) => (
          <div key={g.sec}>
            <div className="nav-sec">{g.sec}</div>
            {g.items.map((item) => {
              const enabled = item.ready && (!item.author || role !== 'viewer') && (!item.create || role === 'planner' || role === 'admin')
              if (!enabled) {
                return <div key={item.label} className="nav-item disabled" title="后续阶段提供"><span style={{ width: 14, textAlign: 'center', opacity: .6 }}>{item.icon}</span>{item.label}</div>
              }
              return (
                <NavLink key={item.label} to={item.to!} end={item.to === '/'}
                  className={({ isActive }) => `nav-item${isActive ? ' active' : ''}`}>
                  <span style={{ width: 14, textAlign: 'center' }}>{item.icon}</span>{item.label}
                </NavLink>
              )
            })}
          </div>
        ))}
        <div style={{ marginTop: 'auto', padding: '10px 14px', borderTop: '1px solid var(--line)', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <Pill tone={role === 'viewer' ? 'reader' : 'accent'}>{role === 'viewer' ? '读者模式' : role}</Pill>
          <a onClick={() => { logout(); navigate('/') }} style={{ color: 'var(--muted)', cursor: 'pointer', fontSize: 12 }}>退出</a>
        </div>
      </aside>

      <div style={{ display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
        <header style={{ display: 'flex', alignItems: 'center', gap: 16, padding: '10px 22px', borderBottom: '1px solid var(--line)', background: 'var(--panel)' }}>
          {(booksData?.books?.length || 0) > 1 ? (
            <select className="input" value={book || ''}
              onChange={(e) => { setBook(e.target.value || null); useCursor.getState().setChapter(latest) }}
              title="切换书库" style={{ fontWeight: 700, fontSize: 14.5, maxWidth: 190 }}>
              {(booksData?.books || []).map((b: any) => {
                const v = b.default ? '' : b.name.replace(/\.db$/, '')
                return <option key={b.name} value={v}>{b.title}{b.chapters ? ` (${b.chapters}章)` : ''}</option>
              })}
            </select>
          ) : (
            <strong style={{ fontSize: 15, letterSpacing: '.02em' }}>{home?.book?.title || '未命名之书'}</strong>
          )}
          {progress && (
            <span style={{ color: 'var(--muted)', fontSize: 12.5 }}>
              <b style={{ color: 'var(--sem-canon)' }}>{progress.committed_chapters}</b> 章 · {(progress.total_chars / 10000).toFixed(1)} 万字
            </span>
          )}
          {role !== 'viewer' && (
            <span className="scrubber" title="章节时光轴:拖动把全站世界回拨到该章">
              <span style={{ color: 'var(--muted)', fontSize: 11.5, letterSpacing: '.06em' }}>时光轴</span>
              <input type="range" min={1} max={latest} value={at} onChange={(e) => setCursor(Number(e.target.value))} />
              <span className="val" style={{ color: isToday ? 'var(--sem-canon)' : 'var(--accent)' }}>
                {isToday ? `ch${at} 今` : `ch${at}`}
              </span>
              {!isToday && <a onClick={() => setCursor(latest)} style={{ color: 'var(--muted)', cursor: 'pointer', fontSize: 11 }}>回今</a>}
            </span>
          )}
          <div style={{ flex: 1 }} />
          {run && (
            <a onClick={() => navigate(`/runs/${run.run_id}`)} style={{ cursor: 'pointer' }}>
              <Pill tone={run.status === 'running' ? 'pass' : run.status === 'paused' || run.status === 'needs_author_decision' ? 'warn' : 'muted'}>
                {run.status === 'running' ? `● 运行中 · 第${run.current_chapter}章` : run.status === 'needs_author_decision' ? '◆ 待决策' : `◼ ${run.status}`}
              </Pill>
            </a>
          )}
        </header>
        <main style={{ flex: 1, overflow: 'auto', padding: 20 }}>
          <Outlet />
        </main>
      </div>
    </div>
  )
}
