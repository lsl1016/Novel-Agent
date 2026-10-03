import { useApi, useQuery, useFilters, useChapterCursor, BookLink } from '../api/scope'
import { Card, Drawer, PageHeader, PageState, SegmentedControl, StatusBadge } from '../components/ui'
import { label } from '../components/labels'
const reviewers = [
  'knowledge_leak',
  'continuity',
  'narrative',
  'character',
  'semantic_knowledge_leak',
  'semantic_character',
  'semantic_narrative',
  'semantic_pacing',
]
export default function Reviews() {
  const api = useApi(),
    { chapter } = useChapterCursor(),
    { params, patch } = useFilters(),
    scope = Number(params.get('scope')) || (params.get('severity') || params.get('finding') ? 9999 : 10),
    severity = params.get('severity') || '',
    type = params.get('type') || ''
  const query = useQuery({
    queryKey: ['reviews'],
    queryFn: () => api.get('/api/v1/reviews?from=1&to=9999'),
    refetchInterval: 30000,
  })
  const chapters = (query.data?.chapters || [])
    .filter((c: any) => !chapter || c.chapter <= chapter)
    .slice(-scope)
    .map((c: any) => ({
      ...c,
      reviews: c.reviews.filter(
        (r: any) =>
          r.draft_version ===
          (c.latest_draft_version ?? Math.max(...c.reviews.map((v: any) => v.draft_version), 0)),
      ),
    }))
  const findings = chapters
    .flatMap((c: any) =>
      c.reviews.flatMap((r: any) =>
        (r.findings || []).map((f: any, i: number) => ({
          ...f,
          chapter: c.chapter,
          version: r.draft_version,
          type: r.reviewer_type,
          verdict: r.verdict,
          key: `${c.chapter}:${r.draft_version}:${r.reviewer_type}:${i}`,
          anchor: r.reviewer_type + ':' + i,
        })),
      ),
    )
    .filter((f: any) => (!severity || f.verdict === severity) && (!type || f.type === type))
    .sort(
      (a: any, b: any) =>
        Number(b.verdict === 'BLOCK') - Number(a.verdict === 'BLOCK') || b.chapter - a.chapter,
    )
  const selected = findings.find((f: any) => f.key === params.get('finding'))
  return (
    <div className="page-stack">
      <PageHeader
        title="审校中心"
        description={`${chapter ? '截至第 ' + chapter + ' 章' : '最新章节时间点'} · 当前草稿版本的审校结果`}
      />
      <Card>
        <div className="toolbar">
          <SegmentedControl
            value={String(scope)}
            onChange={(v) => patch({ scope: v })}
            options={[10, 20, 40, 9999].map((n) => ({
              value: String(n),
              label: n === 9999 ? '全部章节' : '近 ' + n + ' 章',
            }))}
          />
          <select
            className="input"
            aria-label="审校严重度"
            value={severity}
            onChange={(e) => patch({ severity: e.target.value, scope: 9999 })}
          >
            <option value="">全部发现</option>
            <option value="BLOCK">阻断</option>
            <option value="WARN">警告</option>
          </select>
          <select
            className="input"
            aria-label="审校类别"
            value={type}
            onChange={(e) => patch({ type: e.target.value })}
          >
            <option value="">全部类别</option>
            {reviewers.map((t) => (
              <option key={t} value={t}>
                {label(t)}
              </option>
            ))}
          </select>
        </div>
      </Card>
      <PageState loading={query.isPending} error={query.error} onRetry={() => void query.refetch()} />
      {query.data && (
        <>
          <Card title="章节审校矩阵">
            <div className="axis-scroll">
              <table className="review-matrix">
                <thead>
                  <tr>
                    <th>章节</th>
                    {reviewers.map((t) => (
                      <th key={t}>{label(t)}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {chapters.map((c: any) => (
                    <tr key={c.chapter}>
                      <th>第 {c.chapter} 章</th>
                      {reviewers.map((t) => {
                        const r = c.reviews.find((v: any) => v.reviewer_type === t)
                        return (
                          <td key={t}>
                            {r ? (
                              <BookLink to={`/studio/${c.chapter}?mode=draft&version=${r.draft_version}`}>
                                <StatusBadge status={r.verdict} />
                              </BookLink>
                            ) : (
                              <span className="muted">未审</span>
                            )}
                          </td>
                        )
                      })}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Card>
          <div className="two-columns">
            <Card title={`发现收件箱 · ${findings.length} 项`}>
              {findings.length ? (
                findings.map((f: any) => (
                  <button
                    className="finding-card"
                    key={f.key}
                    onClick={() => patch({ finding: f.key }, false)}
                  >
                    <div className="toolbar">
                      <StatusBadge status={f.verdict} />
                      <small>
                        第 {f.chapter} 章 · v{f.version} · {label(f.type)}
                      </small>
                    </div>
                    <p>{f.message}</p>
                    <span className="text-btn">查看证据与建议 →</span>
                  </button>
                ))
              ) : (
                <PageState empty title="当前筛选下没有审校发现" />
              )}
            </Card>
            <Card title="修订收敛">
              {Object.entries(query.data.convergence || {}).map(([ch, versions]: any) => (
                <div className="convergence-row" key={ch}>
                  <BookLink to={'/studio/' + ch}>第 {ch} 章</BookLink>
                  <div className="toolbar">
                    {versions.map((v: any) => (
                      <BookLink
                        className="tag"
                        key={v.version}
                        to={`/studio/${ch}?mode=diff&version=${v.version}`}
                      >
                        v{v.version} · {v.findings} 项
                      </BookLink>
                    ))}
                  </div>
                </div>
              ))}
              {!Object.keys(query.data.convergence || {}).length && (
                <p className="muted small">出现多个草稿版本后，这里展示发现数的变化。</p>
              )}
            </Card>
          </div>
        </>
      )}
      {params.get('finding') && (
        <Drawer title="审校发现" onClose={() => patch({ finding: null })}>
          {selected ? (
            <>
              <StatusBadge status={selected.verdict} />
              <p>{selected.message}</p>
              {selected.evidence && <blockquote>{selected.evidence}</blockquote>}
              {selected.suggestion && <p>{selected.suggestion}</p>}
              <BookLink
                className="btn primary"
                to={`/studio/${selected.chapter}?mode=draft&version=${selected.version}&finding=${encodeURIComponent(selected.anchor)}`}
              >
                定位正文并修订 →
              </BookLink>
              <details>
                <summary>技术标识</summary>
                {selected.code}
              </details>
            </>
          ) : (
            <PageState empty title="该发现不在当前筛选结果内">
              <button className="btn" onClick={() => patch({ scope: 9999, severity: null, type: null })}>
                查看全部发现
              </button>
            </PageState>
          )}
        </Drawer>
      )}
    </div>
  )
}
