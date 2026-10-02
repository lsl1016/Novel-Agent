import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { api } from '../api/client'
import { Card, Pill, verdictTone } from '../components/ui'

const REVIEWERS = [
  'knowledge_leak', 'continuity', 'narrative', 'character',
  'semantic_knowledge_leak', 'semantic_character', 'semantic_narrative', 'semantic_pacing',
]

function rLabel(t: string) {
  return ({
    knowledge_leak: '泄漏', continuity: '连续', narrative: '叙事', character: '人物',
    semantic_knowledge_leak: '语·泄', semantic_character: '语·人', semantic_narrative: '语·叙', semantic_pacing: '语·奏',
  } as any)[t] || t
}

/** 审校中心(D3):章节 × 审校器结论矩阵 + 发现收件箱 + 修订收敛 */
export default function Reviews() {
  const navigate = useNavigate()
  const [scope, setScope] = useState(10)
  const { data } = useQuery({ queryKey: ['reviews', scope], queryFn: () => api.get(`/api/v1/reviews?from=1&to=999`), refetchInterval: 30000 })
  const chapters = (data?.chapters || []).slice(-scope)
  const findings: { ch: number; type: string; verdict: string; f: any }[] = []
  for (const c of chapters) {
    for (const r of c.reviews || []) {
      for (const f of r.findings || []) findings.push({ ch: c.chapter, type: r.reviewer_type, verdict: r.verdict, f })
    }
  }
  findings.sort((a, b) => (a.verdict === 'BLOCK' ? -1 : b.verdict === 'BLOCK' ? 1 : b.ch - a.ch))
  const blocks = findings.filter((x) => x.verdict === 'BLOCK')

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
      <Card title="全书审校矩阵" extra={
        <span style={{ display: 'inline-flex', gap: 10, alignItems: 'center' }}>
          {[5, 10, 20, 40].map((n) => (
            <button key={n} className={`btn sm${scope === n ? ' primary' : ''}`} onClick={() => setScope(n)}>近 {n} 章</button>
          ))}
          {blocks.length > 0 ? <Pill tone="block">{blocks.length} BLOCK</Pill> : <Pill tone="pass">无 BLOCK</Pill>}
        </span>
      }>
        <div style={{ overflowX: 'auto' }}>
          <table style={{ borderCollapse: 'separate', borderSpacing: 4 }}>
            <thead>
              <tr>
                <th style={{ padding: '0 8px', color: 'var(--muted)', fontSize: 11.5, textAlign: 'left' }}>章</th>
                {REVIEWERS.map((r) => <th key={r} style={{ color: 'var(--muted)', fontSize: 11, fontWeight: 500 }}>{rLabel(r)}</th>)}
              </tr>
            </thead>
            <tbody>
              {chapters.map((c: any) => (
                <tr key={c.chapter}>
                  <td className="mono" style={{ color: 'var(--sem-canon)' }}>{c.chapter}</td>
                  {REVIEWERS.map((rt) => {
                    const r = (c.reviews || []).find((x: any) => x.reviewer_type === rt)
                    const v = r?.verdict
                    const n = r?.findings?.length || 0
                    return (
                      <td key={rt} style={{ padding: 0 }}>
                        <div className={`heat ${v ? v.toLowerCase() : 'unknown'}`} style={{ minWidth: 46, padding: '4px 2px', cursor: v ? 'pointer' : 'default' }}
                          title={v ? `ch${c.chapter} ${rt} ${v}${n ? ` (${n} 项发现)` : ''}` : '未审'}
                          onClick={() => v && navigate(`/studio/${c.chapter}`)}>
                          <span style={{ fontSize: 11 }}>{v ? rLabel(v === 'PASS' ? '通过' : v === 'WARN' ? `警${n || ''}` : '阻断') : '—'}</span>
                        </div>
                      </td>
                    )
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>

      <div style={{ display: 'grid', gridTemplateColumns: '1.4fr 1fr', gap: 14 }}>
        <Card title={`发现收件箱(${findings.length})`} extra={<span style={{ color: 'var(--muted)', fontSize: 11.5 }}>BLOCK 置顶 · 点击跳章节</span>}>
          <div style={{ maxHeight: 380, overflow: 'auto' }}>
            {findings.slice(0, 60).map((x, i) => (
              <div key={i} className="row-hover" onClick={() => navigate(`/studio/${x.ch}`)}
                style={{ display: 'flex', gap: 8, alignItems: 'baseline', padding: '4px 6px', borderBottom: '1px solid var(--line)', fontSize: 12.5, borderRadius: 4 }}>
                <span className="mono" style={{ color: 'var(--sem-canon)', minWidth: 34 }}>ch{x.ch}</span>
                <Pill tone={verdictTone(x.verdict)}>{x.verdict}</Pill>
                <span style={{ color: 'var(--muted)', minWidth: 52 }}>{rLabel(x.type)}</span>
                <span style={{ flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                  <code style={{ fontSize: 11, color: 'var(--sem-warn)' }}>{x.f.code}</code> {x.f.message}
                </span>
              </div>
            ))}
            {findings.length === 0 && <div style={{ color: 'var(--muted)' }}>最近章节无审校发现。</div>}
          </div>
        </Card>
        <Card title="修订收敛(多版本章节)">
          {Object.entries(data?.convergence || {}).map(([ch, versions]: any) => (
            <div key={ch} style={{ padding: '6px 0', borderBottom: '1px solid var(--line)' }}>
              <div style={{ fontSize: 13, marginBottom: 4 }}>第 {ch} 章 <span style={{ color: 'var(--muted)', fontSize: 12 }}>发现数逐版本收敛:</span></div>
              <div style={{ display: 'flex', gap: 6, alignItems: 'flex-end', height: 40 }}>
                {versions.map((v: any) => (
                  <div key={v.version} style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 2 }}>
                    <div style={{ width: 26, height: Math.min(36, v.findings * 4 + 4), background: v.findings ? 'var(--sem-warn)' : 'var(--sem-pass)', opacity: .7, borderRadius: 3 }} />
                    <span className="mono" style={{ fontSize: 10.5, color: 'var(--muted)' }}>v{v.version}:{v.findings}</span>
                  </div>
                ))}
              </div>
            </div>
          ))}
          {Object.keys(data?.convergence || {}).length === 0 && <div style={{ color: 'var(--muted)' }}>最近章节均为一稿过门。</div>}
        </Card>
      </div>
    </div>
  )
}
