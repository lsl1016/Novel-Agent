import { useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { api, pollJob } from '../api/client'
import { Card, Modal, Pill, useToast } from '../components/ui'
import { useSession } from '../stores/session'

/** 导演台(v0.11):章节边界的人工引导 — steering_point 决策卡 +
 *  AI 走向提案(作业) + plan_approval 审核卡。挂在运行中心。 */

function SteeringCard({ runId, d, onDone }: { runId: string; d: any; onDone: () => void }) {
  const [directive, setDirective] = useState('')
  const [focus, setFocus] = useState('')
  const [proposing, setProposing] = useState(false)
  const [options, setOptions] = useState<any[] | null>(null)
  const [picked, setPicked] = useState<number | null>(null)
  const [submitting, setSubmitting] = useState(false)
  const push = useToast((s) => s.push)
  const chapter = d.chapter

  async function propose() {
    setProposing(true); setOptions(null)
    try {
      const job = await api.postJob('chapter_direction_propose', {
        chapter, count: 3, ...(focus.trim() ? { focus: focus.trim() } : {}),
      })
      const out = await pollJob(job.job.id)
      setOptions(out.options || [])
      push('ok', `模型提出 ${out.options?.length || 0} 个走向候选`)
    } catch (e: any) {
      push('err', `提案失败:${e.message}`)
    } finally {
      setProposing(false)
    }
  }

  async function submit(text: string) {
    setSubmitting(true)
    try {
      const out = await api.action('novel_run_decision_submit', {
        run_id: runId, decision_id: d.decision_id,
        resolution: { action: 'resume', ...(text.trim() ? { directive: text.trim() } : {}) },
      })
      if (out?.errNo === 0) {
        push('ok', text.trim() ? `第 ${chapter} 章指令已生效,继续规划` : `第 ${chapter} 章按自动规划继续`)
        onDone()
      } else push('err', out?.errMsg || '提交失败')
    } catch (e: any) {
      push('err', e.message)
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <Card title={`🎬 第 ${chapter} 章待导演`} extra={<Pill tone="accent">steering_point</Pill>}>
      <div style={{ color: 'var(--muted)', fontSize: 12.5, marginBottom: 8, lineHeight: 1.7 }}>
        上一章已提交,运行暂停等待你的引导。指令会注入规划器上下文并约束本章 primary_goal 与情节安排;计划生成后自动销账,不影响后续章节。
      </div>
      <textarea className="paper-edit" style={{ minHeight: 84, fontFamily: 'var(--font-ui)', fontSize: 14 }}
        placeholder="例如:本章让主角夜探界墙,遭遇黑衣人但避免正面冲突;埋一条'对方也认得这柄剑'的线索。留空 = 交还给自动规划。"
        value={directive} onChange={(e) => setDirective(e.target.value)} />
      <div style={{ display: 'flex', gap: 10, marginTop: 10, alignItems: 'center', flexWrap: 'wrap' }}>
        <input className="input" style={{ width: 260 }} placeholder="AI 提案的关注点(可选),如'重点推进身世线'"
          value={focus} onChange={(e) => setFocus(e.target.value)} />
        <button className="btn" disabled={proposing} onClick={propose}>{proposing && <span className="spin" />}让模型提案走向(20-60 秒)</button>
        <div style={{ flex: 1 }} />
        <button className="btn ghost" disabled={submitting} onClick={() => submit('')}>跳过(自动规划)</button>
        <button className="btn primary" disabled={submitting || !directive.trim()} onClick={() => submit(directive)}>
          {submitting && <span className="spin" />}按此指令继续
        </button>
      </div>

      {options && (
        <div style={{ marginTop: 14, display: 'flex', flexDirection: 'column', gap: 8 }}>
          {options.map((o: any, i: number) => (
            <div key={i} onClick={() => { setPicked(i); setDirective(`${o.title}:${o.sketch}\n要点:${(o.beats || []).join(';')}`) }}
              style={{ border: `1px solid ${picked === i ? 'var(--accent)' : 'var(--line)'}`, borderRadius: 8, padding: 12, cursor: 'pointer',
                background: picked === i ? 'var(--accent-bg)' : 'var(--panel)', transition: 'all .15s' }}>
              <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
                <b style={{ fontSize: 14 }}>{o.title}</b>
                {o.threads?.length > 0 && <span className="tag">{o.threads.join(',')}</span>}
              </div>
              <div style={{ fontSize: 13, lineHeight: 1.7, marginTop: 4 }}>{o.sketch}</div>
              {o.beats?.length > 0 && (
                <ul style={{ margin: '6px 0 0', paddingLeft: 18, color: 'var(--muted)', fontSize: 12.5, lineHeight: 1.8 }}>
                  {o.beats.map((b: string, j: number) => <li key={j}>{b}</li>)}
                </ul>
              )}
              {o.risk && <div style={{ color: 'var(--sem-warn)', fontSize: 12, marginTop: 4 }}>代价:{o.risk}</div>}
            </div>
          ))}
          <div style={{ color: 'var(--muted)', fontSize: 12 }}>点击候选会填入上方指令框,可继续改写后再提交。</div>
        </div>
      )}
    </Card>
  )
}

function PlanApprovalCard({ runId, d, onDone }: { runId: string; d: any; onDone: () => void }) {
  const [edit, setEdit] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)
  const push = useToast((s) => s.push)
  const chapter = d.chapter
  const plan = d.context?.plan?.plan || {}

  async function saveEdited() {
    setSaving(true)
    try {
      const parsed = JSON.parse(edit!)
      const out = await api.action('chapter_plan_save', { chapter, plan: parsed, allow_blocked: false })
      if (out?.errNo === 0) {
        push('ok', '修改版计划已保存(已重新校验)')
        onDone()
      } else push('err', out?.errMsg || '保存失败(校验未过,可继续修改)')
    } catch (e: any) {
      push('err', `JSON 解析失败:${e.message}`)
    } finally {
      setSaving(false)
    }
  }

  async function approve() {
    setSaving(true)
    try {
      const out = await api.action('novel_run_decision_submit', {
        run_id: runId, decision_id: d.decision_id, resolution: { action: 'resume' },
      })
      if (out?.errNo === 0) { push('ok', '计划已批准,开始写作'); onDone() }
      else push('err', out?.errMsg)
    } finally {
      setSaving(false)
    }
  }

  return (
    <Card title={`✅ 第 ${chapter} 章计划待审核`} extra={<Pill tone="canon">plan_approval</Pill>}>
      <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginBottom: 10, fontSize: 13 }}>
        <span><b style={{ color: 'var(--muted)' }}>目标:</b>{plan.primary_goal || '—'}</span>
        {plan.arc_key && <span className="tag">{plan.arc_key}</span>}
        {plan.pov && <span className="tag">POV {plan.pov}</span>}
        {plan.validation_status && <Pill tone={plan.validation_status === 'ready' ? 'pass' : 'warn'}>{plan.validation_status}</Pill>}
      </div>
      {edit === null ? (
        <>
          <pre style={{ background: 'var(--panel-2)', border: '1px solid var(--line)', borderRadius: 8, padding: 12, fontSize: 12, maxHeight: 260, overflow: 'auto', lineHeight: 1.7 }}>
{JSON.stringify(plan, null, 2)}
          </pre>
          <div style={{ display: 'flex', gap: 10, marginTop: 10, justifyContent: 'flex-end' }}>
            <button className="btn" onClick={() => setEdit(JSON.stringify(plan, null, 2))}>✎ 修改计划</button>
            <button className="btn gold" disabled={saving} onClick={approve}>{saving && <span className="spin" />}批准,开始写作</button>
          </div>
        </>
      ) : (
        <>
          <textarea className="paper-edit" style={{ fontFamily: 'var(--font-mono)', fontSize: 12.5, lineHeight: 1.7, minHeight: 300 }}
            value={edit} onChange={(e) => setEdit(e.target.value)} />
          <div style={{ display: 'flex', gap: 10, marginTop: 10, justifyContent: 'flex-end' }}>
            <button className="btn ghost" onClick={() => setEdit(null)}>放弃修改</button>
            <button className="btn primary" disabled={saving} onClick={saveEdited}>{saving && <span className="spin" />}保存修改版(重新校验)</button>
          </div>
          <div style={{ color: 'var(--muted)', fontSize: 12, marginTop: 6 }}>
            保存成功后本决策自动关闭;修改版会重新过 chapter_plan_check,blocked 会被拒绝。
          </div>
        </>
      )}
    </Card>
  )
}

