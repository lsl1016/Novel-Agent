import { useSession } from '../stores/session'

export class ApiError extends Error {
  status: number
  constructor(status: number, message: string) {
    super(message)
    this.status = status
  }
}

/** 给端点追加当前书参数(多书管理;默认书不带参数) */
function withBook(path: string): string {
  const book = useSession.getState().book
  if (!book || path.includes('book=')) return path
  return path + (path.includes('?') ? '&' : '?') + `book=${encodeURIComponent(book)}`
}

async function request(path: string, init?: RequestInit): Promise<any> {
  const { token } = useSession.getState()
  const resp = await fetch(withBook(path), {
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
  /** 快写动作:POST /api/v1/actions/{tool},返回 facade 的 {errNo,...} 信封 */
  action: (tool: string, args: Record<string, unknown>) =>
    request(`/api/v1/actions/${tool}`, { method: 'POST', body: JSON.stringify(args) }),
  /** 慢操作作业:立即返回 job id,前端轮询 */
  postJob: (tool: string, args: Record<string, unknown>, book?: string | null) =>
    request('/api/v1/jobs/' + tool, { method: 'POST', body: JSON.stringify({ args, book: book ?? useSession.getState().book }) }),
  getJob: (id: string) => request(`/api/v1/jobs/${id}`),
}

export function sseUrl(path: string): string {
  const { token, book } = useSession.getState()
  let p = path + (path.includes('?') ? '&' : '?')
  if (token) p += `token=${encodeURIComponent(token)}&`
  if (book) p += `book=${encodeURIComponent(book)}`
  return p
}

/** 作业轮询到终态;onTick 可用于进度展示 */
export async function pollJob(id: string, onTick?: (job: any) => void, timeoutMs = 600000): Promise<any> {
  const start = Date.now()
  for (;;) {
    const job = await api.getJob(id)
    onTick?.(job)
    if (job.status === 'done') return job.result
    if (job.status === 'failed') throw new Error(job.error || '作业失败')
    if (Date.now() - start > timeoutMs) throw new Error('作业超时')
    await new Promise((r) => setTimeout(r, 1200))
  }
}
