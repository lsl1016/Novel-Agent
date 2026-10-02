import { useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { api, pollJob } from '../api/client'
import { Card, Pill, useToast } from '../components/ui'
import { useSession } from '../stores/session'

/** 开书向导(D3·旗舰页):一句话 → 四段生成(作业) → 开书档案 → 应用/开跑 */
export default function Wizard() {
  const [idea, setIdea] = useState('')
  const [target, setTarget] = useState(120)
  const [genre, setGenre] = useState('')
  const [tone, setTone] = useState('')
  const [counter, setCounter] = useState('')
  const [bookName, setBookName] = useState('')
  const [busy, setBusy] = useState(false)
  const [phase, setPhase] = useState('')
  const [result, setResult] = useState<any | null>(null)
  const [applied, setApplied] = useState(false)
  const push = useToast((s) => s.push)
  const qc = useQueryClient()
  const role = useSession((s) => s.role)
  const canGen = role === 'planner' || role === 'admin'

  async function generate() {
    if (!idea.trim()) return
    setBusy(true); setPhase('准备书库…'); setResult(null); setApplied(false)
    try {
      if (bookName.trim()) {
        setPhase(`创建新书 ${bookName.trim()}.db …`)
        await api.post('/api/v1/books', { name: bookName.trim() })
      }
      setPhase('四段生成中:蓝图 → 实体 → 叙事 → 结构(约 1-3 分钟)…')
      const job = await api.postJob('novel_architecture_generate', {
        idea: idea.trim(),
        options: {
          target_total_chapters: target,
          ...(genre.trim() ? { genre: genre.trim() } : {}),
          ...(tone.trim() ? { tone: tone.trim() } : {}),
          ...(counter.trim() ? { counter_expectation: counter.trim() } : {}),
          mode: 'auto',
        },
      }, bookName.trim() || null)
      const out = await pollJob(job.job.id, (j) => setPhase(`生成中… (${j.status})`))
      setResult(out)
      setPhase('')
      const errs = out?.validation?.errors?.length || 0
      push(errs ? 'warn' : 'ok', errs ? `生成完成,但有 ${errs} 个校验错误` : '生成完成:0 error')
    } catch (e: any) {
      push('err', `生成失败:${e.message}`)
      setPhase('')
    } finally {
      setBusy(false)
    }
  }

  const arch = result?.architecture
  const val = result?.validation

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 14, maxWidth: 1080 }}>
      <Card title="一句话开书" extra={<span style={{ color: 'var(--muted)', fontSize: 12 }}>四段生成 + 跨引用确定性校验 + 有界修复</span>}>
        <textarea className="paper-edit" style={{ minHeight: 84, fontFamily: 'var(--font-ui)', fontSize: 14 }}
          placeholder='例如:写一部百万字东方玄幻,核心是身份谜题 + 世界真相反转。'
          value={idea} onChange={(e) => setIdea(e.target.value)} disabled={busy} />
        <div style={{ display: 'flex', gap: 10, marginTop: 10, flexWrap: 'wrap', alignItems: 'center' }}>
          <label style={{ color: 'var(--muted)', fontSize: 12 }}>目标章数</label>
          <input className="num" type="number" min={10} max={1000} value={target} onChange={(e) => setTarget(+e.target.value)} disabled={busy} />
          <input className="input" style={{ width: 130 }} placeholder="题材(可选)" value={genre} onChange={(e) => setGenre(e.target.value)} disabled={busy} />
          <input className="input" style={{ width: 130 }} placeholder="语气(可选)" value={tone} onChange={(e) => setTone(e.target.value)} disabled={busy} />
          <input className="input" style={{ width: 200 }} placeholder="反套路:避开最俗的…(可选)" value={counter} onChange={(e) => setCounter(e.target.value)} disabled={busy} />
          <input className="input" style={{ width: 150 }} placeholder="新书库名(可选,如 my-book)" value={bookName} onChange={(e) => setBookName(e.target.value)} disabled={busy} />
          <div style={{ flex: 1 }} />
          {canGen ? (
            <button className="btn primary" disabled={busy || !idea.trim()} onClick={generate}>
              {busy && <span className="spin" />}{busy ? '生成中' : '✦ 生成开书档案'}
            </button>
          ) : <Pill tone="muted">需要 planner/admin 令牌</Pill>}
        </div>
        {phase && <div style={{ marginTop: 10, color: 'var(--muted)', fontSize: 13 }}>{phase}</div>}
      </Card>

      {result && arch && (
        <>
          <Card title="开书档案" extra={
            <span style={{ display: 'inline-flex', gap: 8, alignItems: 'center' }}>
              {(val?.errors?.length || 0) > 0 ? <Pill tone="block">{val.errors.length} 错误</Pill> : <Pill tone="pass">0 error</Pill>}
              {(val?.warnings?.length || 0) > 0 && <Pill tone="warn">{val.warnings.length} warning</Pill>}
              {result.repair_rounds > 0 && <Pill tone="muted">修复 {result.repair_rounds} 轮</Pill>}
            </span>
          }>
            <Bible arch={arch} assumptions={result.assumptions} />
          </Card>
          {val?.errors?.length > 0 && (
            <Card title="校验错误(未通过闸门,不可应用)">
              {val.errors.map((e: any, i: number) => (
                <div key={i} style={{ fontFamily: 'var(--font-mono)', fontSize: 12.5, color: 'var(--sem-block)', padding: '2px 0' }}>
                  {e.code} {e.message || ''} {e.group ? `(${e.group})` : ''}
                </div>
              ))}
            </Card>
          )}
          {val?.warnings?.length > 0 && (
            <Card title="警告">
              {val.warnings.map((w: any, i: number) => (
                <div key={i} style={{ fontFamily: 'var(--font-mono)', fontSize: 12, color: 'var(--sem-warn)', padding: '1px 0' }}>
                  {w.code} {w.message || ''}
                </div>
              ))}
            </Card>
          )}
          {(val?.errors?.length || 0) === 0 && (
            <Card title="应用" extra={<span style={{ color: 'var(--muted)', fontSize: 12 }}>生成 ≠ 应用;应用是显式动作</span>}>
              <div style={{ display: 'flex', gap: 10, alignItems: 'center' }}>
                <button className="btn gold" disabled={busy || applied} onClick={applyArch(bookName, result, push, () => setApplied(true))}>
                  {applied ? '✓ 已应用' : `应用为正典起点${bookName.trim() ? `(${bookName.trim()}.db)` : '(当前书)'}`}
                </button>
                <span style={{ color: 'var(--muted)', fontSize: 12 }}>
                  应用后可经运行中心/CLI 启动长跑;或 <code className="tag">./novel.sh new "创意" N 3</code> 一条命令全链路。
                </span>
              </div>
            </Card>
          )}
        </>
      )}
    </div>
  )
}

