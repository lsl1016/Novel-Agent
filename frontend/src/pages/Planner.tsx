import { useQuery } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import { api } from '../api/client'
import { Card, Pill } from '../components/ui'
import { useCursor } from '../stores/cursor'

/** 规划器(D3):弧线甘特(章节轴脊柱)+ 里程碑 + 排期 + 滚动窗 + 章节计划状态 */
export default function Planner() {
  const cursor = useCursor((s) => s.chapter)
  const navigate = useNavigate()
  const { data } = useQuery({ queryKey: ['plan', cursor], queryFn: () => api.get(`/api/v1/plan${cursor ? `?chapter=${cursor}` : ''}`) })
  if (!data) return null
  const arcs = data.arcs || []
  const milestones = data.milestones || []
  const schedule = data.thread_schedule || []
  const lo = 1
  const hi = Math.max(...arcs.map((a: any) => a.target_end_chapter || 0), data.chapter || 40) + 2
  const span = hi - lo + 1
  const x = (ch: number) => ((ch - lo) / span) * 100
  const threadName = (k: string) => (data.threads || []).find((t: any) => t.thread_key === k)?.name || k
  const ARC_HUES = ['#e8f1fa', '#f0e6f5', '#e0f2e6', '#fbeed3', '#e3f3f1', '#f6edf9', '#fdf3e2']

  const planStatus = (data.chapter_plans || [])
  const blockedPlans = planStatus.filter((p: any) => p.validation_status === 'blocked')
  const window = (data.rolling_window || []).slice(0, 24)

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
      <Card title={`篇章结构 · 截至 第 ${data.chapter} 章`} extra={
        <div className="legend">
          <span className="k"><span className="dot" style={{ background: 'var(--sem-canon)' }} />里程碑</span>
          <span className="k"><span className="dot" style={{ background: 'var(--sem-draft)' }} />排期窗</span>
          <span className="k"><span className="dot" style={{ background: 'var(--sem-secret)' }} />真相揭示</span>
        </div>
      }>
        <div style={{ position: 'relative', minWidth: 640 }}>
          {/* 章节刻度 */}
          <div style={{ position: 'relative', height: 20 }}>
            {Array.from({ length: span }, (_, i) => (lo + i) % 5 === 0 && (
              <span key={i} className="mono" style={{ position: 'absolute', left: `${x(lo + i)}%`, transform: 'translateX(-50%)', color: 'var(--muted)', fontSize: 11 }}>{lo + i}</span>
            ))}
          </div>
          {/* 弧带 */}
          {arcs.map((a: any, i: number) => (
            <div key={a.arc_key} style={{ position: 'relative', height: 54, marginBottom: 4 }}>
              <div style={{ position: 'absolute', left: `${x(a.start_chapter)}%`, width: `${x(a.target_end_chapter) - x(a.start_chapter)}%`, top: 6, bottom: 6, background: ARC_HUES[i % ARC_HUES.length], borderRadius: 8, border: '1px solid var(--line)', padding: '6px 10px' }}>
                <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
                  <b style={{ fontSize: 13 }}>{a.name}</b>
                  <span className="mono dim" style={{ fontSize: 11 }}>ch{a.start_chapter}–{a.target_end_chapter}</span>
                  {a.status === 'active' && <Pill tone="pass">进行中</Pill>}
                </div>
                <div style={{ color: 'var(--muted)', fontSize: 11.5, marginTop: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{a.primary_goal}</div>
              </div>
              {/* 里程碑菱形 */}
              {milestones.filter((m: any) => m.arc_key === a.arc_key).map((m: any) => (
                <span key={m.milestone_key} title={`里程碑 ${m.name} · ch${m.min_chapter}–${m.max_chapter} · ${m.status}`}
                  style={{ position: 'absolute', left: `${x((m.min_chapter + m.max_chapter) / 2)}%`, top: -2, transform: 'translateX(-50%) rotate(45deg)', width: 11, height: 11, background: m.status === 'done' ? 'var(--sem-pass)' : 'var(--sem-canon)', border: '2px solid var(--panel)', borderRadius: 2, boxShadow: '0 1px 3px rgba(16,24,40,.3)' }} />
              ))}
              {/* 排期窗 */}
              {schedule.map((s: any) => (
                <span key={s.schedule_key} title={`排期 ${threadName(s.thread_key)} ${s.stage_type} · ch${s.min_chapter}–${s.max_chapter}`}
                  style={{ position: 'absolute', left: `${x(s.min_chapter)}%`, width: `${Math.max(1.5, x(s.max_chapter) - x(s.min_chapter))}%`, top: 44, height: 6, borderRadius: 3, background: 'var(--sem-draft)', opacity: .55 }} />
              ))}
            </div>
          ))}
        </div>
      </Card>

      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 14 }}>
        <Card title={`章节计划(${planStatus.length})`} extra={blockedPlans.length ? <Pill tone="warn">{blockedPlans.length} blocked</Pill> : <Pill tone="pass">全部通过</Pill>}>
          <div style={{ maxHeight: 300, overflow: 'auto', display: 'flex', flexWrap: 'wrap', gap: 4 }}>
            {planStatus.map((p: any) => (
              <span key={p.chapter} onClick={() => navigate(`/studio/${p.chapter}`)}
                title={`ch${p.chapter} ${p.validation_status}${p.arc_key ? ` (${p.arc_key})` : ''}`}
                style={{
                  width: 34, height: 26, borderRadius: 5, cursor: 'pointer', fontSize: 11,
                  display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
                  fontFamily: 'var(--font-mono)',
                  background: p.validation_status === 'blocked' ? 'var(--sem-block-bg)' : p.validation_status === 'warning' ? 'var(--sem-warn-bg)' : 'var(--sem-pass-bg)',
                  color: p.validation_status === 'blocked' ? 'var(--sem-block)' : p.validation_status === 'warning' ? 'var(--sem-warn)' : 'var(--sem-pass)',
                  border: `1px solid var(--line)`,
                }}>{p.chapter}</span>
            ))}
          </div>
          <div style={{ color: 'var(--muted)', fontSize: 11.5, marginTop: 8 }}>每格一章:绿=ready 琥珀=warning 红=blocked;点击进写作工作室。</div>
        </Card>
        <Card title="滚动规划窗(Hard/Medium/Soft)">
          <div style={{ maxHeight: 320, overflow: 'auto' }}>
            {window.map((w: any, i: number) => (
              <div key={i} style={{ display: 'flex', gap: 8, alignItems: 'center', padding: '3px 0', borderBottom: '1px solid var(--line)', fontSize: 12.5 }}>
                <Pill tone={w.tier === 'hard' ? 'block' : w.tier === 'medium' ? 'warn' : 'muted'}>{w.tier}</Pill>
                <span className="mono" style={{ color: 'var(--sem-canon)' }}>ch{w.chapter}</span>
                <span style={{ flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', color: 'var(--muted)' }}>{w.primary_goal || '—'}</span>
                <span className="tag">{w.status}</span>
              </div>
            ))}
          </div>
        </Card>
      </div>
    </div>
  )
}
