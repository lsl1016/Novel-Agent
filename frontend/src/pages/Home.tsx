import { Link, useNavigate } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { api } from '../api/client'
import { Card, Pill, Stat } from '../components/ui'

export default function Home() {
  const navigate = useNavigate()
  const { data: home } = useQuery({ queryKey: ['home'], queryFn: () => api.get('/api/v1/home'), refetchInterval: 15000 })
  if (!home) return null
  const p = home.pressure || {}
  const run = home.run
  const target = run?.config?.target_chapter || home.arcs?.at(-1)?.target_end_chapter || home.progress.committed_chapters
  const pctBar = Math.min(100, Math.round((home.progress.committed_chapters / Math.max(1, target)) * 100))
  const spark = (home.recent_chapters || []).map((c: any) => c.chars || 0)

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
      <div style={{ display: 'grid', gridTemplateColumns: '1.45fr 1fr 1fr 1fr', gap: 14 }}>
        <Card title="进度">
          <div style={{ display: 'flex', gap: 22, alignItems: 'center' }}>
            <div>
              <div style={{ display: 'flex', alignItems: 'baseline', gap: 6 }}>
                <span style={{ fontSize: 32, fontWeight: 700, color: 'var(--sem-canon)', fontFamily: 'var(--font-mono)' }}>{home.progress.committed_chapters}</span>
                <span style={{ color: 'var(--muted)' }}>/ {target} 章</span>
              </div>
              <div style={{ fontSize: 12, color: 'var(--muted)', margin: '2px 0 8px' }}>
                {(home.progress.total_chars / 10000).toFixed(1)} 万字 · {home.current_arc?.name || '—'}
              </div>
              <div style={{ width: 200, height: 7, background: 'var(--panel-2)', borderRadius: 4, overflow: 'hidden' }}>
                <div style={{ width: `${pctBar}%`, height: '100%', background: 'linear-gradient(90deg, var(--sem-canon), #d9a43f)', borderRadius: 4, transition: 'width .6s' }} />
              </div>
            </div>
            <Sparkline values={spark} />
          </div>
        </Card>
        <Card title="故事压力" extra={p.risks?.length ? <Pill tone="warn">{p.risks.length} 风险</Pill> : <Pill tone="pass">健康</Pill>}>
          <div style={{ display: 'flex', gap: 18 }}>
            <Stat label="未解谜团" value={p.open_mysteries ?? '—'} />
            <Stat label="逾期伏笔" value={p.stale_foreshadowing ?? '—'} />
            <Stat label="未偿情感债" value={p.open_emotion_debts ?? '—'} />
          </div>
        </Card>
        <Card title="待办收件箱">
          <div style={{ display: 'flex', gap: 18 }}>
            <Stat label="待决问题" value={home.inbox?.open_decisions ?? '—'} tone={home.inbox?.open_decisions ? 'var(--sem-warn)' : undefined} />
            <Stat label="抽取候选" value={home.inbox?.pending_candidates ?? '—'} />
            <Stat label="写作中草稿" value={home.inbox?.active_draft_chapters ?? '—'} tone="var(--sem-draft)" />
          </div>
        </Card>
        <Card title="运行状态" extra={run && <Link to={`/runs/${run.run_id}`} style={{ color: 'var(--accent)', fontSize: 12 }}>运行中心 →</Link>}>
          {run ? (
            <div style={{ display: 'flex', gap: 18 }}>
              <Stat label="状态" value={<Pill tone={run.status === 'running' ? 'pass' : 'muted'}>{run.status}</Pill>} />
              <Stat label="当前章" value={run.current_chapter} />
              <Stat label="本轮提交" value={run.chapters_committed} />
            </div>
          ) : <div style={{ color: 'var(--muted)' }}>暂无运行记录</div>}
        </Card>
      </div>

      {p.risks?.length > 0 && (
        <Card title="压力建议">
          <ul style={{ margin: 0, paddingLeft: 18, color: 'var(--muted)', lineHeight: 1.9 }}>
            {p.risks.map((r: string) => <li key={r}><code style={{ color: 'var(--sem-warn)' }}>{r}</code></li>)}
          </ul>
        </Card>
      )}

      <div style={{ display: 'grid', gridTemplateColumns: '1.2fr 1fr', gap: 14 }}>
        <Card title="最近章节">
          <table className="tbl">
            <thead>
              <tr>
                <th>章</th><th>标题</th><th>篇章</th><th>视角</th><th style={{ textAlign: 'right' }}>字数</th><th>提交时间</th>
              </tr>
            </thead>
            <tbody>
              {(home.recent_chapters || []).map((c: any) => (
                <tr key={c.chapter} className="row-hover" onClick={() => navigate(`/studio/${c.chapter}`)}>
                  <td className="mono" style={{ color: 'var(--sem-canon)' }}>{c.chapter}</td>
                  <td>{c.title}</td>
                  <td className="dim">{c.arc}</td>
                  <td className="dim">{c.pov}</td>
                  <td className="mono" style={{ textAlign: 'right' }}>{c.chars}</td>
                  <td className="mono dim" style={{ fontSize: 12 }}>{(c.committed_at || '').slice(5, 16)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </Card>
        <Card title="篇章结构">
          {(home.arcs || []).map((a: any) => (
            <div key={a.arc_key} style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '6px 0', borderBottom: '1px solid var(--line)' }}>
              <Pill tone={a.arc_key === home.current_arc?.arc_key ? 'canon' : 'muted'}>{a.order_no}</Pill>
              <span>{a.name}</span>
              <span style={{ marginLeft: 'auto', color: 'var(--muted)', fontFamily: 'var(--font-mono)', fontSize: 12 }}>
                {a.start_chapter}–{a.target_end_chapter}
              </span>
            </div>
          ))}
        </Card>
      </div>
    </div>
  )
}

/** 最近章节字数迷你折线(内联 SVG,零依赖) */
function Sparkline({ values, width = 120, height = 44 }: { values: number[]; width?: number; height?: number }) {
  if (!values.length) return null
  const max = Math.max(...values, 1), min = Math.min(...values, 0)
  const dx = width / Math.max(1, values.length - 1)
  const y = (v: number) => height - 4 - ((v - min) / Math.max(1, max - min)) * (height - 10)
  const pts = values.map((v, i) => `${i * dx},${y(v)}`).join(' ')
  const area = `0,${height} ${pts} ${width},${height}`
  const avg = values.reduce((a, b) => a + b, 0) / values.length
  return (
    <svg width={width} height={height} style={{ overflow: 'visible' }}>
      <polygon points={area} fill="rgba(63,116,173,.10)" />
      <polyline points={pts} fill="none" stroke="var(--sem-draft)" strokeWidth="1.8" strokeLinejoin="round" />
      <line x1="0" x2={width} y1={y(avg)} y2={y(avg)} stroke="var(--muted)" strokeWidth="0.8" strokeDasharray="3 3" opacity=".6" />
      <circle cx={(values.length - 1) * dx} cy={y(values[values.length - 1])} r="2.8" fill="var(--sem-draft)" />
      <text x={width / 2} y={height + 10} textAnchor="middle" fontSize="9.5" fill="var(--muted)">近 {values.length} 章字数 · 均值 {Math.round(avg)}</text>
    </svg>
  )
}
