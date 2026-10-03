import { useState } from 'react'
import { NavLink, Outlet, useNavigate } from 'react-router-dom'
import { useApi, useBookHref, useQuery } from '../api/scope'
import AppShell from './AppShell'
import { ChapterCursor } from './ChapterAxis'
import { StatusBadge } from './ui'

const groups = [
  { name: '总览', items: [['/', '项目主页', '⌂']] },
  {
    name: '创作',
    items: [
      ['/studio/latest', '写作工作室', '✎'],
      ['/planner', '章节规划', '▤'],
      ['/wizard', '开书向导', '✦'],
    ],
  },
  {
    name: '故事资产',
    items: [
      ['/world', '世界观', '◇'],
      ['/board', '叙事看板', '▦'],
      ['/timeline', '时间线', '◷'],
    ],
  },
  {
    name: '质量与自动化',
    items: [
      ['/reviews', '审校中心', '✓'],
      ['/runs', '运行中心', '▷'],
    ],
  },
  { name: '系统', items: [['/settings', '设置', '⚙']] },
]
export default function Layout() {
  const api = useApi(),
    href = useBookHref(),
    navigate = useNavigate()
  const [timeOpen, setTimeOpen] = useState(false)
  const { data: home } = useQuery({
    queryKey: ['home'],
    queryFn: () => api.get('/api/v1/home'),
    refetchInterval: 15000,
  })
  const { data: library } = useQuery({
    queryKey: ['books'],
    queryFn: () => api.get('/api/v1/books'),
    refetchInterval: 60000,
  })
  const { data: reviews } = useQuery({
    queryKey: ['reviews'],
    queryFn: () => api.get('/api/v1/reviews?from=1&to=9999'),
    refetchInterval: 30000,
  })
  const blocks = (reviews?.chapters || []).reduce((n: number, c: any) => {
    const latest = c.latest_draft_version ?? Math.max(...c.reviews.map((r: any) => r.draft_version), 0)
    return n + c.reviews.filter((r: any) => r.draft_version === latest && r.verdict === 'BLOCK').length
  }, 0)
  const pending = home?.inbox?.open_decisions || 0,
    run = home?.run
  const next = home?.progress?.latest_chapter ? home.progress.latest_chapter + 1 : 1
  const sidebar = (
    <>
      <div className="brand">
        <span className="brand-mark">N</span>
        <div className="nav-label">
          <strong>Novel Agent</strong>
          <small>让故事生长</small>
        </div>
      </div>
      <NavLink className="continue-btn" to={href(`/studio/${next}`)} title="继续创作">
        <span>✎</span>
        <span className="nav-label">继续创作</span>
        <span className="nav-label">↗</span>
      </NavLink>
      <nav aria-label="主要导航">
        {groups.map((g) => (
          <div className="nav-group" key={g.name}>
            <div className="nav-sec">{g.name}</div>
            {g.items.map(([to, text, icon]) => (
              <NavLink
                key={to}
                to={href(to)}
                end={to === '/'}
                title={text}
                className={({ isActive }) => 'nav-item' + (isActive ? ' active' : '')}
              >
                <span className="nav-icon" aria-hidden>
                  {icon}
                </span>
                <span className="nav-label">{text}</span>
                {to === '/runs' &&
                  (pending > 0 ? (
                    <span className="nav-count">{pending}</span>
                  ) : run?.status === 'running' ? (
                    <span className="live-dot" />
                  ) : null)}
                {to === '/reviews' && blocks > 0 && <span className="nav-count danger">{blocks}</span>}
              </NavLink>
            ))}
          </div>
        ))}
      </nav>
      <div className="sidebar-footer">
        <span className="live-dot" />
        <span className="nav-label">公开工作台 · 全部功能可用</span>
      </div>
    </>
  )
  return (
    <AppShell
      sidebar={sidebar}
      topbar={(open) => (
        <>
          <button className="icon-btn mobile-menu" onClick={open} aria-label="打开导航">
            ☰
          </button>
          <div className="book-switch">
            <span className="book-icon" aria-hidden>
              ▣
            </span>
            <select
              aria-label="切换书库"
              value={api.book || ''}
              onChange={(e) => navigate('/?book=' + encodeURIComponent(e.target.value))}
            >
              {!library?.books?.some((b: any) => b.default) && (
                <option value="">{home?.book?.title || '当前书库'}</option>
              )}
              {(library?.books || []).map((b: any) => (
                <option key={b.name} value={b.default ? '' : b.name.replace(/\.db$/, '')}>
                  {b.title}
                </option>
              ))}
            </select>
          </div>
          <span className="book-progress">
            {home?.progress?.committed_chapters || 0} 章 ·{' '}
            {((home?.progress?.total_chars || 0) / 10000).toFixed(1)} 万字
          </span>
          <div className="desktop-cursor">
            <ChapterCursor />
          </div>
          <div className="topbar-spacer" />
          {run && (
            <NavLink to={href('/runs/' + run.run_id)} className="run-link">
              <StatusBadge status={run.status} />
            </NavLink>
          )}
          <button
            className="icon-btn time-toggle"
            aria-expanded={timeOpen}
            aria-label="打开章节时光轴"
            onClick={() => setTimeOpen(!timeOpen)}
          >
            ◷
          </button>
        </>
      )}
    >
      {timeOpen && (
        <div className="mobile-time-panel">
          <ChapterCursor />
        </div>
      )}
      <Outlet />
    </AppShell>
  )
}
