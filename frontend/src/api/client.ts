import { useSession } from '../stores/session'

export class ApiError extends Error {
  status: number
  constructor(status: number, message: string) {
    super(message)
    this.status = status
  }
}

async function request(path: string, init?: RequestInit): Promise<any> {
  const token = useSession.getState().token
  const resp = await fetch(path, {
    ...init,
    headers: {
      'Content-Type': 'application/json',
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...(init?.headers || {}),
    },
  })
  if (resp.status === 401) {
    useSession.getState().logout()
    throw new ApiError(401, 'unauthorized')
  }
  if (!resp.ok) {
    let message = `HTTP ${resp.status}`
    try {
      const body = await resp.json()
      message = body?.error?.message || body?.errMsg || message
    } catch { /* keep default */ }
    throw new ApiError(resp.status, message)
  }
  return resp.json()
}

export const api = {
  get: (path: string) => request(path),
  post: (path: string, body: unknown) =>
    request(path, { method: 'POST', body: JSON.stringify(body ?? {}) }),
  /** 写动作:POST /api/v1/actions/{tool},返回 facade 的 {errNo,...} 信封 */
  action: (tool: string, args: Record<string, unknown>) =>
    request(`/api/v1/actions/${tool}`, { method: 'POST', body: JSON.stringify(args) }),
}

export function sseUrl(path: string): string {
  const token = useSession.getState().token
  return path + (path.includes('?') ? '&' : '?') + (token ? `token=${encodeURIComponent(token)}` : '')
}
