import { useEffect, useState } from 'react'
import { api } from '../api/client'
import { useSession } from '../stores/session'

export default function Login() {
  const setSession = useSession((s) => s.setSession)
  const [token, setToken] = useState('')
  const [error, setError] = useState('')
  const [checking, setChecking] = useState(true)

  // 未启用鉴权时自动以 admin 进入(本地开放模式)
  useEffect(() => {
    api.get('/api/v1/whoami').then((w) => {
      if (!w.auth_enabled) setSession('open', w.role, false)
      else setChecking(false)
    }).catch(() => setChecking(false))
  }, [setSession])

  const submit = async (e: React.FormEvent) => {
    e.preventDefault()
    setError('')
    try {
      const w = await fetch('/api/v1/whoami', { headers: { Authorization: `Bearer ${token}` } })
      if (w.status !== 200) throw new Error('令牌无效')
      const body = await w.json()
      setSession(token, body.role, true)
    } catch (err: any) {
      setError(err.message || '登录失败')
    }
  }

  return (
    <div style={{ height: '100%', display: 'grid', placeItems: 'center', background: 'var(--bg)' }}>
      <form onSubmit={submit} style={{ width: 320, background: 'var(--panel)', border: '1px solid var(--line)', borderRadius: 8, padding: 28, display: 'flex', flexDirection: 'column', gap: 12 }}>
        <h1 style={{ margin: 0, fontSize: 18 }}>Novel Agent 工作台</h1>
        <p style={{ margin: 0, color: 'var(--muted)', fontSize: 13, lineHeight: 1.7 }}>
          长篇叙事运行时 · 作者面板<br />输入访问令牌(NOVEL_FACADE_TOKENS)
        </p>
        {!checking && (
          <>
            <input
              autoFocus value={token} onChange={(e) => setToken(e.target.value)}
              placeholder="例如 planner:xxx 中的令牌值"
              style={{ padding: '8px 10px', borderRadius: 'var(--radius)', border: '1px solid var(--line)', background: 'var(--panel-2)', color: 'var(--text)' }}
            />
            {error && <div style={{ color: 'var(--sem-block)', fontSize: 13 }}>{error}</div>}
            <button type="submit" className="btn primary" style={{ justifyContent: 'center', padding: '9px' }}>
              进入工作台
            </button>
          </>
        )}
      </form>
    </div>
  )
}
