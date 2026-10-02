import type { ReactNode } from 'react'
import { useState } from 'react'
import { create } from 'zustand'

/** 状态徽章:语义色唯一入口,禁止散落色值 */
export function Pill({ tone, children }: { tone: 'canon' | 'draft' | 'secret' | 'block' | 'warn' | 'pass' | 'dormant' | 'muted' | 'accent' | 'reader'; children: ReactNode }) {
  const color = `var(--sem-${tone === 'muted' ? 'dormant' : tone})`
  return (
    <span style={{
      display: 'inline-flex', alignItems: 'center', gap: 4,
      border: `1px solid ${color}`, color, borderRadius: 999,
      padding: '1px 8px', fontSize: 12, lineHeight: '18px', whiteSpace: 'nowrap',
    }}>
      {children}
    </span>
  )
}

export function Card({ title, extra, children, style }: { title?: ReactNode; extra?: ReactNode; children: ReactNode; style?: React.CSSProperties }) {
  return (
    <section className="card fade-in" style={style}>
      {(title || extra) && (
        <header className="card-h">
          <h3>{title}</h3>
          {extra}
        </header>
      )}
      {children}
    </section>
  )
}

export function Stat({ label, value, tone }: { label: string; value: ReactNode; tone?: string }) {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 4, minWidth: 84 }}>
      <span style={{ color: 'var(--muted)', fontSize: 12 }}>{label}</span>
      <span style={{ fontSize: 22, fontWeight: 600, color: tone || 'var(--text)' }}>{value}</span>
    </div>
  )
}

export function verdictTone(v?: string | null): 'block' | 'warn' | 'pass' | 'muted' {
  if (v === 'BLOCK') return 'block'
  if (v === 'WARN') return 'warn'
  if (v === 'PASS') return 'pass'
  return 'muted'
}

/* ── 确认/表单对话框 ── */
export function Modal({ title, sub, children, actions, onClose }: {
  title: ReactNode; sub?: ReactNode; children?: ReactNode
  actions?: ReactNode; onClose?: () => void
}) {
  return (
    <div className="overlay" onClick={(e) => e.target === e.currentTarget && onClose?.()}>
      <div className="modal" onClick={(e) => e.stopPropagation()}>
        <h2>{title}</h2>
        {sub && <div className="sub">{sub}</div>}
        {children && <div style={{ marginTop: 12 }}>{children}</div>}
        <div className="modal-actions">
          {actions}
          {onClose && <button className="btn ghost" onClick={onClose}>取消</button>}
        </div>
      </div>
    </div>
  )
}

/* ── Toast ── */
interface Toast { id: number; kind: 'ok' | 'err' | 'warn'; text: string }
interface ToastState { toasts: Toast[]; push: (kind: Toast['kind'], text: string) => void; drop: (id: number) => void }
export const useToast = create<ToastState>((set) => ({
  toasts: [],
  push: (kind, text) => {
    const id = Date.now() + Math.random()
    set((s) => ({ toasts: [...s.toasts, { id, kind, text }] }))
    setTimeout(() => set((s) => ({ toasts: s.toasts.filter((t) => t.id !== id) })), kind === 'err' ? 7000 : 4200)
  },
  drop: (id) => set((s) => ({ toasts: s.toasts.filter((t) => t.id !== id) })),
}))

export function ToastHost() {
  const { toasts, drop } = useToast()
  return (
    <div className="toasts">
      {toasts.map((t) => (
        <div key={t.id} className={`toast ${t.kind}`} onClick={() => drop(t.id)}>
          <b>{t.kind === 'ok' ? '✓ ' : t.kind === 'err' ? '✕ ' : '⚠ '}</b>{t.text}
        </div>
      ))}
    </div>
  )
}

/** 动作按钮:调 /api/v1/actions/{tool},自动 toast 结果(errNo!==0 即错误) */
export function ActionButton({ tool, args, label, variant = '', confirm, onDone, disabled }: {
  tool: string
  args?: Record<string, unknown> | (() => Record<string, unknown>)
  label: ReactNode
  variant?: '' | 'primary' | 'danger' | 'gold'
  confirm?: { title: string; sub?: string }
  onDone?: (out: any) => void
  disabled?: boolean
}) {
  const [busy, setBusy] = useState(false)
  const push = useToast((s) => s.push)
  const [ask, setAsk] = useState(false)

  async function run() {
    setBusy(true)
    try {
      const { api } = await import('../api/client')
      const a = typeof args === 'function' ? args() : (args || {})
      const out = await api.action(tool, a)
      if (out && out.errNo === 0) {
        push('ok', `${String(label)} 成功`)
        onDone?.(out.data ?? out)
      } else {
        push('err', `${String(label)} 失败:${out?.errMsg || '未知错误'}`)
      }
    } catch (e: any) {
      push('err', `${String(label)} 请求失败:${e.message}`)
    } finally {
      setBusy(false)
      setAsk(false)
    }
  }

  return (
    <>
      <button className={`btn ${variant}`} disabled={disabled || busy} onClick={() => (confirm ? setAsk(true) : run())}>
        {busy && <span className="spin" />}{label}
      </button>
      {ask && (
        <Modal title={confirm!.title} sub={confirm!.sub} onClose={() => setAsk(false)}
          actions={<button className={`btn ${variant}`} disabled={busy} onClick={run}>{busy && <span className="spin" />}{label}</button>} />
      )}
    </>
  )
}
