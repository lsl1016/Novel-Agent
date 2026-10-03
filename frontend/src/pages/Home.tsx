import { useQueryClient } from '@tanstack/react-query'
import { useApi, useQuery, BookLink, useBookNavigate } from '../api/scope'
import { ActionButton, Card, DataTable, PageHeader, PageState, Stat, StatusBadge } from '../components/ui'
import { label } from '../components/labels'

export default function Home() {
  const api = useApi(),
    navigate = useBookNavigate(),
    qc = useQueryClient()
  const query = useQuery({
    queryKey: ['home'],
    queryFn: () => api.get('/api/v1/home'),
    refetchInterval: 15000,
  })
  const { data: audit } = useQuery({
    queryKey: ['reviews'],
    queryFn: () => api.get('/api/v1/reviews?from=1&to=9999'),
    refetchInterval: 30000,
  })
  const home = query.data,
    run = home?.run
  const { data: detail } = useQuery({
    queryKey: ['run', run?.run_id],
    queryFn: () => api.get('/api/v1/runs/' + run.run_id),
    enabled: !!run,
    refetchInterval: 15000,
  })
  if (!home)
    return <PageState loading={query.isPending} error={query.error} onRetry={() => void query.refetch()} />
  const latest = home.progress.latest_chapter || 0,
    next = latest + 1,
    p = home.pressure || {}
  const target =
    home.book.target_total_chapters ||
    home.arcs?.at(-1)?.target_end_chapter ||
    run?.config?.target_chapter ||
    next
  const blocked = (audit?.chapters || []).filter((c: any) => {
    const v = c.latest_draft_version ?? Math.max(...c.reviews.map((r: any) => r.draft_version), 0)
    return c.reviews.some((r: any) => r.draft_version === v && r.verdict === 'BLOCK')
  })
  const pending = home.inbox?.open_decisions || 0
  const runChapter = run?.status === 'completed' ? run.config?.target_chapter || latest : run?.current_chapter
  const events = detail?.events || [],
    phase = events.filter((e: any) => e.chapter === runChapter).at(-1)?.phase
  const reviewTrend = (audit?.chapters || []).slice(-7).map((c: any) => {
    const v = c.latest_draft_version ?? Math.max(...c.reviews.map((r: any) => r.draft_version), 0)
    const current = c.reviews.filter((r: any) => r.draft_version === v)
    return {
      chapter: c.chapter,
      version: v,
      reviewed: !!current.length,
      count: current.reduce((n: number, r: any) => n + r.findings.length, 0),
    }
  })
  const peakFindings = Math.max(1, ...reviewTrend.map((c: any) => c.count))
  const phases = ['plan', 'draft', 'review', 'revise', 'commit']
  const arcName = (key: string) => home.arcs?.find((a: any) => a.arc_key === key)?.name || key || '未分卷'
  return (
    <div className="page-stack">
      <PageHeader
        eyebrow="YOUR STORY, IN MOTION"
        title={latest ? '欢迎回到你的故事' : '从一个念头，开始一部小说'}
        description={
          home.book.title
            ? `《${home.book.title}》 · ${home.current_arc?.name || '等待新的篇章'}`
            : '先建立故事蓝图，再写下第一章。'
        }
        actions={
          <BookLink to="/wizard" className="btn">
            ✦ 开启新故事
          </BookLink>
        }
      />
      <section className="hero-grid">
        <div className="next-action">
          <span className="eyebrow">下一步行动</span>
          <h2>
            {pending
              ? '故事在等你做一个决定'
              : blocked.length
                ? '先把这一章打磨好'
                : run?.status === 'paused'
                  ? '准备好继续了吗？'
                  : `继续写第 ${next} 章`}
          </h2>
          <p>
            {pending
              ? `有 ${pending} 个待决问题，需要你的创作判断。`
              : blocked.length
                ? `有 ${blocked.length} 章存在审校阻断，查看证据后即可着手修订。`
                : run?.status === 'running'
                  ? `正在创作第 ${run.current_chapter} 章，你可以查看进展或审阅已完成的章节。`
                  : '从本章计划开始，带着人物和伏笔一起向前。'}
          </p>
          <div className="toolbar">
            {pending ? (
              <BookLink className="btn primary" to="/runs?task=decisions">
                回答待决问题 →
              </BookLink>
            ) : blocked.length ? (
              <BookLink className="btn primary" to="/reviews?severity=BLOCK">
                处理审校阻断 →
              </BookLink>
            ) : run?.status === 'paused' ? (
              <ActionButton
                tool="novel_run_resume"
                args={{ run_id: run.run_id }}
                label="恢复运行"
                variant="primary"
                onDone={async () => {
                  await api.postJob('novel_run_continue', {
                    run_id: run.run_id,
                    max_steps: 50,
                  })
                  await qc.invalidateQueries()
                  navigate('/runs/' + run.run_id)
                }}
              />
            ) : (
              <BookLink
                className="btn primary"
                to={latest || home.arcs?.length ? `/studio/${next}` : '/wizard'}
              >
                {latest || home.arcs?.length ? '进入写作工作室' : '创建故事蓝图'} →
              </BookLink>
            )}
            {latest > 0 && (
              <BookLink className="btn ghost" to={`/studio/${latest}`}>
                阅读最新章节
              </BookLink>
            )}
          </div>
          <div className="action-links">
            <BookLink to="/runs?task=decisions">{pending} 项待决策</BookLink>
            <BookLink to="/reviews?severity=BLOCK">{blocked.length} 章待修订</BookLink>
            <BookLink to="/world?view=candidates">{home.inbox?.pending_candidates || 0} 项待整理</BookLink>
          </div>
        </div>
        <Card
          title="创作进度"
          extra={
            <BookLink to="/planner" className="text-btn">
              查看规划 ↗
            </BookLink>
          }
          className="progress-card"
        >
          <div className="big-progress">
            {home.progress.committed_chapters}
            <span> / {target} 章</span>
          </div>
          <div className="progress-track">
            <i
              style={{
                width: `${Math.min(100, (home.progress.committed_chapters / Math.max(1, target)) * 100)}%`,
              }}
            />
          </div>
          <div className="progress-meta">
            <BookLink to="/studio/latest">
              {(home.progress.total_chars / 10000).toFixed(1)} 万字已定稿
            </BookLink>
            <BookLink to="/planner">
              {Math.round((home.progress.committed_chapters / Math.max(1, target)) * 100)}% 完成
            </BookLink>
          </div>
          <div className="sparkline" aria-label="最近章节字数趋势">
            {home.recent_chapters.map((c: any) => (
              <BookLink
                key={c.chapter}
                to={`/studio/${c.chapter}`}
                title={`第 ${c.chapter} 章 · ${c.chars} 字`}
              >
                <i
                  style={{
                    height: `${Math.max(10, (c.chars / Math.max(...home.recent_chapters.map((v: any) => v.chars), 1)) * 54)}px`,
                  }}
                />
                <small>{c.chapter}</small>
              </BookLink>
            ))}
          </div>
        </Card>
      </section>
      <Card
        title={
          run ? `${run.status === 'completed' ? '最近创作' : '当前创作'} · 第 ${runChapter} 章` : '自动创作'
        }
        extra={
          <BookLink to="/runs" className="text-btn">
            进入运行中心 ↗
          </BookLink>
        }
      >
        <div className="pipeline-row">
          {run ? <StatusBadge status={run.status} /> : <span className="muted">尚未启动</span>}
          <div className="pipeline">
            {phases.map((v, i) => (
              <span key={v} className={v === phase && run?.status === 'running' ? 'current' : ''}>
                <i>{i + 1}</i>
                {label(v)}
              </span>
            ))}
          </div>
        </div>
      </Card>
      <div className="health-grid">
        {[
          ['未解谜团', p.open_mysteries, '/board?tab=mysteries'],
          ['逾期伏笔', p.stale_foreshadowing, '/board?tab=clues&status=overdue'],
          ['未偿情感债', p.open_emotion_debts, '/board?tab=debts'],
          ['创作中草稿', home.inbox?.active_draft_chapters, '/planner?status=writing'],
        ].map(([text, value, to]) => (
          <BookLink key={String(text)} to={String(to)} className="metric-link">
            <Stat label={String(text)} value={value ?? 0} />
            <span>↗</span>
          </BookLink>
        ))}
      </div>
      {reviewTrend.length > 0 && (
        <Card
          title="近期审校趋势"
          extra={
            <BookLink className="text-btn" to="/reviews">
              查看审校 ↗
            </BookLink>
          }
        >
          <p className="small muted">按章节统计当前草稿版本的发现数；未审校不计为零。点击进入该版本处理。</p>
          <div className="sparkline review-trend">
            {reviewTrend.map((c: any) => (
              <BookLink key={c.chapter} to={`/studio/${c.chapter}?mode=draft&version=${c.version}`}>
                <strong>{c.reviewed ? c.count + ' 项' : '未审'}</strong>
                <i style={{ height: Math.max(3, (c.count / peakFindings) * 48) + 'px' }} />
                <small>第 {c.chapter} 章</small>
              </BookLink>
            ))}
          </div>
        </Card>
      )}
      {!!p.risks?.length && (
        <Card title="故事健康提醒">
          {p.risks.map((r: string, i: number) => (
            <BookLink className="list-row" key={i} to="/board">
              <span className="badge warn">待关注</span>
              <span>{r}</span>
              <span>→</span>
            </BookLink>
          ))}
        </Card>
      )}
      <div className="two-columns">
        <Card
          title="最近章节"
          extra={
            <BookLink className="text-btn" to="/planner">
              全部章节 ↗
            </BookLink>
          }
        >
          <DataTable
            rows={[...home.recent_chapters].reverse()}
            rowKey={(c: any) => c.chapter}
            onPick={(c: any) => navigate(`/studio/${c.chapter}`)}
            columns={[
              {
                key: 'title',
                label: '章节',
                render: (c: any) => (
                  <strong>
                    第 {c.chapter} 章 · {c.title}
                  </strong>
                ),
              },
              { key: 'arc', label: '篇章', render: (c: any) => arcName(c.arc) },
              {
                key: 'chars',
                label: '字数',
                render: (c: any) => c.chars.toLocaleString(),
              },
            ]}
            empty="第一章还在酝酿中"
          />
        </Card>
        <Card
          title="篇章结构"
          extra={
            <BookLink className="text-btn" to="/planner">
              查看全貌 ↗
            </BookLink>
          }
        >
          {home.arcs?.length ? (
            home.arcs.map((a: any) => (
              <BookLink
                key={a.arc_key}
                to={`/planner?arc=${encodeURIComponent(a.arc_key)}`}
                className="arc-row"
              >
                <span className="arc-number">{a.order_no}</span>
                <div>
                  <strong>{a.name}</strong>
                  <small>
                    第 {a.start_chapter}—{a.target_end_chapter} 章
                  </small>
                </div>
                {a.arc_key === home.current_arc?.arc_key && <StatusBadge tone="canon">当前篇章</StatusBadge>}
                <span className="muted">↗</span>
              </BookLink>
            ))
          ) : (
            <PageState empty title="尚未建立篇章" />
          )}
        </Card>
      </div>
      <Card
        title="最近活动"
        extra={
          <BookLink to="/runs" className="text-btn">
            全部记录 ↗
          </BookLink>
        }
      >
        {events.length ? (
          events
            .slice(-5)
            .reverse()
            .map((e: any) => (
              <BookLink className="activity-row" key={e.id} to={'/runs/' + run.run_id}>
                <span className="activity-dot" />
                <span>
                  第 {e.chapter || run.current_chapter} 章 · {label(e.phase)}
                </span>
                <StatusBadge status={e.status} />
                <time>{e.created_at}</time>
              </BookLink>
            ))
        ) : (
          <p className="muted">开始创作后，这里会记录故事的每一步进展。</p>
        )}
      </Card>
    </div>
  )
}
