import { useEffect, useRef, useState } from 'react'
import { useParams } from 'react-router-dom'
import { useQueryClient } from '@tanstack/react-query'
import { useApi, useQuery, useBookNavigate, BookLink, useFilters } from '../api/scope'
import { Card, Modal, PageHeader, PageState, StatusBadge, useToast } from '../components/ui'
import { DirectorDecisions, StartRunCard } from '../components/Director'
import { label } from '../components/labels'

function DecisionQueue({
  runId,
  decisions,
  onDone,
}: {
  runId: string
  decisions: any[]
  onDone: () => void
}) {
  const api = useApi(),
    push = useToast((s) => s.push),
    [answering, setAnswering] = useState<any>(null),
    [answers, setAnswers] = useState<Record<string, string>>({}),
    [busy, setBusy] = useState(false)
  const open = decisions.filter(
    (d) => d.status === 'open' && !['steering_point', 'plan_approval'].includes(d.decision_type),
  )
  async function submit(d: any) {
    setBusy(true)
    try {
      if (d.decision_type === 'author_question') {
        const questions = d.author_questions?.length ? d.author_questions : [d.prompt]
        await api.post(`/api/v1/runs/${runId}/decisions/${d.decision_id}/answer`, {
          answers: questions.map((q: string) => ({
            question: q,
            answer: answers[q],
          })),
        })
      } else
        await api.call('novel_run_decision_submit', {
          run_id: runId,
          decision_id: d.decision_id,
          resolution: { action: 'resume' },
        })
      await api.postJob('novel_run_continue', { run_id: runId, max_steps: 50 })
      setAnswering(null)
      push('ok', '决策已提交')
      onDone()
    } catch (e) {
      push('err', (e as Error).message)
    } finally {
      setBusy(false)
    }
  }
  if (!open.length) return null
  return (
    <Card title="等待你的决定" extra={<StatusBadge tone="warn">{open.length} 项待处理</StatusBadge>}>
      {open.map((d) => (
        <div className="decision-row" key={d.decision_id}>
          <div>
            <StatusBadge tone={d.decision_type === 'author_question' ? 'warn' : 'block'}>
              {d.decision_type === 'author_question' ? '创作问题' : '运行异常'}
            </StatusBadge>
            <p>{d.prompt}</p>
            {d.context?.traceback && (
              <details>
                <summary>技术详情</summary>
                <pre>{d.context.traceback}</pre>
              </details>
            )}
          </div>
          <button
            className="btn primary"
            disabled={busy}
            onClick={() =>
              d.decision_type === 'author_question' ? (setAnswering(d), setAnswers({})) : void submit(d)
            }
          >
            {d.decision_type === 'author_question' ? '回答' : '重试'}
          </button>
        </div>
      ))}
      {answering && (
        <Modal
          title="给故事一个方向"
          onClose={busy ? undefined : () => setAnswering(null)}
          actions={
            <button
              className="btn primary"
              disabled={
                busy ||
                (answering.author_questions?.length ? answering.author_questions : [answering.prompt]).some(
                  (q: string) => !answers[q]?.trim(),
                )
              }
              onClick={() => void submit(answering)}
            >
              {busy ? '提交中…' : '提交决定'}
            </button>
          }
        >
          {(answering.author_questions?.length ? answering.author_questions : [answering.prompt]).map(
            (q: string) => (
              <label className="field-label interview-question" key={q}>
                {q}
                <textarea
                  className="input"
                  rows={3}
                  value={answers[q] || ''}
                  onChange={(e) => setAnswers((a) => ({ ...a, [q]: e.target.value }))}
                />
              </label>
            ),
          )}
        </Modal>
      )}
    </Card>
  )
}
function LiveMonitor({ runId }: { runId: string }) {
  const api = useApi(),
    qc = useQueryClient(),
    push = useToast((s) => s.push)
  const [events, setEvents] = useState<any[]>([]),
    [status, setStatus] = useState<any>(null),
    [connection, setConnection] = useState('连接中'),
    [follow, setFollow] = useState(true),
    [busy, setBusy] = useState(false)
  const container = useRef<HTMLDivElement>(null)
  useEffect(() => {
    let alive = true
    setEvents([])
    setStatus(null)
    setConnection('连接中')
    api
      .get('/api/v1/runs/' + runId)
      .then((d) => {
        if (alive) {
          setEvents(d.events || [])
          setStatus(d.run)
        }
      })
      .catch(() => {
        if (alive) setConnection('暂时无法连接')
      })
    const es = new EventSource(api.url('/api/v1/stream/runs/' + runId))
    es.addEventListener('run_event', (e) => {
      const event = JSON.parse((e as MessageEvent).data)
      setEvents((prev) =>
        prev.some((x) => x.id === event.id) ? prev : [...prev, event].sort((a, b) => a.id - b.id).slice(-300),
      )
      void qc.invalidateQueries({ queryKey: ['run', runId] })
    })
    es.addEventListener('run_status', (e) => {
      setStatus(JSON.parse((e as MessageEvent).data))
      setConnection('实时连接')
    })
    es.onerror = () => setConnection('连接中断，正在重连')
    return () => {
      alive = false
      es.close()
    }
  }, [runId, api])
  useEffect(() => {
    if (follow && container.current) container.current.scrollTop = container.current.scrollHeight
  }, [events.length, follow])
  async function control(action: string) {
    setBusy(true)
    try {
      if (action === 'pause')
        await api.call('novel_run_pause', {
          run_id: runId,
          reason: '工作台暂停',
        })
      else {
        if (status?.status === 'paused') await api.call('novel_run_resume', { run_id: runId })
        await api.postJob('novel_run_continue', {
          run_id: runId,
          max_steps: 50,
        })
      }
      await qc.invalidateQueries()
      push('ok', action === 'pause' ? '已请求暂停' : '继续创作已提交')
    } catch (e) {
      push('err', (e as Error).message)
    } finally {
      setBusy(false)
    }
  }
  const runChapter = status?.status === 'completed' ? status.config?.target_chapter : status?.current_chapter
  const phase = events.filter((e) => e.chapter === runChapter).slice(-1)[0]?.phase
  return (
    <>
      <Card
        title={
          (status?.status === 'completed' ? '最近创作' : '当前创作') +
          (runChapter ? ' · 第 ' + runChapter + ' 章' : '')
        }
        extra={
          <div className="toolbar">
            <span className="small muted">{connection}</span>
            {status?.status === 'running' ? (
              <>
                <button className="btn sm" disabled={busy} onClick={() => void control('pause')}>
                  暂停
                </button>
                <button className="btn sm primary" disabled={busy} onClick={() => void control('continue')}>
                  继续推进
                </button>
              </>
            ) : status?.status === 'paused' ? (
              <button className="btn primary sm" disabled={busy} onClick={() => void control('continue')}>
                恢复运行
              </button>
            ) : null}
          </div>
        }
      >
        <div className="pipeline-row">
          <StatusBadge status={status?.status} />
          <div className="pipeline">
            {['plan', 'draft', 'review', 'revise', 'commit'].map((p, i) => (
              <span className={phase === p && status?.status === 'running' ? 'current' : ''} key={p}>
                <i>{i + 1}</i>
                {label(p)}
              </span>
            ))}
          </div>
        </div>
      </Card>
      <Card
        title="实时活动"
        extra={
          <label className="small muted">
            <input type="checkbox" checked={follow} onChange={(e) => setFollow(e.target.checked)} /> 跟随最新
          </label>
        }
      >
        <div className="event-feed" ref={container}>
          {events.map((e) => (
            <div className="event-row" key={e.id}>
              <time>{e.created_at}</time>
              <span>第 {e.chapter || '—'} 章</span>
              <strong>{label(e.phase)}</strong>
              <StatusBadge status={e.status} />
              <span className="event-note">
                {label(e.detail?.reason || e.detail?.note || e.detail?.decision_type || e.detail?.verdict)}
              </span>
            </div>
          ))}
          {!events.length && <PageState empty title="等待第一条创作记录" />}
        </div>
      </Card>
    </>
  )
}
export default function RunCenter() {
  const api = useApi(),
    { runId } = useParams(),
    navigate = useBookNavigate(),
    qc = useQueryClient(),
    { params } = useFilters()
  const query = useQuery({
    queryKey: ['runs'],
    queryFn: () => api.get('/api/v1/runs'),
    refetchInterval: 8000,
  })
  const runs = query.data?.runs || [],
    active = runId || runs[0]?.run_id
  const detail = useQuery({
    queryKey: ['run', active],
    queryFn: () => api.get('/api/v1/runs/' + active),
    enabled: !!active,
    refetchInterval: 8000,
  })
  const decisions = (detail.data?.open_decisions || []).filter((d: any) => d.status === 'open')
  const refresh = () => {
    void qc.invalidateQueries()
  }
  return (
    <div className="page-stack">
      <PageHeader title="运行中心" description="把握创作进度，在关键时刻给故事一个方向" />
      <PageState loading={query.isPending} error={query.error} onRetry={() => void query.refetch()} />
      {query.data && (
        <div className="run-grid">
          <aside className="run-history">
            <Card title="运行记录">
              {runs.map((r: any) => (
                <button
                  className={'run-record ' + (r.run_id === active ? 'selected' : '')}
                  key={r.run_id}
                  onClick={() => navigate('/runs/' + r.run_id)}
                >
                  <div className="toolbar">
                    <StatusBadge status={r.status} />
                    <small>{r.created_at?.slice(5, 16)}</small>
                  </div>
                  <p>
                    第 {r.start_chapter}—{r.config?.target_chapter || '待定'} 章
                  </p>
                  <small>已定稿 {r.chapters_committed} 章</small>
                </button>
              ))}
              {!runs.length && <p className="small muted">暂无运行记录</p>}
            </Card>
          </aside>
          <div className="page-stack">
            {!runs.some((r: any) => ['running', 'paused', 'needs_author_decision'].includes(r.status)) && (
              <StartRunCard />
            )}
            {active && (
              <>
                <PageState
                  loading={detail.isPending}
                  error={detail.error}
                  onRetry={() => void detail.refetch()}
                />
                {params.get('task') === 'decisions' && !decisions.length && (
                  <div className="notice">当前运行没有待决问题。</div>
                )}
                <DirectorDecisions runId={active} decisions={decisions} onDone={refresh} />
                <DecisionQueue runId={active} decisions={decisions} onDone={refresh} />
                <LiveMonitor key={active} runId={active} />
                {detail.data && (
                  <Card title="本轮已完成章节">
                    {detail.data.chapters.map((c: any) => (
                      <BookLink className="list-row" key={c.chapter} to={'/studio/' + c.chapter}>
                        <strong>第 {c.chapter} 章</strong>
                        <span>{c.title}</span>
                        <small>{c.chars} 字 ↗</small>
                      </BookLink>
                    ))}
                    <details>
                      <summary>运行配置与技术记录</summary>
                      <pre>{JSON.stringify(detail.data.run?.config, null, 2)}</pre>
                    </details>
                  </Card>
                )}
              </>
            )}
          </div>
        </div>
      )}
    </div>
  )
}
