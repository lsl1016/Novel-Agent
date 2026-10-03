import { useApi, useQuery, useChapterCursor, useFilters, BookLink } from '../api/scope'
import { Card, DataTable, DetailFields, Drawer, PageHeader, PageState, StatusBadge } from '../components/ui'
import { AxisControls, ChapterAxis } from '../components/ChapterAxis'
import { label } from '../components/labels'

export default function Planner() {
  const api = useApi(),
    { chapter } = useChapterCursor(),
    { params, patch } = useFilters()
  const query = useQuery({
    queryKey: ['plan', chapter],
    queryFn: () => api.get('/api/v1/plan' + (chapter ? '?chapter=' + chapter : '')),
  })
  const chosen = Number(params.get('chapter')),
    arc = params.get('arc'),
    filter = params.get('status') || '',
    q = params.get('q') || ''
  const detail = useQuery({
    queryKey: ['chapter', chosen],
    queryFn: () => api.get('/api/v1/chapter/' + chosen),
    enabled: chosen > 0,
  })
  const data = query.data
  if (!data)
    return <PageState loading={query.isPending} error={query.error} onRetry={() => void query.refetch()} />
  const last = Math.max(data.chapter, ...data.arcs.map((a: any) => a.target_end_chapter), 1)
  const lo = Math.max(1, Number(params.get('from')) || 1),
    hi = Math.max(lo + 1, Number(params.get('to')) || last)
  const x = (n: number) => Math.max(0, Math.min(100, ((n - lo) / (hi - lo)) * 100))
  const arcs = data.arcs.filter((a: any) => !q || a.name.includes(q))
  const picked = data.arcs.find((a: any) => a.arc_key === arc)
  const plans = data.chapter_plans.filter(
    (p: any) =>
      !filter ||
      (filter === 'writing' ? p.active_draft : p.status === filter || p.validation_status === filter),
  )
  return (
    <div className="page-stack">
      <PageHeader title="章节规划" description={`截至第 ${data.chapter} 章 · 从篇章方向到下一章的具体安排`} />
      <Card>
        <div className="toolbar">
          <input
            className="input"
            aria-label="搜索篇章"
            placeholder="搜索篇章…"
            value={q}
            onChange={(e) => patch({ q: e.target.value })}
          />
          <select
            aria-label="计划状态"
            className="input"
            value={filter}
            onChange={(e) => patch({ status: e.target.value })}
          >
            <option value="">全部计划</option>
            <option value="draft">待创作</option>
            <option value="writing">创作中草稿</option>
            <option value="blocked">校验阻断</option>
            <option value="ready">已就绪</option>
          </select>
          <AxisControls latest={last} />
        </div>
      </Card>
      <Card title="篇章时间轴">
        <div className="axis-scroll">
          <div className="axis-canvas">
            <ChapterAxis from={lo} to={hi} />
            {arcs
              .filter((a: any) => a.target_end_chapter >= lo && a.start_chapter <= hi)
              .map((a: any, i: number) => (
                <div key={a.arc_key} className="arc-lane">
                  <button
                    className={'arc-band hue-' + (i % 4)}
                    style={{
                      left: x(a.start_chapter) + '%',
                      width: Math.max(2, x(a.target_end_chapter) - x(a.start_chapter)) + '%',
                    }}
                    onClick={() => patch({ arc: a.arc_key }, false)}
                    title={a.name}
                  >
                    <strong>{a.name}</strong>
                    <small>
                      第 {a.start_chapter}—{a.target_end_chapter} 章
                    </small>
                  </button>
                  {data.milestones
                    .filter((m: any) => m.arc_key === a.arc_key && m.min_chapter >= lo && m.min_chapter <= hi)
                    .map((m: any) => (
                      <button
                        key={m.milestone_key}
                        className="milestone-dot"
                        style={{ left: x(m.min_chapter) + '%' }}
                        title={m.name}
                        onClick={() => patch({ arc: a.arc_key, milestone: m.milestone_key }, false)}
                      >
                        ◆
                      </button>
                    ))}
                </div>
              ))}
          </div>
        </div>
      </Card>
      <div className="two-columns">
        <Card title={`章节计划 · ${plans.length}`}>
          <DataTable
            rows={plans}
            rowKey={(p: any) => p.chapter}
            onPick={(p: any) => patch({ chapter: p.chapter }, false)}
            columns={[
              {
                key: 'chapter',
                label: '章节',
                render: (p: any) => '第 ' + p.chapter + ' 章',
              },
              {
                key: 'arc',
                label: '篇章',
                render: (p: any) => data.arcs.find((a: any) => a.arc_key === p.arc_key)?.name || '未分卷',
              },
              {
                key: 'status',
                label: '状态',
                render: (p: any) => <StatusBadge status={p.validation_status} />,
              },
            ]}
            empty="还没有章节计划"
          />
        </Card>
        <Card title="滚动规划">
          {['hard', 'medium', 'soft'].map((tier) => (
            <details key={tier} open={tier === 'hard'}>
              <summary>{label(tier)}</summary>
              {data.rolling_window
                .filter((w: any) => w.tier === tier)
                .map((w: any) => (
                  <button
                    className="list-row"
                    key={w.chapter}
                    onClick={() => patch({ chapter: w.chapter }, false)}
                  >
                    <strong>第 {w.chapter} 章</strong>
                    <span>{w.primary_goal || '待规划'}</span>
                  </button>
                ))}
            </details>
          ))}
        </Card>
      </div>
      {(arc || chosen > 0) && (
        <Drawer
          title={arc ? picked?.name || '篇章详情' : '第 ' + chosen + ' 章计划'}
          onClose={() => patch({ arc: null, chapter: null, milestone: null })}
        >
          {arc ? (
            picked && (
              <>
                <DetailFields
                  data={{
                    主要目标: picked.primary_goal,
                    表层冲突: picked.surface_conflict,
                    退出条件: picked.exit_conditions,
                    继承叙事线: picked.inherited_thread_keys?.map(
                      (k: string) => data.threads.find((t: any) => t.thread_key === k)?.name || k,
                    ),
                  }}
                />
                <h3>里程碑</h3>
                {data.milestones
                  .filter((m: any) => m.arc_key === arc)
                  .map((m: any) => (
                    <div
                      className={
                        'stage-detail ' + (params.get('milestone') === m.milestone_key ? 'selected' : '')
                      }
                      key={m.milestone_key}
                    >
                      <strong>{m.name}</strong>
                      <p>
                        第 {m.min_chapter}—{m.max_chapter} 章
                      </p>
                      <StatusBadge status={m.status} />
                    </div>
                  ))}
                <h3>叙事排期</h3>
                {data.thread_schedule
                  .filter(
                    (s: any) =>
                      s.min_chapter >= picked.start_chapter && s.min_chapter <= picked.target_end_chapter,
                  )
                  .map((s: any) => (
                    <BookLink
                      key={s.schedule_key}
                      to={'/board?thread=' + encodeURIComponent(s.thread_key)}
                      className="list-row"
                    >
                      {data.threads.find((t: any) => t.thread_key === s.thread_key)?.name || s.thread_key} ·{' '}
                      {label(s.stage_type)}
                    </BookLink>
                  ))}
              </>
            )
          ) : (
            <>
              <PageState
                loading={detail.isPending}
                error={detail.error}
                onRetry={() => void detail.refetch()}
              />
              {detail.data && (
                <>
                  <DetailFields
                    data={{
                      目标: detail.data.chapter_plan?.plan?.primary_goal || '尚未生成计划',
                      视角: detail.data.chapter_plan?.pov_holder,
                      安排:
                        detail.data.chapter_plan?.plan?.beats || detail.data.chapter_plan?.plan?.scene_beats,
                    }}
                  />
                  <BookLink className="btn primary" to={'/studio/' + chosen}>
                    进入本章工作室 →
                  </BookLink>
                  <details>
                    <summary>完整计划</summary>
                    <pre>{JSON.stringify(detail.data.chapter_plan?.plan, null, 2)}</pre>
                  </details>
                </>
              )}
            </>
          )}
        </Drawer>
      )}
    </div>
  )
}