/** 启动长跑卡:导演模式从这里开 */
export function StartRunCard() {
  const [target, setTarget] = useState(40)
  const [steering, setSteering] = useState(true)
  const [review, setReview] = useState(true)
  const [starting, setStarting] = useState(false)
  const push = useToast((s) => s.push)
  const qc = useQueryClient()
  const role = useSession((s) => s.role)
  const canStart = role === 'controller' || role === 'admin'
  if (!canStart) return null

  async function start() {
    setStarting(true)
    try {
      const out = await api.action('novel_run_start', {
        target_chapter: target, require_semantic: true,
        steering_mode: steering, plan_review: review,
      })
      if (out?.errNo === 0) { push('ok', '运行已启动'); qc.invalidateQueries({ queryKey: ['runs'] }) }
      else push('err', out?.errMsg)
    } finally {
      setStarting(false)
    }
  }

  return (
    <Card title="启动长跑" extra={<span style={{ color: 'var(--muted)', fontSize: 12 }}>从最新正典章之后继续</span>}>
      <div style={{ display: 'flex', gap: 14, alignItems: 'center', flexWrap: 'wrap' }}>
        <label style={{ fontSize: 13, color: 'var(--muted)' }}>目标章 <input className="num" type="number" min={1} value={target} onChange={(e) => setTarget(+e.target.value)} /></label>
        <label style={{ display: 'inline-flex', gap: 6, alignItems: 'center', fontSize: 13, cursor: 'pointer' }}>
          <input type="checkbox" checked={steering} onChange={(e) => setSteering(e.target.checked)} /> 🎬 导演模式(每章前等我的指令)
        </label>
        <label style={{ display: 'inline-flex', gap: 6, alignItems: 'center', fontSize: 13, cursor: 'pointer' }}>
          <input type="checkbox" checked={review} onChange={(e) => setReview(e.target.checked)} /> ✅ 计划审核(写前看/改计划)
        </label>
        <div style={{ flex: 1 }} />
        <button className="btn primary" disabled={starting} onClick={start}>{starting && <span className="spin" />}启动</button>
      </div>
    </Card>
  )
}

/** 决策队列的导演分派:steering/plan_approval 走专用卡,其余走原有渲染 */
export function DirectorDecisions({ runId, decisions, onDone }: { runId: string; decisions: any[]; onDone: () => void }) {
  const cards = decisions.map((d, i) => {
    if (d.decision_type === 'steering_point') return <SteeringCard key={d.decision_id} runId={runId} d={d} onDone={onDone} />
    if (d.decision_type === 'plan_approval') return <PlanApprovalCard key={d.decision_id} runId={runId} d={d} onDone={onDone} />
    return null
  }).filter(Boolean)
  return <>{cards}</>
}
