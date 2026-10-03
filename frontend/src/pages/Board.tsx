import { useApi, useQuery, useChapterCursor, useFilters, BookLink } from '../api/scope'
import {
  Card,
  DataTable,
  DetailFields,
  Drawer,
  PageHeader,
  PageState,
  SegmentedControl,
  StatusBadge,
} from '../components/ui'
import { AxisControls, ChapterAxis } from '../components/ChapterAxis'
import { label } from '../components/labels'

export default function Board() {
  const api = useApi(),
    { chapter } = useChapterCursor(),
    { params, patch } = useFilters()
  const query = useQuery({
    queryKey: ['board', chapter],
    queryFn: () => api.get('/api/v1/board' + (chapter ? '?chapter=' + chapter : '')),
  })
  const data = query.data,
    tab = params.get('tab') || 'threads',
    q = params.get('q') || '',
    filter = params.get('status') || ''
  const selected = params.get('thread'),
    picked = data?.threads?.find((t: any) => t.thread_key === selected)
  if (!data)
    return <PageState loading={query.isPending} error={query.error} onRetry={() => void query.refetch()} />
  const at = data.chapter || 1,
    lo = Math.max(1, Number(params.get('from')) || 1),
    hi = Math.max(lo + 1, Number(params.get('to')) || at)
  const x = (n: number) => Math.min(100, Math.max(0, ((n - lo) / (hi - lo)) * 100))
  const match = (r: any) => !q || String(r.name || r.content || r.truth || '').includes(q)
  const threads = data.threads.filter(
    (t: any) =>
      match(t) &&
      (!filter ||
        filter === 'all' ||
        (filter === 'overdue' ? t.status === 'open' && t.target_max < at : t.status === filter)),
  )
  const mysteries = data.mysteries.filter(
    (m: any) => m.introduced_chapter <= at && match(m) && (filter === 'all' || m.status === 'open'),
  )
  const debts = data.emotion_debts
    .filter((d: any) => match(d) && (filter === 'all' || d.status !== 'resolved'))
    .sort((a: any, b: any) => b.intensity - a.intensity)
  const clues = data.clue_ledger.filter(
    (c: any) =>
      match(c) &&
      (filter === 'all' || !c.paid) &&
      (filter !== 'overdue' ||
        (data.threads.find((t: any) => t.thread_key === c.thread_key)?.target_max || Infinity) < at),
  )
  return (
    <div className="page-stack">
      <PageHeader title="叙事看板" description={`截至第 ${at} 章 · 看见故事的承诺、铺垫与回响`} />
      <Card>
        <div className="toolbar">
          <SegmentedControl
            value={tab}
            onChange={(v) => patch({ tab: v, status: null })}
            options={[
              { value: 'threads', label: '叙事线' },
              { value: 'mysteries', label: '谜团' },
              { value: 'clues', label: '伏笔' },
              { value: 'debts', label: '情感债' },
              { value: 'beliefs', label: '认知矩阵' },
            ]}
          />
          <input
            className="input"
            aria-label="搜索叙事内容"
            placeholder="搜索故事内容…"
            value={q}
            onChange={(e) => patch({ q: e.target.value })}
          />
          <select
            className="input"
            aria-label="叙事状态"
            value={filter}
            onChange={(e) => patch({ status: e.target.value })}
          >
            <option value="">当前关注</option>
            <option value="all">全部</option>
            <option value="overdue">逾期未处理</option>
          </select>
        </div>
      </Card>
      {tab === 'threads' && (
        <Card title="叙事线与回收窗口" extra={<AxisControls latest={at} />}>
          <div className="axis-scroll">
            <div className="axis-canvas">
              <ChapterAxis from={lo} to={hi} />
              {threads.map((t: any, i: number) => (
                <div key={t.thread_key} className="thread-lane">
                  <button className="list-row" onClick={() => patch({ thread: t.thread_key }, false)}>
                    <strong>
                      {t.name && t.name !== t.thread_key ? t.name : t.main_goal || `叙事线 ${i + 1}`}
                    </strong>
                    <span className="muted">{label(t.thread_type)}</span>
                    <StatusBadge status={t.status} />
                    <small>
                      第 {t.target_min}—{t.target_max} 章回收
                    </small>
                  </button>
                  <div className="lane-track">
                    <i
                      className="lane-window"
                      style={{
                        left: x(t.target_min) + '%',
                        width: Math.max(0, x(t.target_max) - x(t.target_min)) + '%',
                      }}
                    />
                    {data.stages
                      .filter((s: any) => s.thread_key === t.thread_key && s.chapter >= lo && s.chapter <= hi)
                      .map((s: any) => (
                        <button
                          className="stage-dot"
                          key={s.id}
                          title={`第 ${s.chapter} 章 · ${label(s.stage_type)} · ${s.content}`}
                          style={{
                            left: x(s.chapter) + '%',
                            background:
                              s.stage_type === 'Payoff'
                                ? 'var(--sem-pass)'
                                : s.stage_type === 'Reveal'
                                  ? 'var(--sem-secret)'
                                  : 'var(--sem-draft)',
                          }}
                          onClick={() => patch({ thread: t.thread_key, stage: s.id }, false)}
                        />
                      ))}
                  </div>
                </div>
              ))}
            </div>
          </div>
          {!threads.length && <PageState empty title="暂无匹配的叙事线" />}
        </Card>
      )}
      {tab === 'mysteries' && (
        <Card title="待解开的谜团">
          <DataTable
            rows={mysteries}
            rowKey={(m: any) => m.mystery_key}
            onPick={(m: any) => patch({ thread: m.thread_key }, false)}
            columns={[
              { key: 'name', label: '谜团', render: (m: any) => m.name },
              {
                key: 'window',
                label: '揭示窗口',
                render: (m: any) => `第 ${m.target_min}—${m.target_max} 章`,
              },
              {
                key: 'age',
                label: '已铺垫',
                render: (m: any) => `${at - m.introduced_chapter} 章`,
              },
            ]}
          />
        </Card>
      )}
      {tab === 'clues' && (
        <Card title="伏笔回收台账">
          <DataTable
            rows={clues}
            rowKey={(c: any) => c.stage_id}
            onPick={(c: any) => patch({ thread: c.thread_key }, false)}
            columns={[
              { key: 'content', label: '伏笔', render: (c: any) => c.content },
              {
                key: 'chapter',
                label: '埋设章节',
                render: (c: any) => '第 ' + c.chapter + ' 章',
              },
              {
                key: 'paid',
                label: '回收',
                render: (c: any) => (
                  <StatusBadge tone={c.paid ? 'pass' : 'warn'}>{c.paid ? '已回收' : '待回收'}</StatusBadge>
                ),
              },
            ]}
          />
        </Card>
      )}
      {tab === 'debts' && (
        <Card title="未偿情感债">
          <DataTable
            rows={debts}
            rowKey={(d: any) => d.debt_key}
            onPick={(d: any) => patch({ thread: d.thread_key }, false)}
            columns={[
              { key: 'name', label: '情感债', render: (d: any) => d.name },
              {
                key: 'strength',
                label: '强度',
                render: (d: any) => Math.round(d.intensity * 100) + '%',
              },
              {
                key: 'chapter',
                label: '建立于',
                render: (d: any) => '第 ' + d.created_chapter + ' 章',
              },
            ]}
          />
        </Card>
      )}
      {tab === 'beliefs' && (
        <Card title="谁知道什么">
          <p className="muted small">逐项对照世界真相与角色认知，剧情秘密在本工作台公开可见。</p>
          <div className="belief-cards">
            {data.belief_matrix.filter(match).map((f: any) => (
              <article className="belief-card" key={f.fact_key}>
                <p>{String(f.truth)}</p>
                <div className="chip-list">
                  {Object.entries(f.holders).map(([h, v]: any) => (
                    <span className={`heat ${v.stance}`} key={h}>
                      {h === 'reader' ? '读者' : h} ·{' '}
                      {(
                        {
                          unknown: '不知',
                          suspects: '怀疑',
                          believes: '相信',
                          confirmed: '已知',
                          known: '已知',
                        } as any
                      )[v.stance] || '未知'}
                    </span>
                  ))}
                </div>
                <small className="muted">计划第 {f.reveal_after ?? '待定'} 章揭示</small>
                <details>
                  <summary>事实标识</summary>
                  {f.fact_key}
                </details>
              </article>
            ))}
          </div>
        </Card>
      )}
      {selected && (
        <Drawer title={picked?.name || '叙事线'} onClose={() => patch({ thread: null, stage: null })}>
          {picked ? (
            <>
              <StatusBadge status={picked.status} />
              <DetailFields
                data={{
                  目标: picked.main_goal,
                  类型: label(picked.thread_type),
                  回收窗口: `第 ${picked.target_min}—${picked.target_max} 章`,
                }}
              />
              <h3>故事节拍</h3>
              {data.stages
                .filter((s: any) => s.thread_key === selected)
                .map((s: any) => (
                  <BookLink
                    to={'/studio/' + s.chapter}
                    key={s.id}
                    className={`stage-detail ${String(s.id) === params.get('stage') ? 'selected' : ''}`}
                  >
                    <StatusBadge tone="draft">{label(s.stage_type)}</StatusBadge>
                    <p>{s.content}</p>
                    <small>第 {s.chapter} 章 · 查看正文 ↗</small>
                  </BookLink>
                ))}
              <details>
                <summary>技术标识</summary>
                {selected}
              </details>
            </>
          ) : (
            <PageState empty title="当前时间点未找到这条叙事线" />
          )}
        </Drawer>
      )}
    </div>
  )
}
