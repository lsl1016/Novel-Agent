import { useQuery } from '@tanstack/react-query'
import { api } from '../api/client'
import { Card, Pill } from '../components/ui'
import { useCursor } from '../stores/cursor'

/** 线程时间带:stage 按章节比例落位,一格 = 线程从引入到当前游标的生命史 */
function ThreadLane({ thread, stages, at }: { thread: any; stages: any[]; at: number }) {
  const lo = thread.introduced_chapter || 1
  const hi = Math.max(at, lo + 1)
  const span = hi - lo
  const pos = (ch: number) => Math.max(0, Math.min(100, ((ch - lo) / span) * 100))
  const lastCh = stages.length ? Math.max(...stages.map((s) => s.chapter)) : lo
  const dormant = thread.status === 'open' && stages.length && at - lastCh >= 5
  const stageColor: Record<string, string> = { Clue: 'var(--sem-draft)', Reveal: 'var(--sem-secret)', Payoff: 'var(--sem-pass)' }

  return (
    <div style={{ padding: '8px 0', borderBottom: '1px solid var(--line)' }}>
      <div style={{ display: 'flex', gap: 8, alignItems: 'center', marginBottom: 6 }}>
        <Pill tone={thread.status === 'open' ? (dormant ? 'dormant' : 'pass') : 'canon'}>
          {thread.status === 'open' ? (dormant ? '休眠' : '活跃') : '完结'}
        </Pill>
        <strong style={{ fontSize: 13 }}>{thread.name}</strong>
        <span style={{ color: 'var(--muted)', fontSize: 12 }}>{thread.thread_type}</span>
        <span style={{ marginLeft: 'auto', color: 'var(--muted)', fontFamily: 'var(--font-mono)', fontSize: 11.5 }}>
          ch{thread.introduced_chapter} 起 · 兑付窗 {thread.target_min}–{thread.target_max} · {stages.length} 拍
        </span>
      </div>
      <div className="lane-track">
        {[0, 1, 2, 3, 4].map((i) => <span key={i} className="lane-tick" style={{ left: `${(i / 4) * 100}%` }} />)}
        {/* 兑付窗口投影 */}
        {thread.target_min != null && thread.target_min <= hi && (
          <span style={{ position: 'absolute', left: `${pos(thread.target_min)}%`, width: `${Math.max(0, pos(Math.min(thread.target_max ?? hi, hi)) - pos(thread.target_min))}%`, top: 0, bottom: 0, background: 'var(--sem-canon-bg)', opacity: .8 }} />
        )}
        {/* 休眠段:最后一拍之后到当前 */}
        {dormant && (
          <span style={{ position: 'absolute', left: `${pos(lastCh)}%`, width: `${100 - pos(lastCh)}%`, top: 0, bottom: 0, background: 'repeating-linear-gradient(45deg, transparent 0 4px, rgba(138,145,160,.18) 4px 8px)' }} />
        )}
        {stages.map((s) => (
          <span key={s.id} title={`ch${s.chapter} [${s.stage_type}] ${(s.content || '').slice(0, 70)}`}
            style={{
              position: 'absolute', left: `${pos(s.chapter)}%`, top: '50%',
              transform: 'translate(-50%, -50%)',
              width: s.stage_type === 'Payoff' ? 10 : 7, height: s.stage_type === 'Payoff' ? 10 : 7,
              borderRadius: s.stage_type === 'Reveal' ? 2 : '50%',
              background: stageColor[s.stage_type] || 'var(--muted)',
              border: '1.5px solid var(--panel)',
              boxShadow: '0 1px 3px rgba(16,24,40,.25)',
            }} />
        ))}
      </div>
    </div>
  )
}

