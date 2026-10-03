import { useEffect, useState } from 'react'
import { useChapterCursor, useFilters, useQuery, useApi } from '../api/scope'

export function ChapterCursor() {
  const api = useApi()
  const { data } = useQuery({
    queryKey: ['home'],
    queryFn: () => api.get('/api/v1/home'),
    refetchInterval: 15000,
  })
  const latest = Math.max(1, data?.progress?.latest_chapter || 1)
  const { chapter, setChapter } = useChapterCursor()
  const at = Math.min(latest, chapter || latest)
  const [value, setValue] = useState(at)
  useEffect(() => setValue(at), [at])
  useEffect(() => {
    if (value === at) return
    const t = setTimeout(() => setChapter(value >= latest ? null : value), 200)
    return () => clearTimeout(t)
  }, [value, at, latest])
  return (
    <div className="chapter-cursor">
      <span className="muted">故事时间</span>
      <input
        aria-label="故事章节时光轴"
        type="range"
        min={1}
        max={latest}
        value={value}
        onChange={(e) => setValue(+e.target.value)}
      />
      <span>第 {value} 章</span>
      <button
        className="text-btn"
        onClick={() => {
          setValue(latest)
          setChapter(null)
        }}
        disabled={!chapter}
      >
        回到最新
      </button>
    </div>
  )
}
export function ChapterAxis({ from, to }: { from: number; to: number }) {
  const span = Math.max(1, to - from),
    step = span > 150 ? 50 : span > 60 ? 20 : span > 20 ? 10 : 5
  const ticks = [
    from,
    ...Array.from({ length: Math.floor(to / step) }, (_, i) => (i + 1) * step).filter(
      (n) => n > from && n < to,
    ),
    to,
  ]
  return (
    <div className="chapter-axis">
      {[...new Set(ticks)].map((n) => (
        <span key={n} style={{ left: `${((n - from) / span) * 100}%` }}>
          {n}
        </span>
      ))}
    </div>
  )
}
export function AxisControls({ latest }: { latest: number }) {
  const { params, patch } = useFilters()
  const from = Math.max(1, Number(params.get('from')) || 1)
  const to = Math.max(from, Number(params.get('to')) || latest)
  return (
    <div className="toolbar axis-controls">
      <label>
        第{' '}
        <input
          aria-label="起始章节"
          className="num"
          type="number"
          min={1}
          max={to}
          value={from}
          onChange={(e) => patch({ from: Math.max(1, Math.min(to, +e.target.value)) })}
        />{' '}
        章
      </label>
      <span>—</span>
      <label>
        第{' '}
        <input
          aria-label="结束章节"
          className="num"
          type="number"
          min={from}
          value={to}
          onChange={(e) => patch({ to: Math.max(from, +e.target.value) })}
        />{' '}
        章
      </label>
      <button
        className="btn sm"
        onClick={() => patch({ from, to: from + Math.max(5, Math.round((to - from) / 2)) })}
      >
        放大
      </button>
      <button className="btn sm" onClick={() => patch({ from, to: from + Math.max(10, (to - from) * 2) })}>
        缩小
      </button>
      <button className="text-btn" onClick={() => patch({ from: null, to: null, at: null })}>
        回到最新
      </button>
    </div>
  )
}
