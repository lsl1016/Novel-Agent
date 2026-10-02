import { useEffect, useRef, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { api, sseUrl } from '../api/client'
import { ActionButton, Card, Modal, Pill, useToast } from '../components/ui'
import { useSession } from '../stores/session'

const PHASES = ['run', 'plan', 'draft', 'review', 'revise', 'commit']

function phaseTone(status?: string) {
  if (status === 'ready' || status === 'committed' || status === 'pass' || status === 'resolved') return 'pass' as const
  if (status === 'blocked' || status === 'failed' || status === 'error') return 'block' as const
  if (status === 'revising' || status === 'warn' || status === 'opened') return 'warn' as const
  return 'muted' as const
}

function shPhase(p?: string) {
  return ({ run: '运行', plan: '计划', draft: '草稿', review: '审校', revise: '修订', commit: '提交', chapter: '章节', decision: '决策', planning: '计划' } as any)[p || ''] || p
}

/** HITL 决策作答:作者提问逐条填写;错误类决策一键恢复重试 */
function DecisionQueue({ runId }: { runId: string }) {
  const [answering, setAnswering] = useState<any | null>(null)
  const [answers, setAnswers] = useState<Record<string, string>>({})
  const [busy, setBusy] = useState(false)
  const push = useToast((s) => s.push)
  const qc = useQueryClient()
  const { data } = useQuery({ queryKey: ['run', runId], queryFn: () => api.get(`/api/v1/runs/${runId}`), refetchInterval: 8000 })
  const open = (data?.open_decisions || []).filter((d: any) => d.status === 'open')
  if (!open.length) return null

  async function submit() {
    setBusy(true)
    try {
      const payload = {
        answers: (answering.author_questions || []).map((q: string) => ({ question: q, answer: answers[q] || '作者拍板:由作者在工位上审阅后默认采用保守自洽处理' })),
      }
      const out = await api.post(`/api/v1/runs/${runId}/decisions/${answering.decision_id}/answer`, payload)
      if (out?.ok) {
        push('ok', '决策已提交,运行恢复')
        setAnswering(null)
        qc.invalidateQueries({ queryKey: ['run', runId] })
        qc.invalidateQueries({ queryKey: ['runs'] })
      } else push('err', '提交失败')
    } catch (e: any) {
      push('err', e.message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <Card title="待决问题(人在回路)" extra={<Pill tone="warn">{open.length} 项待决 · 运行已暂停</Pill>}>
      {open.map((d: any) => (
        <div key={d.decision_id} className="row-hover" style={{ display: 'flex', gap: 10, alignItems: 'flex-start', padding: '8px 6px', borderRadius: 6, borderBottom: '1px solid var(--line)' }}>
          <Pill tone={d.decision_type === 'author_question' ? 'accent' : 'block'}>{d.decision_type === 'author_question' ? '提问' : '异常'}</Pill>
          <div style={{ flex: 1, minWidth: 0 }}>
            <div style={{ fontSize: 13, lineHeight: 1.7 }}>{d.prompt}</div>
            {d.author_questions?.length > 0 && (
              <div style={{ color: 'var(--muted)', fontSize: 12, marginTop: 4 }}>{d.author_questions.length} 个子问题</div>
            )}
            {d.context?.traceback && <pre style={{ color: 'var(--sem-block)', fontSize: 11, margin: '6px 0 0', whiteSpace: 'pre-wrap', maxHeight: 90, overflow: 'hidden' }}>{d.context.traceback.slice(0, 400)}</pre>}
          </div>
          {d.decision_type === 'author_question' ? (
            <button className="btn primary sm" onClick={() => { setAnswering(d); setAnswers({}) }}>作答</button>
          ) : (
            <ActionButton tool="novel_run_decision_submit" label="恢复重试" variant="gold"
              args={{ run_id: runId, decision_id: d.decision_id, resolution: { action: 'resume' } }}
              onDone={() => { qc.invalidateQueries({ queryKey: ['run', runId] }); qc.invalidateQueries({ queryKey: ['runs'] }) }} />
          )}
        </div>
      ))}

      {answering && (
        <Modal title={`回答作者的 ${answering.author_questions?.length || 1} 个问题`}
          sub="答案会写入蓝图 author_decisions,规划器后续不再重复提问,并作为本章计划的创作依据。"
          onClose={() => setAnswering(null)}
          actions={<button className="btn primary" disabled={busy} onClick={submit}>{busy && <span className="spin" />}提交并恢复运行</button>}>
          {(answering.author_questions || [answering.prompt]).map((q: string, i: number) => (
            <div key={i} style={{ marginBottom: 14 }}>
              <div style={{ fontSize: 13, lineHeight: 1.7, marginBottom: 6 }}>{i + 1}. {q}</div>
              <textarea className="paper-edit" style={{ minHeight: 74, fontSize: 14, fontFamily: 'var(--font-ui)' }}
                placeholder="你的裁决(留空则默认保守自洽处理)…"
                value={answers[q] || ''} onChange={(e) => setAnswers((a) => ({ ...a, [q]: e.target.value }))} />
            </div>
          ))}
        </Modal>
      )}
    </Card>
  )
}

/** 实时流水线监视器:SSE 增量事件 + 状态胶囊 + 运行控制 */
function LiveMonitor({ runId }: { runId: string }) {
  const [events, setEvents] = useState<any[]>([])
  const [status, setStatus] = useState<any>(null)
  const [live, setLive] = useState(true)
  const qc = useQueryClient()
  const role = useSession((s) => s.role)
  const canControl = role === 'controller' || role === 'admin'
  const bottomRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    api.get(`/api/v1/runs/${runId}`).then((d) => { setEvents(d.events || []); setStatus(d.run) })
    const es = new EventSource(sseUrl(`/api/v1/stream/runs/${runId}`))
    es.addEventListener('run_event', (e) => {
      const payload = JSON.parse((e as MessageEvent).data)
      setEvents((prev) => (prev.length && prev[prev.length - 1].id >= payload.id ? prev : [...prev, payload].slice(-300)))
    })
    es.addEventListener('run_status', (e) => { setStatus(JSON.parse((e as MessageEvent).data)); setLive(true) })
    es.onerror = () => setLive(false)
    return () => es.close()
  }, [runId])

  useEffect(() => { bottomRef.current?.scrollIntoView({ block: 'end' }) }, [events.length])

  const running = status?.status === 'running'
  const currentPhase = running ? events.filter((e) => e.chapter === status.current_chapter).map((e) => e.phase).pop() : null
  const refresh = () => { qc.invalidateQueries({ queryKey: ['runs'] }); qc.invalidateQueries({ queryKey: ['run', runId] }) }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
      <Card title="流水线" extra={
        <span style={{ display: 'inline-flex', gap: 8, alignItems: 'center' }}>
          <Pill tone={live ? 'pass' : 'muted'}>{live ? '● 实时' : '连接断开'}</Pill>
          {canControl && (running ? (
            <ActionButton tool="novel_run_pause" label="暂停" variant="danger" args={{ run_id: runId, reason: '工作台手动暂停' }} onDone={refresh} />
          ) : status?.status === 'paused' ? (
            <ActionButton tool="novel_run_resume" label="恢复" variant="primary" args={{ run_id: runId }} onDone={refresh} />
          ) : null)}
        </span>
      }>
        <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
          {status ? (
            <>
              <Pill tone={running ? 'pass' : status.status === 'needs_author_decision' ? 'warn' : 'muted'}>{status.status}</Pill>
              <span style={{ color: 'var(--muted)' }}>第 {status.current_chapter} 章</span>
              <span style={{ display: 'inline-flex', gap: 6 }}>
                {PHASES.map((ph) => (
                  <span key={ph} style={{
                    padding: '3px 12px', borderRadius: 999, fontSize: 12,
                    border: `1px solid ${currentPhase === ph ? 'var(--sem-pass)' : 'var(--line)'}`,
                    color: currentPhase === ph ? 'var(--sem-pass)' : 'var(--muted)',
                    background: currentPhase === ph ? 'var(--panel-2)' : 'transparent',
                    transition: 'all .3s',
                  }}>{shPhase(ph)}</span>
                ))}
              </span>
              <span style={{ marginLeft: 'auto', color: 'var(--muted)', fontFamily: 'var(--font-mono)', fontSize: 12 }}>本轮提交 {status.chapters_committed} 章</span>
            </>
          ) : <span style={{ color: 'var(--muted)' }}>连接中…</span>}
        </div>
      </Card>

      <Card title="事件流">
        <div style={{ maxHeight: 420, overflow: 'auto', fontFamily: 'var(--font-mono)', fontSize: 12.5 }}>
          {events.map((e) => (
            <div key={e.id} style={{ display: 'flex', gap: 10, padding: '3px 0', borderBottom: '1px solid var(--line)' }}>
              <span style={{ color: 'var(--muted)', minWidth: 118 }}>{(e.created_at || '').slice(5, 19)}</span>
              {e.chapter != null && <span style={{ color: 'var(--sem-canon)', minWidth: 36 }}>ch{e.chapter}</span>}
              <span style={{ minWidth: 44, color: 'var(--sem-draft)' }}>{shPhase(e.phase)}</span>
              <Pill tone={phaseTone(e.status)}>{e.status}</Pill>
              <span style={{ color: 'var(--muted)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', flex: 1 }}>
                {e.detail?.reason || e.detail?.note || e.detail?.decision_type || e.detail?.verdict || ''}
              </span>
            </div>
          ))}
          <div ref={bottomRef} />
        </div>
      </Card>
    </div>
  )
}

