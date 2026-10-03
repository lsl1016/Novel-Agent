import { Component, useEffect, useId, useRef, useState, type ReactNode } from 'react'
import { createPortal } from 'react-dom'
import { create } from 'zustand'
import { useApi } from '../api/scope'
import { label, statusTone } from './labels'

type Tone =
  'canon' | 'draft' | 'secret' | 'block' | 'warn' | 'pass' | 'dormant' | 'muted' | 'accent' | 'reader'
export function StatusBadge({
  tone = 'muted',
  children,
  status,
}: {
  tone?: Tone
  children?: ReactNode
  status?: string
}) {
  return (
    <span className={`badge ${status ? statusTone(status) : tone}`}>{status ? label(status) : children}</span>
  )
}
export const Pill = StatusBadge
export function Card({
  title,
  extra,
  children,
  style,
  className = '',
}: {
  title?: ReactNode
  extra?: ReactNode
  children: ReactNode
  style?: React.CSSProperties
  className?: string
}) {
  return (
    <section className={`card ${className}`} style={style}>
      {(title || extra) && (
        <header className="card-h">
          <h2>{title}</h2>
          {extra}
        </header>
      )}
      {children}
    </section>
  )
}
export function PageHeader({
  title,
  description,
  actions,
  eyebrow,
}: {
  title: string
  description?: ReactNode
  actions?: ReactNode
  eyebrow?: string
}) {
  return (
    <header className="page-header">
      <div>
        {eyebrow && <div className="eyebrow">{eyebrow}</div>}
        <h1>{title}</h1>
        {description && <p>{description}</p>}
      </div>
      {actions && <div className="toolbar">{actions}</div>}
    </header>
  )
}
export function Stat({ label: name, value, tone }: { label: string; value: ReactNode; tone?: string }) {
  return (
    <div className="stat">
      <span>{name}</span>
      <strong style={{ color: tone }}>{value}</strong>
    </div>
  )
}
export const verdictTone = statusTone
export function SegmentedControl<T extends string>({
  value,
  onChange,
  options,
  ariaLabel = '切换视图',
}: {
  value: T
  onChange: (v: T) => void
  options: { value: T; label: ReactNode; disabled?: boolean }[]
  ariaLabel?: string
}) {
  return (
    <div className="segmented" role="group" aria-label={ariaLabel}>
      {options.map((o) => (
        <button
          type="button"
          key={o.value}
          aria-pressed={value === o.value}
          disabled={o.disabled}
          className={value === o.value ? 'selected' : ''}
          onClick={() => onChange(o.value)}
        >
          {o.label}
        </button>
      ))}
    </div>
  )
}
export function PageState({
  loading,
  error,
  empty,
  onRetry,
  title,
  children,
}: {
  loading?: boolean
  error?: unknown
  empty?: boolean
  onRetry?: () => void
  title?: string
  children?: ReactNode
}) {
  if (loading)
    return (
      <div className="page-state skeleton" role="status" aria-label="加载中">
        <i />
        <i />
        <i />
        <span>正在读取故事…</span>
      </div>
    )
  if (error)
    return (
      <div className="page-state" role="alert">
        <span className="state-symbol">!</span>
        <h3>暂时无法加载</h3>
        <p>{error instanceof Error ? error.message : String(error)}</p>
        {onRetry && (
          <button className="btn" onClick={onRetry}>
            重新加载
          </button>
        )}
      </div>
    )
  if (empty)
    return (
      <div className="page-state">
        <span className="state-symbol">✦</span>
        <h3>{title || '这里还没有内容'}</h3>
        {children}
      </div>
    )
  return null
}
export class ErrorBoundary extends Component<{ children: ReactNode }, { error: Error | null }> {
  state: { error: Error | null } = { error: null }
  static getDerivedStateFromError(error: Error) {
    return { error }
  }
  render() {
    return this.state.error ? (
      <PageState error={this.state.error} onRetry={() => window.location.reload()} />
    ) : (
      this.props.children
    )
  }
}
export type Column<T> = {
  key: string
  label: string
  render: (row: T) => ReactNode
}
export function DataTable<T>({
  rows,
  columns,
  rowKey,
  onPick,
  empty = '暂无记录',
}: {
  rows: T[]
  columns: Column<T>[]
  rowKey: (row: T) => string | number
  onPick?: (row: T) => void
  empty?: string
}) {
  if (!rows.length) return <PageState empty title={empty} />
  return (
    <table className="tbl data-table">
      <thead>
        <tr>
          {columns.map((c) => (
            <th key={c.key}>{c.label}</th>
          ))}
        </tr>
      </thead>
      <tbody>
        {rows.map((row) => (
          <tr
            key={rowKey(row)}
            className={onPick ? 'row-hover' : ''}
            tabIndex={onPick ? 0 : undefined}
            onClick={() => onPick?.(row)}
            onKeyDown={(e) => {
              if (onPick && (e.key === 'Enter' || e.key === ' ')) {
                e.preventDefault()
                onPick(row)
              }
            }}
          >
            {columns.map((c) => (
              <td key={c.key} data-label={c.label}>
                {c.render(row)}
              </td>
            ))}
          </tr>
        ))}
      </tbody>
    </table>
  )
}
function Dialog({
  title,
  children,
  onClose,
  drawer = false,
}: {
  title: ReactNode
  children: ReactNode
  onClose?: () => void
  drawer?: boolean
}) {
  const ref = useRef<HTMLDivElement>(null),
    titleId = useId(),
    closeRef = useRef(onClose)
  closeRef.current = onClose
  useEffect(() => {
    const previous = document.activeElement as HTMLElement
    const node = ref.current
    const focusable = () => [
      ...(node?.querySelectorAll<HTMLElement>(
        'button:not(:disabled), a[href], input, textarea, select, [tabindex="0"]',
      ) || []),
    ]
    ;(focusable()[0] || node)?.focus()
    const handle = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        e.preventDefault()
        closeRef.current?.()
      }
      if (e.key === 'Tab') {
        const list = focusable(),
          first = list[0],
          last = list[list.length - 1]
        if (!first) {
          e.preventDefault()
          return
        }
        if (e.shiftKey && document.activeElement === first) {
          e.preventDefault()
          last.focus()
        } else if (!e.shiftKey && document.activeElement === last) {
          e.preventDefault()
          first.focus()
        }
      }
    }
    node?.addEventListener('keydown', handle)
    return () => {
      node?.removeEventListener('keydown', handle)
      previous?.focus()
    }
  }, [])
  return createPortal(
    <div
      className={`overlay ${drawer ? 'drawer-overlay' : ''}`}
      onMouseDown={(e) => e.target === e.currentTarget && onClose?.()}
    >
      <div
        className={drawer ? 'drawer' : 'modal'}
        ref={ref}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        tabIndex={-1}
      >
        <header className="dialog-header">
          <h2 id={titleId}>{title}</h2>
          {onClose && (
            <button className="icon-btn" aria-label="关闭" onClick={onClose}>
              ×
            </button>
          )}
        </header>
        {children}
      </div>
    </div>,
    document.body,
  )
}
export function Drawer({
  title,
  children,
  onClose,
}: {
  title: ReactNode
  children: ReactNode
  onClose: () => void
}) {
  return (
    <Dialog title={title} onClose={onClose} drawer>
      <div className="drawer-body">{children}</div>
    </Dialog>
  )
}
export function Modal({
  title,
  sub,
  children,
  actions,
  onClose,
}: {
  title: ReactNode
  sub?: ReactNode
  children?: ReactNode
  actions?: ReactNode
  onClose?: () => void
}) {
  return (
    <Dialog title={title} onClose={onClose}>
      {sub && <p className="muted">{sub}</p>}
      {children}
      <div className="modal-actions">
        {onClose && (
          <button className="btn ghost" onClick={onClose}>
            取消
          </button>
        )}
        {actions}
      </div>
    </Dialog>
  )
}
interface Toast {
  id: number
  kind: 'ok' | 'err' | 'warn'
  text: string
}
export const useToast = create<{
  toasts: Toast[]
  push: (kind: Toast['kind'], text: string) => void
  drop: (id: number) => void
}>((set) => ({
  toasts: [],
  push: (kind, text) => {
    const id = Date.now() + Math.random()
    set((s) => ({ toasts: [...s.toasts.slice(-3), { id, kind, text }] }))
    setTimeout(
      () => set((s) => ({ toasts: s.toasts.filter((t) => t.id !== id) })),
      kind === 'err' ? 9000 : 4500,
    )
  },
  drop: (id) => set((s) => ({ toasts: s.toasts.filter((t) => t.id !== id) })),
}))
export function ToastHost() {
  const { toasts, drop } = useToast()
  return (
    <div className="toasts" aria-live="polite">
      {toasts.map((t) => (
        <div key={t.id} role={t.kind === 'err' ? 'alert' : 'status'} className={`toast ${t.kind}`}>
          <span>{t.text}</span>
          <button aria-label="关闭通知" onClick={() => drop(t.id)}>
            ×
          </button>
        </div>
      ))}
    </div>
  )
}
export function ActionButton({
  tool,
  args,
  label: text,
  variant = '',
  confirm,
  onDone,
  disabled,
}: {
  tool: string
  args?: Record<string, unknown> | (() => Record<string, unknown>)
  label: ReactNode
  variant?: '' | 'primary' | 'danger' | 'gold'
  confirm?: { title: string; sub?: string }
  onDone?: (out: any) => void | Promise<void>
  disabled?: boolean
}) {
  const api = useApi(),
    [busy, setBusy] = useState(false),
    [ask, setAsk] = useState(false)
  const push = useToast((s) => s.push)
  async function run() {
    setBusy(true)
    try {
      const out = await api.call(tool, typeof args === 'function' ? args() : args || {})
      await onDone?.(out)
      push('ok', '操作已完成')
    } catch (e) {
      if ((e as Error).name !== 'AbortError') push('err', (e as Error).message)
    } finally {
      setBusy(false)
      setAsk(false)
    }
  }
  return (
    <>
      <button
        className={`btn ${variant}`}
        disabled={disabled || busy}
        onClick={() => (confirm ? setAsk(true) : void run())}
      >
        {busy && <span className="spin" />}
        {text}
      </button>
      {ask && (
        <Modal
          title={confirm!.title}
          sub={confirm!.sub}
          onClose={busy ? undefined : () => setAsk(false)}
          actions={
            <button className={`btn ${variant}`} disabled={busy} onClick={run}>
              {busy ? '处理中…' : text}
            </button>
          }
        />
      )}
    </>
  )
}
export function DetailFields({ data }: { data: Record<string, any> }) {
  return (
    <dl className="detail-fields">
      {Object.entries(data)
        .filter(([, v]) => v != null && v !== '')
        .map(([key, v]) => (
          <div key={key}>
            <dt>{key}</dt>
            <dd>
              {Array.isArray(v)
                ? v.map((x) => (typeof x === 'string' ? x : JSON.stringify(x))).join('、')
                : typeof v === 'object'
                  ? JSON.stringify(v)
                  : String(v)}
            </dd>
          </div>
        ))}
    </dl>
  )
}
