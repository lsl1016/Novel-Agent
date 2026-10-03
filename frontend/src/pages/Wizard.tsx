import { useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useApi, useQuery } from '../api/scope'
import { Card, DataTable, Modal, PageHeader, PageState, StatusBadge, useToast } from '../components/ui'

const groupNames: Record<string, string> = {
  blueprint: '故事蓝图',
  world_facts: '世界真相',
  entities: '人物与事物',
  identity_profiles: '身份档案',
  entity_aliases: '别名',
  entity_attributes: '实体属性',
  entity_relations: '实体关系',
  narrative_entity_links: '叙事关联',
  threads: '叙事线',
  mysteries: '谜团',
  emotion_debts: '情感债',
  arcs: '篇章',
  milestones: '里程碑',
  thread_schedule: '叙事排期',
}
const keys: Record<string, string[]> = {
  world_facts: ['fact_key'],
  entities: ['entity_key'],
  identity_profiles: ['profile_key'],
  entity_aliases: ['entity_key', 'alias'],
  entity_attributes: ['entity_key', 'attr_key', 'chapter'],
  entity_relations: ['source_entity_key', 'relation_type', 'target_entity_key', 'start_chapter'],
  narrative_entity_links: ['narrative_type', 'narrative_key', 'entity_key', 'role', 'chapter'],
  threads: ['thread_key'],
  mysteries: ['mystery_key'],
  emotion_debts: ['debt_key'],
  arcs: ['arc_key'],
  milestones: ['milestone_key'],
  thread_schedule: ['schedule_key'],
}
function changes(before: any, after: any) {
  return Object.entries(after || {})
    .filter(([k]) => groupNames[k])
    .flatMap(([group, rows]: any) => {
      if (group === 'blueprint')
        return Object.entries(rows)
          .filter(([k, v]) => JSON.stringify(before?.blueprint?.[k]) !== JSON.stringify(v))
          .map(([k, v]) => ({
            group: '故事蓝图',
            name:
              (
                {
                  title: '书名',
                  genre: '题材',
                  tone: '语气',
                  core_promise: '核心承诺',
                  hard_constraints: '创作约束',
                  author_decisions: '作者决定',
                } as any
              )[k] || k,
            before: before?.blueprint?.[k],
            after: v,
          }))
      return (Array.isArray(rows) ? rows : []).flatMap((row: any) => {
        const old = (before?.[group] || []).find((x: any) =>
          (keys[group] || []).every((k) => String(x[k] ?? '') === String(row[k] ?? '')),
        )
        const prior = old ? Object.fromEntries(Object.keys(row).map((k) => [k, old[k]])) : null
        if (JSON.stringify(prior) === JSON.stringify(row)) return []
        return [
          {
            group: groupNames[group],
            name: row.name || row.title || row[(keys[group] || [])[0]] || group,
            before: prior,
            after: row,
          },
        ]
      })
    })
}
const initial = {
  step: 1,
  idea: '',
  target: 120,
  genre: '',
  tone: '',
  constraints: '',
  bookName: '',
  destination: 'new',
  questions: [] as any[],
  answers: {} as Record<string, string>,
  confirmed: false,
  result: null as any,
  decisions: {} as Record<string, string>,
  objections: {} as Record<string, string>,
  pending: null as any,
  createdBook: '',
}
export default function Wizard() {
  const api = useApi(),
    navigate = useNavigate(),
    push = useToast((s) => s.push),
    storageKey = 'novel:wizard:' + JSON.stringify(api.book)
  const [state, setState] = useState(() => {
    try {
      return {
        ...initial,
        ...JSON.parse(sessionStorage.getItem(storageKey) || 'null'),
      }
    } catch {
      return initial
    }
  })
  const [busy, setBusy] = useState(''),
    [error, setError] = useState(''),
    [ask, setAsk] = useState(false),
    [applied, setApplied] = useState(false),
    [applyBusy, setApplyBusy] = useState(false)
  const processing = useRef(false)
  const change = (values: Partial<typeof initial>) => setState((s: typeof initial) => ({ ...s, ...values }))
  useEffect(() => {
    try {
      sessionStorage.setItem(storageKey, JSON.stringify(state))
    } catch {}
  }, [state, storageKey])
  const baseline = useQuery({
    queryKey: ['architecture'],
    queryFn: () => api.get('/api/v1/architecture'),
    enabled: state.destination === 'current',
  })
  const assumptions = state.result?.assumptions || [],
    allAccepted = assumptions.every((_: any, i: number) => state.decisions[i] === 'accept')
  const generated = state.result?.architecture
  // Preview exactly the payload that will be applied, including the author's
  // own answers and constraints. Author input takes precedence over AI guesses.
  const decisions = new Map<string, string>()
  for (const d of generated?.blueprint?.author_decisions || []) decisions.set(d.question, d.answer)
  for (const q of state.questions) {
    if (state.answers[q.question]?.trim()) decisions.set(q.question, state.answers[q.question])
  }
  assumptions.forEach((a: string, i: number) => {
    if (state.decisions[i] === 'accept') decisions.set('开书假设：' + a, '作者已确认')
  })
  const arch = generated
    ? {
        ...generated,
        blueprint: {
          ...generated.blueprint,
          hard_constraints: [
            ...new Set([
              ...(generated.blueprint?.hard_constraints || []),
              ...state.constraints
                .split('\n')
                .map((s: string) => s.trim())
                .filter(Boolean),
            ]),
          ],
          author_decisions: [...decisions].map(([question, answer]) => ({ question, answer })),
        },
      }
    : undefined
  const delta = arch ? changes(state.destination === 'new' ? {} : baseline.data, arch) : []
  const hasErrors = !!state.result?.validation?.errors?.length
  useEffect(() => {
    if (!state.pending || processing.current) return
    processing.current = true
    setBusy(state.pending.kind === 'interview' ? 'AI 正在整理访谈问题…' : '正在生成故事蓝图…')
    const pending = state.pending
    api
      .pollJob(pending.id)
      .then((out) => {
        if (pending.kind === 'interview') change({ questions: out.questions || [], pending: null, step: 2 })
        else if (out.architecture)
          change({
            result: out,
            pending: null,
            step: 3,
            decisions: {},
            objections: {},
          })
        else throw new Error(out.error?.message || '没有返回有效蓝图')
      })
      .catch((e) => {
        if (e.name !== 'AbortError') {
          setError(e.message)
          change({ pending: null })
        }
      })
      .finally(() => {
        processing.current = false
        setBusy('')
      })
  }, [state.pending])
  async function interview() {
    setError('')
    setBusy('准备访谈…')
    change({ step: 2, confirmed: false })
    try {
      const j = await api.postJob('story_architect_interview', {
        idea: state.idea,
        options: {
          genre: state.genre,
          tone: state.tone,
          target_total_chapters: state.target,
        },
      })
      change({ pending: { id: j.job.id, kind: 'interview' } })
    } catch (e) {
      setBusy('')
      setError((e as Error).message)
    }
  }
  async function generate() {
    setError('')
    setBusy('提交生成任务…')
    setApplied(false)
    const rejected = assumptions
      .map((a: string, i: number) =>
        state.decisions[i] === 'reject'
          ? `不要采用：${a}。替代要求：${state.objections[i] || '重新设计这一点'}`
          : null,
      )
      .filter(Boolean)
    const decisions = state.questions
      .map((q: any) => ({
        question: q.question,
        answer: state.answers[q.question] || '',
      }))
      .filter((a: any) => a.answer)
    try {
      const j = await api.postJob('novel_architecture_generate', {
        idea: state.idea,
        options: {
          target_total_chapters: state.target,
          genre: state.genre,
          tone: state.tone,
          mode: 'interview',
          author_decisions: decisions,
          hard_constraints: state.constraints.split('\n').filter(Boolean),
          counter_expectation: rejected.join('\n'),
        },
      })
      change({ pending: { id: j.job.id, kind: 'generate' } })
    } catch (e) {
      setBusy('')
      setError((e as Error).message)
    }
  }
  async function apply() {
    setApplyBusy(true)
    setError('')
    try {
      let target = api.book
      if (state.destination === 'new') {
        target = state.createdBook || state.bookName.trim()
        if (!target) throw new Error('请输入新书库名称')
        if (!state.createdBook) {
          await api.post('/api/v1/books', { name: target })
          change({ createdBook: target })
        }
      }
      const dry = await api.postJob('story_architect_apply', { architecture: arch, dry_run: true }, target)
      await api.pollJob(dry.job.id)
      const j = await api.postJob('story_architect_apply', { architecture: arch }, target)
      await api.pollJob(j.job.id)
      setApplied(true)
      setAsk(false)
      push('ok', '故事蓝图已应用，可以开始第一章')
      sessionStorage.removeItem(storageKey)
      navigate('/planner?book=' + encodeURIComponent(target || ''))
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setApplyBusy(false)
    }
  }
  return (
    <div className="page-stack wizard-page">
      <PageHeader
        eyebrow="A NEW BEGINNING"
        title="开书向导"
        description="把一个念头，变成值得写下去的故事。"
      />
      <ol className="wizard-steps">
        {['创意与规模', '访谈与约束', '蓝图与确认'].map((text, i) => (
          <li key={text} className={state.step === i + 1 ? 'active' : state.step > i + 1 ? 'done' : ''}>
            <button
              disabled={!!busy || applyBusy || i + 1 > state.step}
              onClick={() => change({ step: i + 1 })}
            >
              <span>{state.step > i + 1 ? '✓' : i + 1}</span>
              {text}
            </button>
          </li>
        ))}
      </ol>
      {busy && (
        <div className="notice" role="status">
          <span className="spin" />
          {busy} 可以刷新页面，任务会继续在后台进行。
        </div>
      )}
      {error && (
        <div className="notice warn" role="alert">
          {error}
        </div>
      )}
      {state.step === 1 && (
        <Card title="你想讲一个什么故事？">
          <textarea
            className="paper-edit idea-input"
            aria-label="故事创意"
            placeholder="例如：记忆质检员在被删去的记忆中发现一个求救信号，而删除指令竟是她自己签发的。"
            value={state.idea}
            onChange={(e) => change({ idea: e.target.value, result: null })}
          />
          <div className="form-grid">
            <label>
              目标章数
              <input
                className="input"
                type="number"
                min={20}
                max={1000}
                value={state.target}
                onChange={(e) => change({ target: +e.target.value })}
              />
            </label>
            <label>
              题材
              <input
                className="input"
                placeholder="都市悬疑、东方玄幻…"
                value={state.genre}
                onChange={(e) => change({ genre: e.target.value })}
              />
            </label>
            <label>
              故事语气
              <input
                className="input"
                placeholder="冷峻、轻快、温暖…"
                value={state.tone}
                onChange={(e) => change({ tone: e.target.value })}
              />
            </label>
          </div>
          <div className="wizard-actions">
            <button
              className="btn primary"
              disabled={!!busy || state.idea.trim().length < 5 || state.target < 20 || state.target > 1000}
              onClick={interview}
            >
              下一步 · AI 访谈 →
            </button>
          </div>
        </Card>
      )}
      {state.step === 2 && (
        <Card
          title="先确定故事的方向"
          extra={
            <button className="text-btn" disabled={!!busy} onClick={interview}>
              重新访谈
            </button>
          }
        >
          <p className="muted small">
            选择建议或自由作答。暂时没有答案的问题可以留空，后续在蓝图里确认 AI 的假设。
          </p>
          {state.questions.map((q: any, i: number) => (
            <div className="interview-question" key={q.question}>
              <h3>
                {i + 1}. {q.question}
              </h3>
              <div className="toolbar">
                {q.options?.map((o: string) => (
                  <button
                    key={o}
                    className={'btn ' + (state.answers[q.question] === o ? 'primary' : '')}
                    onClick={() =>
                      change({
                        answers: { ...state.answers, [q.question]: o },
                        confirmed: false,
                      })
                    }
                  >
                    {o}
                  </button>
                ))}
              </div>
              <textarea
                className="input"
                rows={2}
                aria-label={q.question}
                placeholder="也可以输入自己的想法…"
                value={state.answers[q.question] || ''}
                onChange={(e) =>
                  change({
                    answers: { ...state.answers, [q.question]: e.target.value },
                    confirmed: false,
                  })
                }
              />
            </div>
          ))}
          {!state.questions.length && !busy && (
            <p className="muted">访谈尚未生成。你可以重试，或直接填写创作约束继续。</p>
          )}
          <label className="field-label">
            创作约束与禁忌
            <textarea
              className="input"
              rows={4}
              aria-label="创作约束与禁忌"
              placeholder="例如：不使用失忆反转；感情线保持克制；结局必须回应主角的选择。"
              value={state.constraints}
              onChange={(e) => change({ constraints: e.target.value, confirmed: false })}
            />
          </label>
          <label className="check-label">
            <input
              type="checkbox"
              checked={state.confirmed}
              onChange={(e) => change({ confirmed: e.target.checked })}
            />
            我已确认这些回答与约束，可据此生成蓝图
          </label>
          <div className="wizard-actions">
            <button className="btn" disabled={!!busy} onClick={() => change({ step: 1 })}>
              上一步
            </button>
            <button className="btn primary" disabled={!state.confirmed || !!busy} onClick={generate}>
              生成故事蓝图 →
            </button>
          </div>
        </Card>
      )}
      {state.step === 3 && arch && (
        <>
          <Card
            title="故事蓝图"
            extra={
              <StatusBadge tone={hasErrors ? 'block' : 'pass'}>
                {hasErrors ? '需修复校验错误' : '结构校验通过'}
              </StatusBadge>
            }
          >
            <h2 className="bible-title">{arch.blueprint?.title || '未命名之书'}</h2>
            <p>{arch.blueprint?.core_promise}</p>
            <div className="chip-list">
              <StatusBadge tone="draft">{arch.blueprint?.genre || state.genre || '未指定题材'}</StatusBadge>
              <StatusBadge tone="muted">{arch.blueprint?.tone || state.tone || '自由语气'}</StatusBadge>
            </div>
            <p className="muted small">
              {(arch.entities || []).length} 个实体 · {(arch.threads || []).length} 条叙事线 ·{' '}
              {(arch.arcs || []).length} 个篇章
            </p>
            <DataTable
              rows={arch.arcs || []}
              rowKey={(a: any) => a.arc_key}
              columns={[
                { key: 'name', label: '篇章', render: (a: any) => a.name },
                {
                  key: 'range',
                  label: '章节范围',
                  render: (a: any) => `${a.start_chapter}—${a.target_end_chapter}`,
                },
                {
                  key: 'goal',
                  label: '目标',
                  render: (a: any) => a.primary_goal,
                },
              ]}
            />
          </Card>
          <Card title="逐条确认创作假设">
            {assumptions.length ? (
              assumptions.map((a: string, i: number) => (
                <div className="assumption" key={i}>
                  <p>{a}</p>
                  <div className="toolbar">
                    <button
                      className={'btn sm ' + (state.decisions[i] === 'accept' ? 'primary' : '')}
                      onClick={() =>
                        change({
                          decisions: { ...state.decisions, [i]: 'accept' },
                        })
                      }
                    >
                      ✓ 接受
                    </button>
                    <button
                      className={'btn sm ' + (state.decisions[i] === 'reject' ? 'danger' : '')}
                      onClick={() =>
                        change({
                          decisions: { ...state.decisions, [i]: 'reject' },
                        })
                      }
                    >
                      否决并调整
                    </button>
                  </div>
                  {state.decisions[i] === 'reject' && (
                    <textarea
                      className="input"
                      rows={2}
                      placeholder="你希望如何调整？"
                      aria-label={'假设 ' + (i + 1) + ' 的替代要求'}
                      value={state.objections[i] || ''}
                      onChange={(e) =>
                        change({
                          objections: {
                            ...state.objections,
                            [i]: e.target.value,
                          },
                        })
                      }
                    />
                  )}
                </div>
              ))
            ) : (
              <p className="muted small">没有额外假设需要确认。</p>
            )}
            <button className="btn" disabled={!!busy} onClick={generate}>
              按访谈与否决意见重新生成
            </button>
          </Card>
          {hasErrors && (
            <Card title="需要修复的结构问题">
              {state.result.validation.errors.map((e: any, i: number) => (
                <p className="error-text" key={i}>
                  {e.message || e.code}
                </p>
              ))}
            </Card>
          )}
          <Card title="应用到哪里？">
            <div className="form-grid">
              <label>
                目标书库
                <select
                  className="input"
                  value={state.destination}
                  disabled={!!state.createdBook}
                  onChange={(e) => change({ destination: e.target.value })}
                >
                  <option value="new">创建新书库</option>
                  <option value="current">应用到当前书库</option>
                </select>
              </label>
              {state.destination === 'new' && (
                <label>
                  新书库名称
                  <input
                    className="input"
                    aria-label="新书库名称"
                    placeholder="如 memory-city"
                    value={state.bookName}
                    disabled={!!state.createdBook}
                    onChange={(e) => change({ bookName: e.target.value })}
                  />
                </label>
              )}
            </div>
            <p className="muted small">生成阶段不会创建空书库。应用失败时，可对已创建的同一书库重试。</p>
          </Card>
          <Card title={`应用前变更预览 · ${delta.length} 项`}>
            <p className="muted small">绿色为新增或更新后的内容。未出现在本次蓝图中的旧记录将保留。</p>
            {state.destination === 'current' && (
              <PageState
                loading={baseline.isPending}
                error={baseline.error}
                onRetry={() => void baseline.refetch()}
              />
            )}
            <div className="architecture-changes">
              {delta.map((d: any, i: number) => (
                <details key={i}>
                  <summary>
                    <StatusBadge tone={d.before == null ? 'pass' : 'warn'}>
                      {d.before == null ? '新增' : '更新'}
                    </StatusBadge>{' '}
                    {d.group} · {d.name}
                  </summary>
                  <div className="architecture-diff">
                    <div>
                      <small>应用前</small>
                      <pre>
                        {d.before == null
                          ? '无'
                          : typeof d.before === 'string'
                            ? d.before
                            : JSON.stringify(d.before, null, 2)}
                      </pre>
                    </div>
                    <div>
                      <small>应用后</small>
                      <pre>{typeof d.after === 'string' ? d.after : JSON.stringify(d.after, null, 2)}</pre>
                    </div>
                  </div>
                </details>
              ))}
            </div>
            <div className="wizard-actions">
              <button className="btn" disabled={!!busy} onClick={() => change({ step: 2 })}>
                返回访谈
              </button>
              <button
                className="btn gold"
                disabled={
                  !!busy ||
                  applyBusy ||
                  applied ||
                  hasErrors ||
                  !allAccepted ||
                  (state.destination === 'new' && !/^[\w\u4e00-\u9fff-]+$/.test(state.bookName)) ||
                  (state.destination === 'current' && !baseline.data)
                }
                onClick={() => setAsk(true)}
              >
                确认并应用蓝图
              </button>
            </div>
            {!allAccepted && <p className="small muted">请接受所有假设，或按否决意见重新生成后再应用。</p>}
          </Card>
        </>
      )}
      {ask && (
        <Modal
          title="应用这份故事蓝图？"
          sub={
            state.destination === 'new'
              ? `将创建书库「${state.bookName}」，并写入已确认的故事设定。`
              : '将更新当前书库中对应的蓝图与设定。请确认上方变更预览。'
          }
          onClose={applyBusy ? undefined : () => setAsk(false)}
          actions={
            <button className="btn gold" disabled={applyBusy} onClick={apply}>
              {applyBusy ? '正在校验并应用…' : '应用蓝图'}
            </button>
          }
        />
      )}
    </div>
  )
}
