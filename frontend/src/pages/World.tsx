import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { api } from '../api/client'
import { Card, Pill } from '../components/ui'
import { useCursor } from '../stores/cursor'
import GraphCanvas from '../components/GraphCanvas'

/** 世界观设定集(D2):目录表格 ↔ 图谱画布 双视图 + 实体档案抽屉 */
export default function World() {
  const cursor = useCursor((s) => s.chapter)
  const [view, setView] = useState<'table' | 'graph'>('table')
  const [q, setQ] = useState('')
  const [type, setType] = useState('')
  const [picked, setPicked] = useState<string | null>(null)

  const { data } = useQuery({
    queryKey: ['entities', cursor, q, type],
    queryFn: () => api.get(`/api/v1/entities?${new URLSearchParams({ ...(cursor ? { chapter: String(cursor) } : {}), q, type })}`),
  })
  const { data: graph } = useQuery({
    queryKey: ['graph', cursor],
    queryFn: () => api.get(`/api/v1/graph${cursor ? `?chapter=${cursor}` : ''}`),
    enabled: view === 'graph',
  })
  const { data: detail } = useQuery({
    queryKey: ['entity', picked, cursor],
    queryFn: () => api.get(`/api/v1/entity/${picked}${cursor ? `?chapter=${cursor}` : ''}`),
    enabled: !!picked,
  })

  const entities = data?.entities || []
  const types = Object.entries<any>(data?.type_counts || {}).sort((a, b) => b[1] - a[1])

  return (
    <div style={{ display: 'flex', gap: 14, height: '100%' }}>
      <div style={{ flex: 1, display: 'flex', flexDirection: 'column', gap: 14, overflow: 'auto' }}>
        <Card>
          <div style={{ display: 'flex', gap: 10, alignItems: 'center', flexWrap: 'wrap' }}>
            <input className="input" style={{ width: 210 }} value={q} onChange={(e) => setQ(e.target.value)} placeholder="搜索名称/键…" />
            <button onClick={() => setType('')} className={`btn sm${type === '' ? ' primary' : ''}`}>全部 {data?.entities.length ?? ''}</button>
            {types.map(([t, n]) => (
              <button key={t} onClick={() => setType(t)} className={`btn sm${type === t ? ' primary' : ''}`}>{tLabel(t)} {n}</button>
            ))}
            <div style={{ flex: 1 }} />
            {['table', 'graph'].map((v) => (
              <button key={v} onClick={() => setView(v as any)} className={`btn sm${view === v ? ' primary' : ''}`}>{v === 'table' ? '目录' : '图谱'}</button>
            ))}
          </div>
        </Card>

        {view === 'table' ? (
          <Card>
            <table className="tbl">
              <thead><tr>
                <th>名称</th><th>类型</th><th>描述</th><th>登场章</th><th>关联线</th>
              </tr></thead>
              <tbody>
                {entities.map((e: any) => (
                  <tr key={e.entity_key} className="row-hover" onClick={() => setPicked(e.entity_key)}
                    style={{ background: picked === e.entity_key ? 'var(--panel-2)' : undefined }}>
                    <td style={{ fontWeight: 600 }}>{e.name}</td>
                    <td><Pill tone={e.entity_type === 'Character' ? 'draft' : e.entity_type === 'Faction' ? 'secret' : e.entity_type === 'Location' ? 'pass' : 'canon'}>{tLabel(e.entity_type)}</Pill></td>
                    <td className="dim" style={{ maxWidth: 300, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{e.description || '—'}</td>
                    <td className="mono">ch{e.introduced_chapter ?? '?'}</td>
                    <td className="dim">{e.thread_count ?? ''}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </Card>
        ) : (
          <Card title={`实体图谱 · 截至 第 ${graph?.chapter ?? '最新'} 章`} extra={<span style={{ color: 'var(--muted)', fontSize: 12 }}>实线=公开 · 紫红虚线=秘密 · 形状=类型</span>}>
            {graph && <GraphCanvas nodes={graph.nodes} edges={graph.edges} onPick={setPicked} focus={picked} />}
          </Card>
        )}
      </div>

      {detail && (
        <aside style={{ width: 380, overflow: 'auto' }}>
          <Card title={<span>{detail.name} <Pill tone="muted">{tLabel(detail.entity_type)}</Pill></span>}
            extra={<a onClick={() => setPicked(null)} style={{ color: 'var(--muted)', cursor: 'pointer' }}>✕</a>}>
            <p style={{ margin: '0 0 10px', color: 'var(--muted)', lineHeight: 1.7 }}>{detail.description}</p>

            {detail.identity_profiles?.length > 0 && (
              <Section title="身份档案">
                {detail.identity_profiles.map((p: any) => (
                  <div key={p.profile_key} style={{ display: 'flex', gap: 8, padding: '3px 0', fontSize: 13 }}>
                    <Pill tone={p.secrecy !== 'public' ? 'secret' : 'muted'}>{p.kind}</Pill>
                    <span>{p.value}</span>
                    {p.scope_key && <span style={{ color: 'var(--muted)' }}>@{p.scope_key}</span>}
                  </div>
                ))}
              </Section>
            )}

            <Section title={`属性时间线 (截至 ch${detail.chapter})`}>
              {detail.attributes.length === 0 && <Empty />}
              {detail.attributes.map((a: any, i: number) => (
                <div key={i} style={{ display: 'flex', gap: 8, padding: '3px 0', fontSize: 13 }}>
                  <span style={{ color: 'var(--sem-draft)', minWidth: 72 }}>{a.attr_key}</span>
                  <span>{String(a.value)}</span>
                  <span style={{ marginLeft: 'auto', color: 'var(--muted)', fontFamily: 'var(--font-mono)', fontSize: 12 }}>ch{a.start_chapter}{a.end_chapter ? `–${a.end_chapter}` : '–'}</span>
                  {a.secrecy !== 'public' && <Pill tone="secret">🔒</Pill>}
                </div>
              ))}
            </Section>

            <Section title="关系">
              {detail.relations.length === 0 && <Empty />}
              {detail.relations.map((r: any, i: number) => {
                const outgoing = r.source_entity_key === detail.entity_key
                return (
                  <div key={i} style={{ display: 'flex', gap: 8, padding: '3px 0', fontSize: 13 }}>
                    <span style={{ color: 'var(--muted)' }}>{outgoing ? '→' : '←'}</span>
                    <code style={{ fontSize: 11, color: 'var(--accent)' }}>{r.relation_type}</code>
                    <span>{outgoing ? r.target_name : r.source_name}</span>
                    <span style={{ marginLeft: 'auto', color: 'var(--muted)', fontFamily: 'var(--font-mono)', fontSize: 12 }}>ch{r.start_chapter}–{r.end_chapter ?? '今'}</span>
                  </div>
                )
              })}
            </Section>

            <Section title={`叙事参与 (${detail.narrative_links.length})`}>
              {detail.narrative_links.slice(0, 12).map((l: any, i: number) => (
                <div key={i} style={{ display: 'flex', gap: 8, padding: '2px 0', fontSize: 13 }}>
                  <span style={{ color: 'var(--muted)', fontFamily: 'var(--font-mono)', fontSize: 12 }}>ch{l.chapter}</span>
                  <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{l.narrative_name}</span>
                  <span style={{ marginLeft: 'auto', color: 'var(--muted)', fontSize: 12 }}>{l.role}</span>
                </div>
              ))}
              {detail.narrative_links.length > 12 && <div style={{ color: 'var(--muted)', fontSize: 12 }}>…共 {detail.narrative_links.length} 条</div>}
            </Section>
          </Card>
        </aside>
      )}
    </div>
  )
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div style={{ borderTop: '1px solid var(--line)', marginTop: 10, paddingTop: 8 }}>
      <div style={{ color: 'var(--muted)', fontSize: 12, marginBottom: 4, letterSpacing: '0.05em' }}>{title}</div>
      {children}
    </div>
  )
}
const Empty = () => <div style={{ color: 'var(--muted)', fontSize: 12 }}>暂无</div>

function tLabel(t: string) {
  return ({ Character: '人物', Faction: '势力', Location: '地点', Artifact: '器物', Item: '物品', Power: '力量' } as any)[t] || t
}