/** 叙事看板:线程时间带 + 谜团倒计时 + 情感债 + 信念矩阵 + 伏笔台账 */
export default function Board() {
  const cursor = useCursor((s) => s.chapter)
  const { data } = useQuery({
    queryKey: ['board', cursor],
    queryFn: () => api.get(`/api/v1/board${cursor ? `?chapter=${cursor}` : ''}`),
  })
  if (!data) return null
  const at = data.chapter
  const stagesByThread: Record<string, any[]> = {}
  for (const s of data.stages || []) (stagesByThread[s.thread_key] ||= []).push(s)
  const openMysteries = (data.mysteries || []).filter((m: any) => m.status === 'open' && m.introduced_chapter <= at)
  const openDebts = (data.emotion_debs || data.emotion_debts || []).filter((d: any) => d.status !== 'resolved')
  const unpaid = (data.clue_ledger || []).filter((c: any) => !c.paid).length

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
      <div style={{ display: 'grid', gridTemplateColumns: '1.55fr 1fr', gap: 14 }}>
        <Card title={`叙事线时间带 · 截至 第 ${at} 章`}
          extra={<div className="legend">
            <span className="k"><span className="dot" style={{ background: 'var(--sem-draft)' }} />线索</span>
            <span className="k"><span className="dot" style={{ background: 'var(--sem-secret)', borderRadius: 2 }} />揭示</span>
            <span className="k"><span className="dot" style={{ background: 'var(--sem-pass)' }} />兑现</span>
            <span className="k"><span className="dot" style={{ background: 'var(--sem-canon-bg)', border: '1px solid var(--sem-canon)' }} />兑付窗</span>
          </div>}>
          {(data.threads || []).map((t: any) => (
            <ThreadLane key={t.thread_key} thread={t} stages={stagesByThread[t.thread_key] || []} at={at} />
          ))}
        </Card>

        <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
          <Card title={`未解谜团 (${openMysteries.length})`}>
            {openMysteries.map((m: any) => (
              <div key={m.mystery_key} style={{ padding: '6px 0', borderBottom: '1px solid var(--line)' }}>
                <div style={{ fontSize: 13, marginBottom: 4 }}>{m.name}</div>
                <div style={{ display: 'flex', justifyContent: 'space-between', color: 'var(--muted)', fontSize: 11.5, fontFamily: 'var(--font-mono)' }}>
                  <span>ch{m.introduced_chapter} 提出 · 已 {at - m.introduced_chapter} 章</span>
                  <span>窗口 {m.target_min}–{m.target_max}</span>
                </div>
                <div style={{ height: 5, background: 'var(--panel-2)', borderRadius: 3, marginTop: 5, position: 'relative', overflow: 'hidden' }}>
                  <div style={{ position: 'absolute', left: `${pct(at, m.target_min, m.target_max)}%`, right: 0, top: 0, bottom: 0, background: inWindow(at, m) ? 'var(--sem-pass)' : 'var(--sem-draft)', opacity: .55 }} />
                </div>
              </div>
            ))}
          </Card>
          <Card title={`情感债 (${openDebts.length})`} extra={<span style={{ color: 'var(--muted)', fontSize: 11.5 }}>按强度 · 前 10</span>}>
            {openDebts.slice().sort((a: any, b: any) => b.intensity - a.intensity).slice(0, 10).map((d: any) => (
              <div key={d.debt_key} style={{ display: 'flex', gap: 8, alignItems: 'center', padding: '4px 0', fontSize: 12.5, borderBottom: '1px solid var(--line)' }}>
                <span style={{ width: 46, height: 6, borderRadius: 3, background: 'var(--sem-warn)', opacity: 0.25 + d.intensity * 0.75 }} />
                <span style={{ flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{d.name}</span>
                <span className="mono dim" style={{ fontFamily: 'var(--font-mono)', fontSize: 11.5 }}>ch{d.created_chapter}</span>
              </div>
            ))}
          </Card>
        </div>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: '1.15fr 1fr', gap: 14 }}>
        <Card title="信念矩阵" extra={<span style={{ color: 'var(--muted)', fontSize: 11.5 }}>🔒 真相(作者可见) · 每格 = 该持有者截至本章的认知</span>}>
          <table style={{ borderCollapse: 'separate', borderSpacing: 6, fontSize: 12.5 }}>
            <tbody>
              {(data.belief_matrix || []).map((f: any) => (
                <tr key={f.fact_key}>
                  <td style={{ maxWidth: 190, paddingRight: 6 }}>
                    <div style={{ color: 'var(--sem-secret)', fontWeight: 600, fontSize: 12 }}>🔒 {f.fact_key}</div>
                    <div style={{ color: 'var(--muted)', fontSize: 11, marginTop: 2, lineHeight: 1.5 }}>{String(f.truth).slice(0, 46)}</div>
                  </td>
                  {Object.entries(f.holders).map(([holder, h]: any) => (
                    <td key={holder} style={{ padding: 0 }}>
                      <div className={`heat ${h.stance || 'unknown'}`}>
                        <div style={{ fontSize: 10.5, opacity: .75 }}>{holder === 'reader' ? '读者' : holder}</div>
                        <div style={{ fontWeight: 600 }}>{stanceLabel(h.stance)}</div>
                      </div>
                    </td>
                  ))}
                  <td style={{ color: 'var(--muted)', fontSize: 11, fontFamily: 'var(--font-mono)', whiteSpace: 'nowrap' }}>
                    揭示 ch{f.reveal_after ?? '—'}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </Card>

        <Card title="伏笔台账" extra={<Pill tone={unpaid ? 'warn' : 'pass'}>{unpaid} 未回收</Pill>}>
          <div style={{ maxHeight: 300, overflow: 'auto' }}>
            {(data.clue_ledger || []).slice(-24).reverse().map((c: any) => (
              <div key={c.stage_id} style={{ display: 'flex', gap: 8, padding: '4px 0', fontSize: 12.5, borderBottom: '1px solid var(--line)' }}>
                <span style={{ color: c.paid ? 'var(--sem-pass)' : 'var(--sem-warn)' }}>{c.paid ? '✓' : '◌'}</span>
                <span style={{ color: 'var(--muted)', fontFamily: 'var(--font-mono)', fontSize: 11.5 }}>ch{c.chapter}</span>
                <span style={{ flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{c.content}</span>
                <code style={{ color: 'var(--muted)', fontSize: 10 }}>{c.callback_key}</code>
              </div>
            ))}
          </div>
          <div style={{ color: 'var(--muted)', fontSize: 11.5, marginTop: 8, lineHeight: 1.6 }}>
            ◌ 待回收:后续应以同 callback_key 显式兑付(设计契约);回收率纳入 KPI。
          </div>
        </Card>
      </div>
    </div>
  )
}

function stanceLabel(s?: string | null) {
  return ({ unknown: '不知', suspects: '怀疑', believes: '信(误)', confirmed: '已知' } as any)[s || ''] || s || '—'
}
function pct(now: number, min: number, max: number) {
  return Math.max(0, Math.min(100, ((now - min) / Math.max(1, max - min)) * 100))
}
function inWindow(at: number, m: any) {
  return at >= m.target_min && at <= m.target_max
}
