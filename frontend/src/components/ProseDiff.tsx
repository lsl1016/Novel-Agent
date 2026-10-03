import { useMemo } from 'react'

/** Paragraph LCS keeps insertions aligned instead of shifting every subsequent line. */
export function diffParagraphs(before: string, after: string) {
  const a = before.split(/\n\s*\n/),
    b = after.split(/\n\s*\n/)
  if (a.length * b.length > 1000000) return [{ before, after, kind: 'changed' }]
  const dp = Array.from({ length: a.length + 1 }, () => new Uint32Array(b.length + 1))
  for (let i = a.length - 1; i >= 0; i--)
    for (let j = b.length - 1; j >= 0; j--)
      dp[i][j] = a[i] === b[j] ? dp[i + 1][j + 1] + 1 : Math.max(dp[i + 1][j], dp[i][j + 1])
  const rows: { before: string; after: string; kind: string }[] = []
  let i = 0,
    j = 0
  while (i < a.length || j < b.length) {
    if (i < a.length && j < b.length && a[i] === b[j]) {
      rows.push({ before: a[i++], after: b[j++], kind: 'same' })
      continue
    }
    const left: string[] = [],
      right: string[] = []
    while ((i < a.length || j < b.length) && !(i < a.length && j < b.length && a[i] === b[j])) {
      if (j >= b.length || (i < a.length && dp[i + 1][j] >= dp[i][j + 1])) left.push(a[i++])
      else right.push(b[j++])
    }
    rows.push({
      before: left.join('\n\n'),
      after: right.join('\n\n'),
      kind: 'changed',
    })
  }
  return rows
}
export function ProseDiff({
  before,
  after,
  beforeLabel,
  afterLabel,
}: {
  before: string
  after: string
  beforeLabel: string
  afterLabel: string
}) {
  const rows = useMemo(() => diffParagraphs(before, after), [before, after])
  return (
    <div className="prose-diff">
      <div className="diff-head">
        <strong>{beforeLabel}</strong>
        <strong>{afterLabel}</strong>
      </div>
      {rows.map((r, i) => (
        <div className={`diff-row ${r.kind}`} key={i}>
          <div>
            <small>{r.kind === 'changed' && r.before ? '− 旧内容' : ''}</small>
            {r.before || '—'}
          </div>
          <div>
            <small>{r.kind === 'changed' && r.after ? '+ 新内容' : ''}</small>
            {r.after || '—'}
          </div>
        </div>
      ))}
    </div>
  )
}
