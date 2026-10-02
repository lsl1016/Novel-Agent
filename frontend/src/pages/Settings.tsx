import { useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from '../api/client'
import { Card, Pill, useToast } from '../components/ui'
import { useSession } from '../stores/session'

/** 设置(D3):书库管理/切换 + 模型路由 + 访问令牌 + 数据导出 */
export default function Settings() {
  const { role, book, setBook } = useSession()
  const push = useToast((s) => s.push)
  const qc = useQueryClient()
  const { data: booksData } = useQuery({ queryKey: ['books'], queryFn: () => api.get('/api/v1/books') })
  const { data: settings } = useQuery({ queryKey: ['settings'], queryFn: () => api.get('/api/v1/settings'), enabled: role === 'planner' || role === 'admin' })
  const canManage = role === 'planner' || role === 'admin'

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 14, maxWidth: 980 }}>
      <Card title="书库" extra={<span style={{ color: 'var(--muted)', fontSize: 12 }}>{booksData?.books_dir}</span>}>
        <table className="tbl">
          <thead><tr><th>书库文件</th><th>书名</th><th>章节</th><th>字数</th><th>更新</th><th></th></tr></thead>
          <tbody>
            {(booksData?.books || []).map((b: any) => (
              <tr key={b.name} style={{ background: (book ? b.name === book + '.db' : b.default) ? 'var(--accent-bg)' : undefined }}>
                <td className="mono">{b.name}{b.default && !book ? ' ·默认' : ''}</td>
                <td style={{ fontWeight: 600 }}>{b.title}</td>
                <td className="mono">{b.chapters}</td>
                <td className="mono dim">{(b.chars / 10000).toFixed(1)}万</td>
                <td className="mono dim">{b.updated_at}</td>
                <td>
                  <div style={{ display: 'flex', gap: 6 }}>
                    <button className="btn sm" onClick={() => {
                      setBook(b.default ? null : b.name.replace(/\.db$/, ''))
                      qc.invalidateQueries()
                      push('ok', `已切换到《${b.title}》`)
                    }}>切换</button>
                    <a className="btn sm" href={`/api/v1/export/novel?book=${encodeURIComponent(b.name.replace(/\.db$/, ''))}`}
                      download={`${b.title}.md`}>导出正文</a>
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        <div style={{ color: 'var(--muted)', fontSize: 12, marginTop: 8 }}>
          新书经"开书向导"创建;默认书由服务启动 <code className="tag">--db</code> 指定。
        </div>
      </Card>

      {settings && (
        <Card title="模型路由(五角色)" extra={<span style={{ color: 'var(--muted)', fontSize: 12 }}>env/llm.env · 密钥已脱敏</span>}>
          <table className="tbl">
            <thead><tr><th>角色</th><th>端点</th><th>模型</th><th>密钥</th></tr></thead>
            <tbody>
              {Object.entries(settings.models || {}).map(([r, m]: any) => (
                <tr key={r}>
                  <td style={{ fontWeight: 600 }}>{r}</td>
                  <td className="mono dim">{m.base_url || <span style={{ color: 'var(--sem-warn)' }}>回退 planner</span>}</td>
                  <td className="mono">{m.model || '—'}</td>
                  <td>{m.key_set ? <Pill tone="pass">已配置</Pill> : <Pill tone="warn">未配置</Pill>}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </Card>
      )}

      {settings && (
        <Card title="访问与安全">
          <div style={{ display: 'flex', gap: 20, fontSize: 13, color: 'var(--muted)', lineHeight: 1.9 }}>
            <div>
              <div>Facade 鉴权:{settings.facade_auth?.enabled ? <Pill tone="pass">已启用</Pill> : <Pill tone="warn">开放模式</Pill>}</div>
              <div style={{ fontSize: 12 }}>五类角色:viewer(读者)/writer/reviewer/planner/controller/admin;viewer 拿不到任何真相载荷。</div>
            </div>
            <div>
              <div>当前书:{settings.book?.db}</div>
              <div>参考图:{settings.reference_root || '未挂载'}</div>
            </div>
          </div>
        </Card>
      )}
    </div>
  )
}
