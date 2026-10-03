import { useEffect, useState } from 'react'
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
import { label } from '../components/labels'
import GraphCanvas from '../components/GraphCanvas'

export default function World() {
  const api = useApi(),
    { chapter } = useChapterCursor(),
    { params, patch } = useFilters()
  const view = params.get('view') || 'table',
    picked = params.get('entity'),
    type = params.get('type') || '',
    q = params.get('q') || ''
  const [search, setSearch] = useState(q)
  useEffect(() => setSearch(q), [q])
  useEffect(() => {
    const t = setTimeout(() => {
      if (search !== q) patch({ q: search })
    }, 200)
    return () => clearTimeout(t)
  }, [search, q])
  const query = useQuery({
    queryKey: ['entities', chapter, q, type],
    queryFn: () =>
      api.get(
        '/api/v1/entities?' +
          new URLSearchParams({
            q,
            type,
            ...(chapter ? { chapter: String(chapter) } : {}),
          }),
      ),
  })
  const graph = useQuery({
    queryKey: ['graph', chapter],
    queryFn: () => api.get('/api/v1/graph' + (chapter ? '?chapter=' + chapter : '')),
    enabled: view === 'graph',
  })
  const detail = useQuery({
    queryKey: ['entity', picked, chapter],
    queryFn: () =>
      api.get('/api/v1/entity/' + encodeURIComponent(picked!) + (chapter ? '?chapter=' + chapter : '')),
    enabled: !!picked,
  })
  const candidates = useQuery({
    queryKey: ['candidates'],
    queryFn: () => api.call('candidate_list', { status: 'candidate', limit: 100 }),
    enabled: view === 'candidates',
  })
  const d = detail.data
  return (
    <div className="page-stack">
      <PageHeader
        title="世界观"
        description={`截至第 ${chapter || query.data?.chapter || '最新'} 章 · 人物、地点与故事设定`}
      />
      <Card>
        <div className="toolbar">
          <input
            className="input"
            aria-label="搜索世界观"
            placeholder="搜索人物、地点、器物…"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
          <select
            className="input"
            aria-label="实体类型"
            value={type}
            onChange={(e) => patch({ type: e.target.value })}
          >
            <option value="">全部类型</option>
            {['Character', 'Faction', 'Location', 'Artifact', 'Item', 'Skill', 'Realm', 'Concept'].map(
              (t) => (
                <option key={t} value={t}>
                  {label(t)}
                </option>
              ),
            )}
          </select>
          <SegmentedControl
            value={view}
            onChange={(v) => patch({ view: v })}
            options={[
              { value: 'table', label: '目录' },
              { value: 'graph', label: '关系图谱' },
              { value: 'candidates', label: '待整理' },
            ]}
          />
        </div>
      </Card>
      {view === 'candidates' ? (
        <Card title="抽取候选">
          <PageState
            loading={candidates.isPending}
            error={candidates.error}
            onRetry={() => void candidates.refetch()}
          />
          {candidates.data && (
            <DataTable
              rows={Array.isArray(candidates.data) ? candidates.data : candidates.data.candidates || []}
              rowKey={(r: any) => r.id || r.candidate_id}
              columns={[
                {
                  key: 'name',
                  label: '内容',
                  render: (r: any) => r.name || r.node_key || r.candidate_id,
                },
                {
                  key: 'chapter',
                  label: '来源',
                  render: (r: any) => <BookLink to={'/studio/' + r.chapter}>第 {r.chapter} 章 ↗</BookLink>,
                },
                {
                  key: 'status',
                  label: '状态',
                  render: () => <StatusBadge tone="warn">待整理</StatusBadge>,
                },
              ]}
              empty="没有待整理的候选"
            />
          )}
        </Card>
      ) : view === 'graph' ? (
        <Card title="实体关系">
          <p className="small muted">点击节点查看档案。实线代表已公开关系，虚线标记故事中的秘密关系。</p>
          <PageState loading={graph.isPending} error={graph.error} onRetry={() => void graph.refetch()} />
          {graph.data && (
            <GraphCanvas
              nodes={graph.data.nodes.filter(
                (n: any) => (!type || n.type === type) && (!q || n.name.includes(q) || n.key.includes(q)),
              )}
              edges={graph.data.edges}
              focus={picked}
              onPick={(entity) => patch({ entity }, false)}
            />
          )}
        </Card>
      ) : (
        <Card title={`设定目录 · ${query.data?.entities?.length || 0} 项`}>
          <PageState loading={query.isPending} error={query.error} onRetry={() => void query.refetch()} />
          {query.data && (
            <DataTable
              rows={query.data.entities}
              rowKey={(e: any) => e.entity_key}
              onPick={(e: any) => patch({ entity: e.entity_key }, false)}
              columns={[
                {
                  key: 'name',
                  label: '名称',
                  render: (e: any) => <strong>{e.name}</strong>,
                },
                {
                  key: 'type',
                  label: '类型',
                  render: (e: any) => <StatusBadge tone="draft">{label(e.entity_type)}</StatusBadge>,
                },
                {
                  key: 'chapter',
                  label: '首次登场',
                  render: (e: any) => '第 ' + e.introduced_chapter + ' 章',
                },
                {
                  key: 'description',
                  label: '描述',
                  render: (e: any) => e.description || '—',
                },
              ]}
              empty="没有匹配的设定"
            />
          )}
        </Card>
      )}
      {picked && (
        <Drawer title={d?.name || '实体档案'} onClose={() => patch({ entity: null })}>
          <PageState loading={detail.isPending} error={detail.error} onRetry={() => void detail.refetch()} />
          {d && (
            <>
              <StatusBadge tone="draft">{label(d.entity_type)}</StatusBadge>
              <p>{d.description || '暂无描述'}</p>
              <DetailFields
                data={{
                  首次登场: '第 ' + d.introduced_chapter + ' 章',
                  身份档案: d.identity_profiles?.map((x: any) => x.value),
                  别名: d.aliases?.map((x: any) => x.alias),
                }}
              />
              <h3>属性沿革</h3>
              {d.attributes.map((x: any, i: number) => (
                <div key={i} className="list-row">
                  <span>{x.attr_key}</span>
                  <span>{String(x.value)}</span>
                  <small>第 {x.start_chapter} 章</small>
                </div>
              ))}
              <h3>人物与事物的关系</h3>
              {d.relations.map((r: any, i: number) => {
                const out = r.source_entity_key === picked
                return (
                  <BookLink
                    className="list-row"
                    key={i}
                    to={
                      '/world?entity=' + encodeURIComponent(out ? r.target_entity_key : r.source_entity_key)
                    }
                  >
                    <StatusBadge tone="muted">{r.relation_type}</StatusBadge>
                    <span>
                      {out ? r.target_name || r.target_entity_key : r.source_name || r.source_entity_key}
                    </span>
                    <span>↗</span>
                  </BookLink>
                )
              })}
              <h3>叙事参与</h3>
              {d.narrative_links.map((l: any, i: number) => (
                <BookLink
                  className="list-row"
                  key={i}
                  to={'/board?thread=' + encodeURIComponent(l.narrative_key)}
                >
                  {l.narrative_name || l.narrative_key} →
                </BookLink>
              ))}
              <h3>证据来源</h3>
              {d.assertions?.length ? (
                d.assertions.map((a: any) => (
                  <BookLink key={a.assertion_id} className="list-row" to={'/studio/' + a.chapter}>
                    第 {a.chapter} 章 · {a.source_span || a.predicate} ↗
                  </BookLink>
                ))
              ) : (
                <p className="muted small">暂无证据记录</p>
              )}
              <details>
                <summary>技术标识</summary>
                <code>{d.entity_key}</code>
              </details>
            </>
          )}
        </Drawer>
      )}
    </div>
  )
}