function applyArch(bookName: string, result: any, push: any, onDone: () => void) {
  return async () => {
    try {
      // 应用走作业执行器:与生成同一 book 作用域,且过同一确定性闸门
      const job = await api.postJob('story_architect_apply', { architecture: result.architecture }, bookName.trim() || null)
      await pollJob(job.job.id)
      push('ok', '架构已应用为正典起点')
      onDone()
    } catch (e: any) {
      push('err', `应用失败:${e.message}`)
    }
  }
}

function Bible({ arch, assumptions }: { arch: any; assumptions: any }) {
  const bp = arch.blueprint || {}
  const facts = arch.world_facts || []
  const threads = arch.threads || []
  const arcs = arch.arcs || []
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
      <div>
        <div style={{ fontSize: 20, fontWeight: 700, fontFamily: 'var(--font-prose)' }}>{bp.title || '未命名'}</div>
        <div style={{ color: 'var(--muted)', marginTop: 4, lineHeight: 1.7 }}>{bp.core_promise}</div>
        <div style={{ display: 'flex', gap: 6, marginTop: 8, flexWrap: 'wrap' }}>
          {bp.genre && <span className="tag">{bp.genre}</span>}
          {bp.tone && <span className="tag">{bp.tone}</span>}
          <span className="tag">{threads.length} 线程</span>
          <span className="tag">{arcs.length} 弧</span>
          <span className="tag">{(arch.entities || []).length} 实体</span>
          <span className="tag">章长目标 {bp.chapter_length_target}</span>
        </div>
      </div>
      <div style={{ display: 'grid', gridTemplateColumns: '1.2fr 1fr', gap: 14 }}>
        <div>
          <SubTitle>世界真相与揭示计划(作者可见)</SubTitle>
          <table className="tbl">
            <tbody>
              {facts.map((f: any) => (
                <tr key={f.fact_key}>
                  <td className="mono" style={{ color: 'var(--sem-secret)' }}>🔒 {f.fact_key}</td>
                  <td>{String(f.truth).slice(0, 60)}</td>
                  <td className="mono dim">ch{f.reveal_after ?? '—'} 揭示</td>
                </tr>
              ))}
            </tbody>
          </table>
          <SubTitle>叙事线</SubTitle>
          <table className="tbl">
            <tbody>
              {threads.map((t: any) => (
                <tr key={t.thread_key}>
                  <td>{t.name}</td>
                  <td className="dim">{t.thread_type}</td>
                  <td className="mono dim">ch{t.introduced_chapter} → {t.target_min}–{t.target_max}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <div>
          <SubTitle>篇章结构</SubTitle>
          {arcs.map((a: any, i: number) => (
            <div key={a.arc_key} style={{ padding: '5px 0', borderBottom: '1px solid var(--line)', fontSize: 13 }}>
              <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
                <Pill tone={i === 0 ? 'canon' : 'muted'}>{a.order_no}</Pill>
                <b>{a.name}</b>
                <span className="mono dim" style={{ marginLeft: 'auto' }}>ch{a.start_chapter}–{a.target_end_chapter}</span>
              </div>
              <div style={{ color: 'var(--muted)', fontSize: 12, marginTop: 2 }}>{a.primary_goal}</div>
            </div>
          ))}
          {assumptions?.length > 0 && (
            <>
              <SubTitle>本次生成采用的假设(auto 模式推断,可否决后重生成)</SubTitle>
              {assumptions.map((a: string, i: number) => (
                <div key={i} style={{ fontSize: 12.5, color: 'var(--muted)', padding: '2px 0', lineHeight: 1.6 }}>· {a}</div>
              ))}
            </>
          )}
        </div>
      </div>
    </div>
  )
}

function SubTitle({ children }: { children: React.ReactNode }) {
  return <div style={{ color: 'var(--muted)', fontSize: 11.5, letterSpacing: '.08em', margin: '12px 0 6px' }}>{children}</div>
}
