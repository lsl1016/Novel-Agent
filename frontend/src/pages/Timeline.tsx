import { useApi, useQuery, useChapterCursor, useFilters, BookLink } from '../api/scope'
import { Card, DetailFields, Drawer, PageHeader, PageState, DataTable, StatusBadge } from '../components/ui'
import { AxisControls, ChapterAxis } from '../components/ChapterAxis'
import { label } from '../components/labels'

const types: Record<string, string> = {
  event: '事件',
  battle: '战斗',
  discovery: '发现',
  betrayal: '背叛',
  death: '死亡',
  meeting: '会面',
}
export default function Timeline() {
  const api = useApi(),
    { chapter } = useChapterCursor(),
    { params, patch } = useFilters()
  const home = useQuery({
    queryKey: ['home'],
    queryFn: () => api.get('/api/v1/home'),
  })
  const latest = chapter || home.data?.progress?.latest_chapter || 1
  const lo = Math.max(1, Number(params.get('from')) || 1),
    hi = Math.max(lo, Number(params.get('to')) || latest),
    entity = params.get('entity') || '',
    type = params.get('type') || '',
    event = params.get('event')
  const query = useQuery({
    queryKey: ['timeline', lo, hi, entity],
    queryFn: () =>
      api.get('/api/v1/timeline?' + new URLSearchParams({ from: String(lo), to: String(hi), entity })),
  })
  const detail = useQuery({
    queryKey: ['event', event],
    queryFn: () =>
      api.call('event_get', /^\d+$/.test(event!) ? { event_id: Number(event) } : { event_key: event }),
    enabled: !!event,
  })
  const data = query.data,
    events = (data?.events || []).filter((e: any) => !type || e.event_type === type),
    selected = detail.data
  const lanes: Record<string, any[]> = {}
  events.forEach((e: any) => (lanes[e.event_type || 'event'] ||= []).push(e))
  const x = (ch: number) => ((ch - lo + 0.5) / Math.max(1, hi - lo + 1)) * 100
  return (
    <div className="page-stack">
      <PageHeader title="时间线" description={`截至第 ${latest} 章 · 追踪事件、关系与人物的变化`} />
      <Card>
        <div className="toolbar">
          <AxisControls latest={latest} />
          <select
            className="input"
            aria-label="事件类型"
            value={type}
            onChange={(e) => patch({ type: e.target.value })}
          >
            <option value="">全部事件</option>
            {Object.entries(types).map(([k, v]) => (
              <option key={k} value={k}>
                {v}
              </option>
            ))}
          </select>
          {entity && (
            <button className="btn sm" onClick={() => patch({ entity: null })}>
              清除实体筛选 ×
            </button>
          )}
        </div>
      </Card>
      <PageState loading={query.isPending} error={query.error} onRetry={() => void query.refetch()} />
      {data && (
        <>
          <Card title="世界事件">
            <div className="axis-scroll">
              <div className="axis-canvas">
                <ChapterAxis from={lo} to={hi} />
                {Object.entries(lanes).map(([t, list]) => (
                  <div className="event-lane" key={t}>
                    <span>{types[t] || t}</span>
                    {list.map((e: any) => (
                      <button
                        className="event-dot"
                        key={e.event_id ?? e.id}
                        title={`第 ${e.chapter} 章 · ${e.name}`}
                        style={{ left: x(e.chapter) + '%' }}
                        onClick={() => patch({ event: e.event_id ?? e.id }, false)}
                      >
                        <span />
                      </button>
                    ))}
                  </div>
                ))}
              </div>
            </div>
            {!events.length && <PageState empty title="这一窗口还没有事件" />}
          </Card>
          <Card title="事件目录">
            <DataTable
              rows={events}
              rowKey={(e: any) => e.event_id ?? e.id}
              onPick={(e: any) => patch({ event: e.event_id ?? e.id }, false)}
              columns={[
                { key: 'name', label: '事件', render: (e: any) => e.name },
                {
                  key: 'type',
                  label: '类型',
                  render: (e: any) => types[e.event_type] || e.event_type,
                },
                {
                  key: 'chapter',
                  label: '章节',
                  render: (e: any) => '第 ' + e.chapter + ' 章',
                },
              ]}
            />
          </Card>
          <div className="two-columns">
            <Card title="属性变迁">
              {data.attribute_changes.map((a: any, i: number) => (
                <BookLink
                  key={i}
                  className="list-row"
                  to={'/world?entity=' + encodeURIComponent(a.entity_key) + '&at=' + a.start_chapter}
                >
                  <small>第 {a.start_chapter} 章</small>
                  <span>
                    {a.attr_key} → {String(a.value)}
                  </span>
                </BookLink>
              ))}
            </Card>
            <Card title="关系变迁">
              {data.relation_changes.map((r: any, i: number) => (
                <BookLink
                  key={i}
                  className="list-row"
                  to={'/world?entity=' + encodeURIComponent(r.source_entity_key) + '&at=' + r.start_chapter}
                >
                  <small>第 {r.start_chapter} 章</small>
                  <span>{r.relation_type}</span>
                </BookLink>
              ))}
            </Card>
          </div>
        </>
      )}
      {event && (
        <Drawer title={selected?.name || '事件详情'} onClose={() => patch({ event: null })}>
          <PageState loading={detail.isPending} error={detail.error} onRetry={() => void detail.refetch()} />
          {selected && (
            <>
              <StatusBadge status={selected.status} />
              <DetailFields
                data={{
                  类型: types[selected.event_type] || selected.event_type,
                  结果: selected.outcome,
                  后果: selected.consequence,
                }}
              />
              <BookLink className="btn" to={'/studio/' + selected.chapter}>
                阅读第 {selected.chapter} 章 ↗
              </BookLink>
              {selected.cause_event_id && (
                <BookLink className="list-row" to={'/timeline?event=' + selected.cause_event_id}>
                  查看上游原因 →
                </BookLink>
              )}
              {selected.thread_key && (
                <BookLink
                  className="list-row"
                  to={'/board?thread=' + encodeURIComponent(selected.thread_key)}
                >
                  关联叙事线 →
                </BookLink>
              )}
              <h3>参与者</h3>
              {selected.participants?.map((p: any, i: number) => (
                <BookLink
                  className="list-row"
                  key={i}
                  to={'/world?entity=' + encodeURIComponent(p.entity_key)}
                >
                  {p.entity_name || p.name || p.entity_key} ↗
                </BookLink>
              ))}
            </>
          )}
        </Drawer>
      )}
    </div>
  )
}
