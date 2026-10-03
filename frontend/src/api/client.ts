export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message)
  }
}

/** Every client captures an immutable book; in-flight work cannot drift to another book. */
export function createApi(book: string | null, scopeSignal?: AbortSignal) {
  function url(path: string, target: string | null = book) {
    const u = new URL(path, window.location.origin)
    if (!u.searchParams.has('book')) u.searchParams.set('book', target || '')
    return u.pathname + u.search
  }
  async function request(path: string, init?: RequestInit, target: string | null = book): Promise<any> {
    scopeSignal?.throwIfAborted()
    const resp = await fetch(url(path, target), {
      ...init,
      signal: init?.signal || scopeSignal,
      headers: { 'Content-Type': 'application/json', ...init?.headers },
    })
    const body = await resp.json()
    if (!resp.ok)
      throw new ApiError(resp.status, body?.error?.message || body?.errMsg || `请求失败（${resp.status}）`)
    return body
  }
  const client = {
    book,
    url,
    get: (path: string, signal?: AbortSignal) => request(path, { signal: signal || scopeSignal }),
    post: (path: string, body: unknown, target: string | null = book) =>
      request(path, { method: 'POST', body: JSON.stringify(body ?? {}) }, target),
    action: (tool: string, args: Record<string, unknown>) =>
      request('/api/v1/actions/' + tool, {
        method: 'POST',
        body: JSON.stringify(args),
      }),
    async call(tool: string, args: Record<string, unknown> = {}) {
      const out = await client.action(tool, args)
      if (out.errNo !== 0) throw new Error(out.errMsg || '操作未完成')
      if (out.data?.ok === false)
        throw new Error(out.data.error?.message || JSON.stringify(out.data.errors || out.data))
      return out.data
    },
    postJob: (tool: string, args: Record<string, unknown>, target: string | null = book) =>
      request(
        '/api/v1/jobs/' + tool,
        { method: 'POST', body: JSON.stringify({ args, book: target }) },
        target,
      ),
    async pollJob(id: string, onTick?: (job: any) => void, timeoutMs = 600000): Promise<any> {
      const start = Date.now()
      while (true) {
        const job = await request('/api/v1/jobs/' + id)
        onTick?.(job)
        if (job.status === 'done') return job.result
        if (job.status === 'failed') throw new Error(job.error || '任务失败')
        if (Date.now() - start > timeoutMs) throw new Error('任务仍在后台进行，请稍后恢复查看')
        await new Promise<void>((resolve, reject) => {
          const finish = () => {
            scopeSignal?.removeEventListener('abort', abort)
            resolve()
          }
          const timer = window.setTimeout(finish, 1200)
          const abort = () => {
            clearTimeout(timer)
            reject(new DOMException('已切换书库', 'AbortError'))
          }
          scopeSignal?.addEventListener('abort', abort, { once: true })
        })
      }
    },
  }
  return client
}
export type BookApi = ReturnType<typeof createApi>