export default function RunCenter() {
  const { runId } = useParams()
  const navigate = useNavigate()
  const { data } = useQuery({ queryKey: ['runs'], queryFn: () => api.get('/api/v1/runs') })
  const runs = data?.runs || []
  const active = runId || runs[0]?.run_id
  const { data: detail } = useQuery({ queryKey: ['run', active], queryFn: () => api.get(`/api/v1/runs/${active}`), enabled: !!active })

  return (
    <div style={{ display: 'grid', gridTemplateColumns: '262px 1fr', gap: 14 }}>
      <Card title="运行记录">
        {runs.map((r: any) => (
          <div key={r.run_id} className={`row-hover${r.run_id === active ? ' active' : ''}`}
            onClick={() => navigate(`/runs/${r.run_id}`)}
            style={{ padding: '8px 8px', borderRadius: 'var(--radius)',
              background: r.run_id === active ? 'var(--panel-2)' : 'transparent' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <code style={{ fontSize: 11 }}>{r.run_id.slice(4, 12)}</code>
              <Pill tone={r.status === 'running' ? 'pass' : r.status === 'paused' || r.status === 'needs_author_decision' ? 'warn' : 'muted'}>{r.status === 'needs_author_decision' ? '待决策' : r.status}</Pill>
            </div>
            <div style={{ color: 'var(--muted)', fontSize: 12, marginTop: 3, fontFamily: 'var(--font-mono)' }}>
              ch{r.start_chapter} → {r.config?.target_chapter ?? '∞'} · 已提交 {r.chapters_committed}
            </div>
          </div>
        ))}
      </Card>

      <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
        {active ? (
          <>
            <DecisionQueue runId={active} />
            <LiveMonitor runId={active} />
            {detail && (
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 14 }}>
                <Card title="本轮章节">
                  <div style={{ maxHeight: 220, overflow: 'auto' }}>
                    {detail.chapters?.map((c: any) => (
                      <div key={c.chapter} className="row-hover" onClick={() => navigate(`/studio/${c.chapter}`)}
                        style={{ display: 'flex', gap: 10, padding: '4px 6px', borderBottom: '1px solid var(--line)', fontSize: 13, borderRadius: 4 }}>
                        <span style={{ color: 'var(--sem-canon)', minWidth: 36, fontFamily: 'var(--font-mono)' }}>ch{c.chapter}</span>
                        <span style={{ flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{c.title}</span>
                        <span style={{ color: 'var(--muted)', fontFamily: 'var(--font-mono)' }}>{c.chars}字</span>
                      </div>
                    ))}
                  </div>
                </Card>
                <Card title="运行配置">
                  <dl style={{ margin: 0, display: 'grid', gridTemplateColumns: 'auto 1fr', gap: '4px 14px', fontSize: 13, color: 'var(--muted)' }}>
                    {Object.entries(detail.run?.config || {}).map(([k, v]) => [
                      <dt key={k} style={{ fontFamily: 'var(--font-mono)', fontSize: 12 }}>{k}</dt>,
                      <dd key={k + 'v'} style={{ margin: 0 }}>{String(v)}</dd>,
                    ])}
                  </dl>
                  {detail.run?.stop_reason && (
                    <div style={{ marginTop: 10, color: 'var(--sem-warn)', fontSize: 13 }}>停止原因:{JSON.stringify(detail.run.stop_reason)}</div>
                  )}
                </Card>
              </div>
            )}
          </>
        ) : (
          <Card><span style={{ color: 'var(--muted)' }}>尚无运行记录 —— 可经 CLI(scripts/stress/drive.py)或 MCP 工具 novel_run_start 启动长跑</span></Card>
        )}
      </div>
    </div>
  )
}
