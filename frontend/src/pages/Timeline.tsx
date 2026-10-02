import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { api } from '../api/client'
import { Card, Pill } from '../components/ui'

/** 时间线浏览器(D2):章节主轴 + 事件泳道(按类型分道) + 变迁轨道 */
export default function Timeline() {
  const [from, setFrom] = useState(1)
  const [to, setTo] = useState(40)
  const [sel, setSel] = useState<any | null>(null)
  const { data: home } = useQuery({ queryKey: ['home'], queryFn: () => api.get('/api/v1/home') })
  const latest = home?.progress?.latest_chapter || 40
  const lo = from, hi = Math.min(to, latest)
  const { data } = useQuery({
    queryKey: ['timeline', lo, hi],
    queryFn: () => api.get(`/api/v1/timeline?from=${lo}&to=${hi}`),
  })
  const events = data?.events || []
  const span = Math.max(1, hi - lo + 1)
  const x = (ch: number) => ((ch - lo + 0.5) / span) * 100

  const lanes: Record<string, any[]> = {}
  for (const e of events) (lanes[e.event_type || 'event'] ||= []).push(e)

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 14, height: '100%' }}>
      <Card>
        <div style={{ display: 'flex', gap: 10, alignItems: 'center' }}>
          <span style={{ color: 'var(--muted)' }}>章节窗口</span>
          <input type="number" value={lo} min={1} max={latest} onChange={(e) => setFrom(Math.max(1, Math.min(+e.target.value, hi)))} className="num" />
          <span>–</span>
          <input type="number" value={hi} min={lo} max={latest} onChange={(e) => setTo(+e.target.value)} className="num" />
          <span style={{ color: 'var(--muted)', fontSize: 12 }}>共 {events.length} 事件 · {data?.attribute_changes?.length ?? 0} 属性变迁 · {data?.relation_changes?.length ?? 0} 关系变迁(最新已提交 ch{latest})</span>
        </div>
      </Card>

      <Card title="世界事件时间线" style={{ overflow: 'auto' }}>
        <div style={{ minWidth: 700, position: 'relative' }}>
          {/* 章节刻度 */}
          <div style={{ position: 'relative', height: 22, borderBottom: '1px solid var(--line)' }}>
            {Array.from({ length: span }, (_, i) => (lo + i) % 5 === 0 && (
              <span key={i} style={{ position: 'absolute', left: `${x(lo + i)}%`, transform: 'translateX(-50%)', color: 'var(--muted)', fontFamily: 'var(--font-mono)', fontSize: 11 }}>
                {lo + i}
              </span>
            ))}
          </div>
          {/* 事件泳道 */}
          {Object.entries(lanes).map(([type, es]) => (
            <div key={type} style={{ position: 'relative', height: 44, borderBottom: '1px solid var(--line)' }}>
              {Array.from({ length: span }, (_, i) => (lo + i) % 5 === 0 && (
                <span key={i} style={{ position: 'absolute', left: `${x(lo + i)}%`, top: 0, bottom: 0, width: 1, background: 'var(--line)' }} />
              ))}
              <span style={{ position: 'sticky', left: 4, color: 'var(--muted)', fontSize: 11, top: 2, background: 'var(--panel)', padding: '0 4px', borderRadius: 3 }}>{typeLabel(type)} ({es.length})</span>
              {es.map((e) => (
                <span key={e.event_id ?? e.id} title={`ch${e.chapter} ${e.name}\n${e.outcome || ''}`}
                  onClick={() => setSel(e)}
                  style={{
                    position: 'absolute', left: `${x(e.chapter)}%`, top: 19, transform: 'translateX(-50%)',
                    width: 10, height: 10, borderRadius: 10, cursor: 'pointer',
                    background: typeColor(e.event_type),
                    boxShadow: sel && (sel.event_id ?? sel.id) === (e.event_id ?? e.id) ? '0 0 0 3px rgba(146,81,158,.3)' : '0 1px 3px rgba(16,24,40,.22)',
                    border: '1.5px solid var(--panel)',
                  }} />
              ))}
            </div>
          ))}
          {Object.keys(lanes).length === 0 && <div style={{ color: 'var(--muted)', padding: 14 }}>该窗口暂无一等事件(事件由作者/抽取管线创建)。</div>}
          {/* 属性/关系变迁轨道 */}
          {(data?.attribute_changes?.length || data?.relation_changes?.length) ? (
            <div style={{ position: 'relative', height: 40 }}>
              <span style={{ position: 'sticky', left: 4, color: 'var(--muted)', fontSize: 11 }}>变迁轨道</span>
              {(data.attribute_changes || []).map((a: any, i: number) => (
                <span key={'a' + i} title={`ch${a.start_chapter} ${a.entity_key}.${a.attr_key} = ${JSON.stringify(a.value)}`}
                  style={{ position: 'absolute', left: `${x(a.start_chapter)}%`, top: 20, transform: 'translateX(-50%)', fontSize: 10, color: 'var(--sem-canon)', cursor: 'default' }}>◆</span>
              ))}
              {(data.relation_changes || []).map((r: any, i: number) => (
                <span key={'r' + i} title={`ch${r.start_chapter} ${r.source_entity_key} ${r.relation_type} ${r.target_entity_key}${r.end_chapter ? ` (至 ch${r.end_chapter})` : ''}`}
                  style={{ position: 'absolute', left: `${x(r.start_chapter)}%`, top: 30, transform: 'translateX(-50%)', fontSize: 10, color: 'var(--sem-reader)', cursor: 'default' }}>◇</span>
              ))}
            </div>
          ) : null}
        </div>
      </Card>

      {sel && (
        <Card title={`事件 · ch${sel.chapter}`} extra={<a onClick={() => setSel(null)} style={{ color: 'var(--muted)', cursor: 'pointer' }}>✕</a>}>
          <div style={{ fontSize: 14, marginBottom: 6 }}>{sel.name}</div>
          <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap', color: 'var(--muted)', fontSize: 13 }}>
            <Pill tone="muted">{sel.event_type || 'event'}</Pill>
            {sel.status && <Pill tone={sel.status === 'verified' ? 'pass' : 'warn'}>{sel.status}</Pill>}
            {sel.thread_key && <span>线:{sel.thread_key}</span>}
            {sel.location_key && <span>地:{sel.location_key}</span>}
            {sel.cause_event_id && <span>因果上游:#{sel.cause_event_id}</span>}
          </div>
          {sel.outcome && <p style={{ margin: '8px 0 0', lineHeight: 1.8, fontSize: 13 }}>{sel.outcome}</p>}
          {sel.consequence && <p style={{ margin: '4px 0 0', color: 'var(--muted)', fontSize: 12 }}>后果:{sel.consequence}</p>}
          {sel.participants?.length > 0 && (
            <div style={{ marginTop: 8, display: 'flex', gap: 6, flexWrap: 'wrap' }}>
              {sel.participants.map((p: any, i: number) => <Pill key={i} tone="draft">{p.entity_key}{p.participant_role ? ` · ${p.participant_role}` : ''}</Pill>)}
            </div>
          )}
        </Card>
      )}
    </div>
  )
}

function typeLabel(t: string) {
  return ({ event: '事件', battle: '战斗', discovery: '发现', betrayal: '背叛', death: '死亡', meeting: '会面' } as any)[t] || t
}

function typeColor(t?: string) {
  return ({
    event: 'var(--sem-draft)', battle: 'var(--sem-block)', discovery: 'var(--sem-pass)',
    betrayal: 'var(--sem-secret)', death: 'var(--sem-block)', meeting: 'var(--sem-character)',
  } as any)[t || ''] || 'var(--sem-draft)'
}
