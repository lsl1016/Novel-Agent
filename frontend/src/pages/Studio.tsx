import { useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from '../api/client'
import { ActionButton, Card, Pill, verdictTone, useToast } from '../components/ui'
import { useSession } from '../stores/session'

/** 写作工作室:左栏 = 计划/版本/审校/定稿门(含定稿动作);主区 = 纸页正文(可编辑草稿) */
export default function Studio() {
  const params = useParams()
  const navigate = useNavigate()
  const role = useSession((s) => s.role)
  const push = useToast((s) => s.push)
  const qc = useQueryClient()
  const [showDraft, setShowDraft] = useState(false)
  const [editing, setEditing] = useState(false)
  const [editBody, setEditBody] = useState('')
  const [saving, setSaving] = useState(false)

  const { data: home } = useQuery({ queryKey: ['home'], queryFn: () => api.get('/api/v1/home') })
  const latest = home?.progress?.latest_chapter || 1
  const chapter = params.chapter === 'latest' ? latest : Number(params.chapter) || 1

  const { data: ws, isLoading } = useQuery({
    queryKey: ['chapter', chapter],
    queryFn: () => api.get(`/api/v1/chapter/${chapter}`),
    refetchInterval: 15000,
  })
  const canWrite = !!role && !['viewer', 'writer'].includes(role)
  const { data: draft } = useQuery({
    queryKey: ['draft', chapter, ws?.latest_draft_version],
    queryFn: () => api.get(`/api/v1/chapter/${chapter}/draft/${ws?.latest_draft_version}`),
    enabled: canWrite && !!ws?.latest_draft_version && showDraft,
  })

  const prose = showDraft && (draft as any)?.body ? (draft as any).body : ws?.canon?.body
  const gate = ws?.gate

  async function saveDraft() {
    setSaving(true)
    try {
      const d: any = draft
      const out = await api.action('chapter_draft_save', {
        chapter, title: d?.title || ws?.canon?.title || `第${chapter}章`,
        body: editBody, arc: d?.arc || ws?.canon?.arc || '', pov: d?.pov || ws?.canon?.pov || '',
        summary: d?.summary || ws?.canon?.summary || '', declared_updates: d?.declared_updates || {},
        source: 'web_edit',
      })
      if (out?.errNo === 0) {
        push('ok', `已保存为新草稿版本(基于 v${ws?.latest_draft_version})`)
        setEditing(false)
        qc.invalidateQueries({ queryKey: ['chapter', chapter] })
      } else {
        push('err', `保存失败:${out?.errMsg}`)
      }
    } catch (e: any) {
      push('err', e.message)
    } finally {
      setSaving(false)
    }
  }

  return (
    <div style={{ display: 'grid', gridTemplateColumns: '312px 1fr', gap: 14, height: '100%' }}>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 14, overflow: 'auto' }}>
        <Card title={`第 ${chapter} 章`}>
          <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
            <button className="btn sm" onClick={() => navigate(`/studio/${Math.max(1, chapter - 1)}`)}>‹ 上一章</button>
            <input className="num" value={chapter} onChange={(e) => { const v = Number(e.target.value); if (v > 0) navigate(`/studio/${v}`) }} />
            <button className="btn sm" onClick={() => navigate(`/studio/${chapter + 1}`)}>下一章 ›</button>
            <button className="btn sm ghost" style={{ marginLeft: 'auto' }} onClick={() => navigate('/studio/latest')}>最新</button>
          </div>
        </Card>

        {gate && (
          <Card title="定稿检查单"
            extra={ws?.canon ? <Pill tone="canon">已入正典</Pill> : gate.ready ? <Pill tone="pass">可定稿</Pill> : <Pill tone="muted">未就绪</Pill>}>
            {gate.checks?.map((c: any) => (
              <div key={c.key} style={{ display: 'flex', gap: 8, alignItems: 'center', padding: '4px 0', fontSize: 13 }}>
                <span style={{ color: c.ok ? 'var(--sem-pass)' : 'var(--sem-block)' }}>{c.ok ? '✓' : '✗'}</span>
                <span>{gateLabel(c.key)}</span>
                {!c.ok && c.missing && <span style={{ color: 'var(--muted)', fontSize: 12 }}>缺:{c.missing.join(', ')}</span>}
                {c.verdict && <Pill tone={verdictTone(c.verdict)}>{c.verdict}</Pill>}
              </div>
            ))}
            <hr className="divider" />
            <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
              {canWrite && !ws?.canon && gate.ready && (
                <ActionButton tool="chapter_finalize" variant="gold" label={`定稿 v${gate.draft_version} 入正典`}
                  confirm={{ title: `把第 ${chapter} 章 v${gate.draft_version} 提交为正典?`, sub: '定稿走服务端提交闸门:正典写入、声明更新、状态推进均原子完成;此动作进入版本史。' }}
                  args={{ chapter, version: gate.draft_version, allow_warnings: true }}
                  onDone={() => { qc.invalidateQueries({ queryKey: ['chapter', chapter] }); qc.invalidateQueries({ queryKey: ['home'] }); qc.invalidateQueries({ queryKey: ['home-mini'] }) }} />
              )}
              <span style={{ color: 'var(--muted)', fontSize: 11.5, lineHeight: 1.6 }}>
                {ws?.canon ? '本章已定稿;编辑需从草稿重新走审校门。' : '闸门条件由服务端判定,前端只呈现。'}
              </span>
            </div>
          </Card>
        )}

        {canWrite && ws?.drafts?.length > 0 && (
          <Card title="草稿版本">
            {ws.drafts.map((d: any) => (
              <div key={d.version} style={{ display: 'flex', gap: 8, alignItems: 'center', padding: '4px 0', fontSize: 13, borderBottom: '1px solid var(--line)' }}>
                <span style={{ fontFamily: 'var(--font-mono)', color: d.status === 'committed' ? 'var(--sem-canon)' : 'var(--sem-draft)' }}>v{d.version}</span>
                <Pill tone={d.status === 'committed' ? 'canon' : 'draft'}>{d.status}</Pill>
                <span className="tag" style={{ marginLeft: 'auto' }}>{d.source}</span>
              </div>
            ))}
          </Card>
        )}

        {ws?.reviews?.length > 0 && (
          <Card title="审校结论">
            {ws.reviews.map((r: any) => (
              <div key={r.reviewer_type} style={{ display: 'flex', gap: 8, alignItems: 'center', padding: '4px 0', fontSize: 13, borderBottom: '1px solid var(--line)' }}>
                <span style={{ flex: 1, color: r.reviewer_type.startsWith('semantic') ? 'var(--sem-secret)' : undefined }}>{reviewerLabel(r.reviewer_type)}</span>
                {r.findings > 0 && <span style={{ color: 'var(--muted)', fontSize: 12 }}>{r.findings} 项发现</span>}
                <Pill tone={verdictTone(r.verdict)}>{r.verdict}</Pill>
              </div>
            ))}
          </Card>
        )}
      </div>

      {/* 纸页书房 */}
      <div data-surface="paper" style={{ overflow: 'auto', borderRadius: 8, border: '1px solid var(--line)' }}>
        <div style={{ maxWidth: 680, margin: '0 auto', padding: '44px 32px 80px' }}>
          {isLoading ? (
            <div style={{ color: 'var(--muted)' }}>加载中…</div>
          ) : editing ? (
            <>
              <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 16 }}>
                <strong style={{ fontFamily: 'var(--font-prose)', fontSize: 18 }}>编辑草稿 v{ws?.latest_draft_version} → 新版本</strong>
                <div style={{ flex: 1 }} />
                <button className="btn" disabled={saving} onClick={() => { setEditing(false); setEditBody('') }}>放弃</button>
                <button className="btn primary" disabled={saving || !editBody.trim()} onClick={saveDraft}>{saving && <span className="spin" />}保存为新草稿</button>
              </div>
              <textarea className="paper-edit" style={{ minHeight: 520 }} value={editBody} onChange={(e) => setEditBody(e.target.value)} />
              <div style={{ color: 'var(--muted)', fontSize: 12, marginTop: 8 }}>
                保存为非正典草稿(chapter_draft_save);定稿仍需走左侧闸门。原文{editBody.length ? `现 ${editBody.length} 字` : ''}。
              </div>
            </>
          ) : !prose ? (
            <div style={{ color: 'var(--muted)', lineHeight: 2 }}>
              {showDraft ? '此章暂无草稿正文。' : '此章尚未提交正典。'}
              {canWrite && !showDraft && ws?.latest_draft_version && (
                <a onClick={() => setShowDraft(true)} style={{ color: '#7c5c1e', cursor: 'pointer' }}> 查看最新草稿 v{ws.latest_draft_version} →</a>
              )}
            </div>
          ) : (
            <>
              <div style={{ display: 'flex', alignItems: 'baseline', gap: 12, borderBottom: '1px solid var(--line)', paddingBottom: 14, marginBottom: 22 }}>
                <span style={{ fontFamily: 'var(--font-prose)', fontSize: 22, fontWeight: 700 }}>
                  第{chapter}章 {(showDraft ? (draft as any)?.title : ws?.canon?.title) || ''}
                </span>
                {showDraft ? <Pill tone="draft">草稿 v{ws?.latest_draft_version}</Pill> : <Pill tone="canon">正典</Pill>}
                <div style={{ marginLeft: 'auto', display: 'inline-flex', gap: 8 }}>
                  {canWrite && showDraft && !editing && (
                    <button className="btn sm" onClick={() => { setEditBody((draft as any)?.body || ''); setEditing(true) }}>✎ 编辑此稿</button>
                  )}
                  {canWrite && ws?.latest_draft_version && !showDraft && (
                    <button className="btn sm" onClick={() => setShowDraft(true)}>切到草稿</button>
                  )}
                  {showDraft && (
                    <button className="btn sm" onClick={() => { setShowDraft(false); setEditing(false) }}>切到正典</button>
                  )}
                </div>
              </div>
              {ws?.canon?.summary && !showDraft && (
                <p style={{ color: 'var(--muted)', fontSize: 13, margin: '0 0 20px' }}>{ws.canon.summary}</p>
              )}
              <article style={{ fontFamily: 'var(--font-prose)', fontSize: 17, lineHeight: 1.9, whiteSpace: 'pre-wrap' }}>
                {prose}
              </article>
            </>
          )}
        </div>
      </div>
    </div>
  )
}

function gateLabel(key: string) {
  return ({ draft_exists: '存在草稿', plan_valid: '章节计划有效', reviews_complete: '审校齐全', review_verdict_ok: '审校结论可过' } as any)[key] || key
}

function reviewerLabel(t: string) {
  return ({
    knowledge_leak: '知识泄漏', continuity: '连续性', narrative: '叙事义务', character: '人物状态',
    semantic_knowledge_leak: '语义·泄漏', semantic_character: '语义·人物', semantic_narrative: '语义·叙事', semantic_pacing: '语义·节奏',
  } as any)[t] || t
}
