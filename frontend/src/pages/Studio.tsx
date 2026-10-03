import { useEffect, useRef, useState } from 'react'
import { useBlocker, useParams } from 'react-router-dom'
import { useQueryClient } from '@tanstack/react-query'
import { useApi, useQuery, useFilters, useBookNavigate, BookLink } from '../api/scope'
import {
  ActionButton,
  Card,
  DetailFields,
  Modal,
  PageHeader,
  PageState,
  SegmentedControl,
  StatusBadge,
  useToast,
} from '../components/ui'
import { label } from '../components/labels'
import { ProseDiff } from '../components/ProseDiff'

export default function Studio() {
  const api = useApi(),
    { chapter: route } = useParams()
  const home = useQuery({
    queryKey: ['home'],
    queryFn: () => api.get('/api/v1/home'),
  })
  if (route === 'latest' && !home.data)
    return <PageState loading={home.isPending} error={home.error} onRetry={() => void home.refetch()} />
  const chapter =
    route === 'latest' ? home.data?.progress?.latest_chapter || 1 : Math.max(1, Number(route) || 1)
  return <ChapterStudio key={chapter} chapter={chapter} />
}
function ChapterStudio({ chapter }: { chapter: number }) {
  const api = useApi(),
    qc = useQueryClient(),
    navigate = useBookNavigate(),
    push = useToast((s) => s.push)
  const { params, patch } = useFilters()
  const versionParam = Number(params.get('version')) || undefined
  const query = useQuery({
    queryKey: ['chapter', chapter, versionParam],
    queryFn: () => api.get(`/api/v1/chapter/${chapter}${versionParam ? '?version=' + versionParam : ''}`),
    refetchInterval: 15000,
  })
  const ws = query.data,
    version = versionParam || ws?.latest_draft_version
  const draftQuery = useQuery({
    queryKey: ['draft', chapter, version],
    queryFn: () => api.get(`/api/v1/chapter/${chapter}/draft/${version}`),
    enabled: !!version,
  })
  const draft = draftQuery.data
  const mode = params.get('mode') || (ws?.canon ? 'canon' : 'draft')
  const [editing, setEditing] = useState(false),
    [body, setBody] = useState(''),
    [baseline, setBaseline] = useState('')
  const [saving, setSaving] = useState(false),
    [savedAt, setSavedAt] = useState(''),
    [saveError, setSaveError] = useState('')
  const [job, setJob] = useState(''),
    [compare, setCompare] = useState('canon'),
    [highlight, setHighlight] = useState<number | null>(null)
  const [pane, setPane] = useState<'write' | 'plan' | 'review'>('write')
  const editRef = useRef<HTMLTextAreaElement>(null),
    savingPromise = useRef<Promise<any> | null>(null)
  const current = useRef({
    body: '',
    baseline: '',
    editing: false,
    draft: null as any,
    parent: undefined as number | undefined,
  })
  const recoveryKey = `novel:edit:${JSON.stringify(api.book)}:${chapter}`
  const [recovery, setRecovery] = useState<any>(() => {
    try {
      return JSON.parse(localStorage.getItem(recoveryKey) || 'null')
    } catch {
      return null
    }
  })
  current.current.body = body
  current.current.baseline = baseline
  current.current.editing = editing
  const dirty = editing && body !== baseline
  const blocker = useBlocker(
    ({ currentLocation, nextLocation }) =>
      ((current.current.editing && current.current.body !== current.current.baseline) ||
        !!savingPromise.current) &&
      (currentLocation.pathname !== nextLocation.pathname ||
        new URLSearchParams(currentLocation.search).get('book') !==
          new URLSearchParams(nextLocation.search).get('book')),
  )
  const blockedNavigation = useRef(false)
  blockedNavigation.current = blocker.state === 'blocked'
  const contextQuery = useQuery({
    queryKey: ['context', chapter],
    queryFn: () =>
      api.call('context_compile', {
        chapter,
        role: 'writer',
        max_tokens: 12000,
        persist: false,
      }),
    enabled: !!ws?.chapter_plan,
    staleTime: 60000,
  })
  const compareQuery = useQuery({
    queryKey: ['draft', chapter, compare],
    queryFn: () => api.get(`/api/v1/chapter/${chapter}/draft/${compare}`),
    enabled: mode === 'diff' && compare !== 'canon',
  })
  const source = mode === 'canon' ? ws?.canon : draft
  const text = editing ? body : source?.body || ''
  const paragraphs = text.split(/\n\s*\n/).filter(Boolean)
  const findings = (ws?.review_details || []).flatMap((r: any) =>
    (r.findings || []).map((f: any, i: number) => ({
      ...f,
      type: r.reviewer_type,
      verdict: r.verdict,
      key: r.reviewer_type + ':' + i,
    })),
  )
  const plan = ws?.chapter_plan?.plan || {}
  const gateLabels: Record<string, string> = {
    draft_exists: '已保存草稿',
    plan_valid: '章节计划有效',
    reviews_complete: '当前版本审校齐全',
    review_verdict_ok: '没有阻断问题',
  }

  useEffect(() => {
    const handle = (e: BeforeUnloadEvent) => {
      if (
        (current.current.editing && current.current.body !== current.current.baseline) ||
        savingPromise.current
      ) {
        e.preventDefault()
        e.returnValue = ''
      }
    }
    window.addEventListener('beforeunload', handle)
    return () => window.removeEventListener('beforeunload', handle)
  }, [])
  useEffect(() => {
    if (!dirty) return
    localStorage.setItem(
      recoveryKey,
      JSON.stringify({
        body,
        parent: current.current.parent,
        updated: new Date().toISOString(),
      }),
    )
    if (blockedNavigation.current) return
    const t = setTimeout(() => {
      if (body.trim() && !saveError) void save(true)
    }, 3000)
    return () => clearTimeout(t)
  }, [body, dirty, saveError, blocker.state])
  useEffect(() => {
    const handle = (e: KeyboardEvent) => {
      if (blockedNavigation.current) return
      if (!(e.metaKey || e.ctrlKey)) return
      if (e.key.toLowerCase() === 's') {
        e.preventDefault()
        if (editing) void save()
      }
      if (e.key === 'Enter') {
        e.preventDefault()
        if (!job) void review()
      }
      if (e.altKey && (e.key === 'ArrowLeft' || e.key === 'ArrowRight')) {
        e.preventDefault()
        navigate('/studio/' + Math.max(1, chapter + (e.key === 'ArrowLeft' ? -1 : 1)))
      }
    }
    window.addEventListener('keydown', handle)
    return () => window.removeEventListener('keydown', handle)
  })
  useEffect(() => {
    const key = params.get('finding')
    const f = findings.find((x: any) => x.key === key)
    if (f && mode === 'draft' && draft) locate(f, false)
  }, [params.get('finding'), draft?.version, ws?.reviewed_version])

  function beginEdit(recovered = false) {
    const value = recovered ? recovery.body : draft?.body || ''
    current.current.draft = draft
    current.current.parent = recovered ? recovery.parent : draft?.version
    setBaseline(draft?.body || '')
    setBody(value)
    setEditing(true)
    setSaveError('')
    patch({ mode: 'draft' })
    setPane('write')
  }
  function save(automatic = false): Promise<any> {
    if (savingPromise.current) return savingPromise.current
    if (!current.current.body.trim()) return Promise.resolve(null)
    if (current.current.body === current.current.baseline)
      return Promise.resolve({ version: current.current.parent || version })
    const snapshot = current.current.body,
      meta = current.current.draft || draft || {}
    setSaving(true)
    setSaveError('')
    const work = api
      .call('chapter_draft_save', {
        chapter,
        title: meta.title || ws?.canon?.title || `第${chapter}章`,
        body: snapshot,
        arc: meta.arc || ws?.chapter_plan?.arc_key || '',
        pov: meta.pov || ws?.chapter_plan?.pov_holder || '',
        summary: meta.summary || '',
        declared_updates: meta.declared_updates,
        source: 'web_edit',
        parent_version: current.current.parent,
      })
      .then(async (out) => {
        current.current.parent = out.draft.version
        current.current.draft = out.draft
        current.current.baseline = snapshot
        setBaseline(snapshot)
        setSavedAt(
          new Date().toLocaleTimeString('zh-CN', {
            hour: '2-digit',
            minute: '2-digit',
            second: '2-digit',
          }),
        )
        if (current.current.body === snapshot) {
          localStorage.removeItem(recoveryKey)
          setRecovery(null)
        }
        // A URL replacement here would cancel React Router's pending transition
        // and prevent "save and leave" from reaching the chosen book/chapter.
        if (!blockedNavigation.current) patch({ mode: 'draft', version: out.draft.version })
        await qc.invalidateQueries({ queryKey: ['chapter', chapter] })
        await qc.invalidateQueries({ queryKey: ['draft', chapter] })
        await qc.invalidateQueries({ queryKey: ['reviews'] })
        await qc.invalidateQueries({ queryKey: ['home'] })
        if (!automatic) push('ok', `已保存为草稿 v${out.draft.version}`)
        return out.draft
      })
      .catch((e) => {
        if (e.name !== 'AbortError') {
          setSaveError(e.message)
          push('err', '保存失败：' + e.message)
        }
        return null
      })
      .finally(() => {
        setSaving(false)
        savingPromise.current = null
      })
    savingPromise.current = work
    return work
  }
  async function runJob(tool: string, args: Record<string, unknown>, message: string) {
    setJob(message)
    try {
      const j = await api.postJob(tool, args)
      const out = await api.pollJob(j.job.id)
      await qc.invalidateQueries()
      push('ok', message.replace('中…', '完成'))
      return out
    } catch (e) {
      if ((e as Error).name !== 'AbortError') push('err', (e as Error).message)
    } finally {
      setJob('')
    }
  }
  async function review() {
    let v = current.current.parent || version
    if (dirty || savingPromise.current) {
      const saved = await save()
      if (!saved) return
      v = saved.version
    }
    if (!v) {
      push('warn', '请先保存一版草稿')
      return
    }
    await runJob('chapter_review_full', { chapter, version: v, semantic: true }, '审校中…')
    setPane('review')
  }
  async function restore() {
    if (!draft) return
    setJob('恢复版本中…')
    try {
      const out = await api.call('chapter_draft_save', {
        chapter,
        title: draft.title,
        body: draft.body,
        arc: draft.arc,
        pov: draft.pov,
        summary: draft.summary,
        declared_updates: draft.declared_updates,
        source: 'web_restore',
        parent_version: draft.version,
      })
      patch({ version: out.draft.version, mode: 'draft' })
      await qc.invalidateQueries()
      push('ok', `已恢复为新草稿 v${out.draft.version}，请重新审校`)
    } catch (e) {
      push('err', (e as Error).message)
    } finally {
      setJob('')
    }
  }
  function changeView(values: Record<string, string | number | null>) {
    if (saving || (dirty && !window.confirm('有尚未保存的正文，放弃这些修改？'))) return
    setEditing(false)
    current.current.parent = undefined
    setHighlight(null)
    patch(values)
  }
  function locate(f: any, notify = true) {
    const evidence =
      typeof f.evidence === 'string' ? f.evidence : typeof f.source_span === 'string' ? f.source_span : ''
    const content = editing ? body : draft?.body || ''
    const parts = content.split(/\n\s*\n/).filter(Boolean)
    let idx = evidence ? parts.findIndex((p: string) => p.includes(evidence)) : -1
    if (idx < 0 && Number.isInteger(f.paragraph) && f.paragraph > 0 && f.paragraph <= parts.length)
      idx = f.paragraph - 1
    if (idx < 0) {
      if (notify) push('warn', '此发现没有可匹配的正文引用，请结合建议手动查看')
      return
    }
    setHighlight(idx)
    setPane('write')
    patch({ mode: 'draft', finding: f.key })
    setTimeout(() => {
      if (editing && editRef.current) {
        const pos = content.indexOf(parts[idx])
        editRef.current.focus()
        editRef.current.setSelectionRange(pos, pos + parts[idx].length)
      } else
        document.getElementById('paragraph-' + idx)?.scrollIntoView({ behavior: 'smooth', block: 'center' })
    }, 50)
  }

  if (!ws)
    return <PageState loading={query.isPending} error={query.error} onRetry={() => void query.refetch()} />
  const ctx = contextQuery.data?.context,
    budget = contextQuery.data?.budget
  const entityName = (key: string) =>
    ctx?.entity_context?.items?.find((x: any) => x.entity_key === key)?.entity?.name || key
  const latestSelected = version === ws.latest_draft_version
  return (
    <div className="page-stack studio-page">
      <PageHeader
        title={`第 ${chapter} 章`}
        description={ws.canon?.title || draft?.title || '新的故事，正在这里发生。'}
        actions={
          <>
            <button
              className="btn sm"
              disabled={chapter === 1}
              onClick={() => navigate('/studio/' + (chapter - 1))}
              aria-label="上一章"
            >
              ← 上一章
            </button>
            <button
              className="btn sm"
              onClick={() => navigate('/studio/' + (chapter + 1))}
              aria-label="下一章"
            >
              下一章 →
            </button>
            <BookLink className="text-btn" to="/planner">
              章节目录
            </BookLink>
          </>
        }
      />
      <div className="studio-mobile-tabs">
        <SegmentedControl
          value={pane}
          onChange={setPane}
          options={[
            { value: 'plan', label: '计划与上下文' },
            { value: 'write', label: '正文' },
            { value: 'review', label: '审校与定稿' },
          ]}
        />
      </div>
      <div className={`studio-grid pane-${pane}`}>
        <aside className="studio-plan">
          <Card
            title="本章计划"
            extra={
              <BookLink to={`/planner?chapter=${chapter}`} className="text-btn">
                详情 ↗
              </BookLink>
            }
          >
            {ws.chapter_plan ? (
              <>
                <StatusBadge status={ws.chapter_plan.validation_status} />
                <h3 className="plan-goal">{plan.primary_goal || plan.summary || '推进本章故事'}</h3>
                <DetailFields
                  data={{
                    视角: entityName(ws.chapter_plan.pov_holder || plan.pov),
                    场景: entityName(plan.location || plan.location_key),
                    节奏: plan.pacing,
                    情节要点: plan.beats || plan.scene_beats,
                    本章约束: plan.hard_constraints,
                  }}
                />
                <details>
                  <summary>完整计划</summary>
                  <pre>{JSON.stringify(plan, null, 2)}</pre>
                </details>
              </>
            ) : (
              <>
                <p className="muted">先生成章节计划，确定本章目标与情节。</p>
                <button
                  className="btn primary"
                  disabled={!!job}
                  onClick={() => void runJob('chapter_plan_generate', { chapter }, '规划中…')}
                >
                  生成本章计划
                </button>
              </>
            )}
          </Card>
          <Card title="写作上下文">
            <PageState
              loading={contextQuery.isFetching && !ctx}
              error={contextQuery.error}
              onRetry={() => void contextQuery.refetch()}
            />
            {ctx ? (
              <>
                <p className="small muted">模型将依据以下人物、叙事线与已发生的故事创作。</p>
                {budget && (
                  <>
                    <div className="budget-label">
                      {budget.estimated_tokens?.toLocaleString()} / {budget.max_tokens?.toLocaleString()}{' '}
                      tokens
                    </div>
                    <div className="progress-track">
                      <i
                        style={{
                          width: `${Math.min(100, (budget.estimated_tokens / budget.max_tokens) * 100)}%`,
                        }}
                      />
                    </div>
                  </>
                )}
                <h4>相关人物与事物</h4>
                <div className="chip-list">
                  {(ctx.entity_context?.items || []).map((x: any) => (
                    <BookLink
                      className="tag"
                      key={x.entity_key}
                      to={`/world?entity=${encodeURIComponent(x.entity_key)}`}
                    >
                      {x.entity?.name || x.entity_key}
                    </BookLink>
                  ))}
                </div>
                <h4>活跃叙事线</h4>
                {(ctx.narrative_context?.items || []).map((x: any, i: number) => (
                  <BookLink
                    className="list-row"
                    key={x.thread_key}
                    to={`/board?thread=${encodeURIComponent(x.thread_key)}`}
                  >
                    {x.name && x.name !== x.thread_key ? x.name : `叙事线 ${i + 1}`} ↗
                  </BookLink>
                ))}
                <details>
                  <summary>暂不应写入正文的秘密</summary>
                  <p className="small muted">
                    这是故事的揭示顺序提示，公开工作台仍可在世界观中查看全部真相。
                  </p>
                  {(ctx.forbidden_fact_keys || []).map((x: any, i: number) => (
                    <code className="tag" key={i}>
                      {typeof x === 'string' ? x : x.fact_key}
                    </code>
                  ))}
                </details>
              </>
            ) : (
              !ws.chapter_plan && <p className="muted small">保存计划后生成上下文。</p>
            )}
          </Card>
        </aside>
        <section className="studio-manuscript">
          <div className="editor-toolbar">
            <SegmentedControl
              value={mode}
              onChange={(v) => changeView({ mode: v })}
              options={[
                { value: 'canon', label: '正典' },
                { value: 'draft', label: '草稿' },
                { value: 'diff', label: '版本对比', disabled: !version },
              ]}
            />
            <div className="toolbar">
              {version && (
                <select
                  className="input"
                  aria-label="草稿版本"
                  disabled={saving}
                  value={version}
                  onChange={(e) =>
                    changeView({
                      version: +e.target.value,
                      mode: mode === 'diff' ? 'diff' : 'draft',
                    })
                  }
                >
                  {ws.drafts.map((d: any) => (
                    <option key={d.version} value={d.version}>
                      v{d.version} · {label(d.status)}
                    </option>
                  ))}
                </select>
              )}
              {mode === 'draft' && !editing && (
                <button
                  className="btn sm"
                  disabled={!ws.chapter_plan || !!job || (!!version && !draft)}
                  onClick={() => beginEdit()}
                >
                  编辑草稿
                </button>
              )}
              {editing && (
                <button
                  className="btn primary sm"
                  disabled={saving || !body.trim()}
                  onClick={() => void save()}
                >
                  {saving ? '保存中…' : '保存'}
                </button>
              )}
            </div>
          </div>
          {recovery && !editing && (
            <div className="notice warn">
              发现本地未保存的正文。
              <button className="text-btn" onClick={() => beginEdit(true)}>
                恢复编辑
              </button>
              <button
                className="text-btn"
                onClick={() => {
                  localStorage.removeItem(recoveryKey)
                  setRecovery(null)
                }}
              >
                丢弃本地副本
              </button>
            </div>
          )}
          {job && (
            <div className="notice" role="status">
              <span className="spin" />
              {job}
            </div>
          )}
          {draftQuery.error && mode !== 'canon' && (
            <PageState error={draftQuery.error} onRetry={() => void draftQuery.refetch()} />
          )}
          {mode === 'diff' ? (
            <>
              <div className="diff-controls">
                <label>
                  对比基准{' '}
                  <select
                    className="input"
                    aria-label="对比基准"
                    value={compare}
                    onChange={(e) => setCompare(e.target.value)}
                  >
                    <option value="canon">已定稿正文</option>
                    {ws.drafts.map((d: any) => (
                      <option key={d.version} value={d.version}>
                        草稿 v{d.version}
                      </option>
                    ))}
                  </select>
                </label>
                <button className="btn" disabled={!draft || !!job} onClick={restore}>
                  恢复 v{version} 为新版本
                </button>
              </div>
              <PageState loading={compareQuery.isFetching} error={compareQuery.error} />
              {draft && !compareQuery.isFetching && (
                <ProseDiff
                  before={compare === 'canon' ? ws.canon?.body || '' : compareQuery.data?.body || ''}
                  after={draft.body}
                  beforeLabel={compare === 'canon' ? '已定稿正文' : '草稿 v' + compare}
                  afterLabel={'草稿 v' + version}
                />
              )}
            </>
          ) : (
            <div className="manuscript-paper" data-surface="paper">
              <div className="prose-width">
                {editing ? (
                  <textarea
                    ref={editRef}
                    className="prose-editor"
                    aria-label="章节正文编辑器"
                    placeholder="在这里写下本章正文…"
                    value={body}
                    onChange={(e) => {
                      setBody(e.target.value)
                      setSaveError('')
                    }}
                  />
                ) : text ? (
                  <article className="prose-reader">
                    {paragraphs.map((p: string, i: number) => (
                      <p id={'paragraph-' + i} key={i} className={highlight === i ? 'highlighted' : ''}>
                        {p.replace(/^#{1,3}\s*/, '')}
                      </p>
                    ))}
                  </article>
                ) : (
                  <PageState empty title={mode === 'canon' ? '本章尚未定稿' : '本章还没有草稿'}>
                    {mode === 'canon' ? (
                      <button className="btn" onClick={() => patch({ mode: 'draft' })}>
                        查看草稿
                      </button>
                    ) : (
                      <>
                        <p>按照左侧计划开始写作，也可以交给 AI 起草。</p>
                        <button
                          className="btn primary"
                          disabled={!ws.chapter_plan || !!job}
                          onClick={() => void runJob('chapter_draft_generate', { chapter }, '起草中…')}
                        >
                          AI 起草
                        </button>
                      </>
                    )}
                  </PageState>
                )}
              </div>
            </div>
          )}
          <footer className="editor-status" aria-live="polite">
            <span>{text.length.toLocaleString()} 字</span>
            <span className={saveError ? 'error-text' : ''}>
              {saveError
                ? '保存失败 · 本地副本已保留'
                : saving
                  ? '保存中…'
                  : dirty
                    ? '未保存 · 停止输入 3 秒后自动保存'
                    : savedAt
                      ? `已保存 · 自动保存时间 ${savedAt}`
                      : editing
                        ? '已保存'
                        : mode === 'canon'
                          ? '已定稿正文'
                          : '草稿版本 ' + (version || '待创建')}
            </span>
            <span className="desktop-hint">⌘S 保存 · ⌘Enter 审校 · ⌘⌥←/→ 切章</span>
          </footer>
        </section>
        <aside className="studio-review">
          <Card
            title="审校发现"
            extra={
              <StatusBadge tone={findings.some((f: any) => f.verdict === 'BLOCK') ? 'block' : 'muted'}>
                {findings.length} 项 · v{ws.reviewed_version || '—'}
              </StatusBadge>
            }
          >
            <button
              className="btn full-width"
              disabled={!version || !!job || saving}
              onClick={() => void review()}
            >
              {job || '审校此版本'}
            </button>
            {ws.review_details?.length ? (
              <div className="review-summary">
                {ws.review_details.map((r: any) => (
                  <div key={r.reviewer_type}>
                    <span>{label(r.reviewer_type)}</span>
                    <StatusBadge status={r.verdict} />
                  </div>
                ))}
              </div>
            ) : (
              <p className="small muted">保存草稿后，发起审校以检查连续性、人物与叙事。</p>
            )}
            {findings.map((f: any) => (
              <button className="finding-card" key={f.key} onClick={() => locate(f)}>
                <div className="toolbar">
                  <StatusBadge status={f.verdict} />
                  <small>{label(f.type)}</small>
                </div>
                <p>{f.message}</p>
                {f.evidence && (
                  <blockquote>
                    {typeof f.evidence === 'string' ? f.evidence : JSON.stringify(f.evidence)}
                  </blockquote>
                )}
                {f.suggestion && <p className="suggestion">{f.suggestion}</p>}
                <span className="text-btn">
                  {f.evidence || f.paragraph ? '定位正文 ↗' : '查看后手动修订'}
                </span>
              </button>
            ))}
          </Card>
          <Card title="定稿检查" className="finalize-card">
            {ws.gate?.checks?.map((c: any) => (
              <div className="gate-check" key={c.key}>
                <span className={c.ok ? 'check-ok' : 'error-text'}>{c.ok ? '✓' : '○'}</span>
                <div>
                  {gateLabels[c.key] || c.key}
                  {!c.ok && c.missing?.length > 0 && <small>还需：{c.missing.map(label).join('、')}</small>}
                </div>
              </div>
            ))}
            {!latestSelected && <p className="small muted">你正在查看历史版本。切回最新草稿后定稿。</p>}
            {ws.canon ? (
              <div className="notice">本章已入正典；新草稿保留在版本史中。</div>
            ) : (
              <ActionButton
                tool="chapter_finalize"
                label="定稿入正典"
                variant="gold"
                args={{
                  chapter,
                  version: ws.gate?.draft_version,
                  allow_warnings: true,
                }}
                disabled={!ws.gate?.ready || !latestSelected || dirty || saving || !!job}
                confirm={{
                  title: `定稿第 ${chapter} 章？`,
                  sub: '当前草稿将成为正式正文，服务端会再次核对审校结果。',
                }}
                onDone={() => {
                  void qc.invalidateQueries()
                  patch({ mode: 'canon' })
                }}
              />
            )}
          </Card>
        </aside>
      </div>
      {blocker.state === 'blocked' && (
        <Modal
          title="正文尚未保存"
          sub="保存完成后离开，或保留本地恢复副本并离开。"
          onClose={
            saving
              ? undefined
              : () => {
                  blocker.reset()
                  if (current.current.parent) patch({ version: current.current.parent })
                }
          }
          actions={
            <>
              <button className="btn" disabled={saving} onClick={() => blocker.proceed()}>
                直接离开
              </button>
              <button
                className="btn primary"
                disabled={saving || !body.trim()}
                onClick={async () => {
                  const out = await save()
                  if (out && current.current.body === current.current.baseline) blocker.proceed()
                }}
              >
                保存并离开
              </button>
            </>
          }
        />
      )}
    </div>
  )
}
