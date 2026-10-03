import { useNavigate } from 'react-router-dom'
import { useApi, useQuery, BookLink } from '../api/scope'
import { Card, DataTable, PageHeader, PageState, StatusBadge } from '../components/ui'
export default function Settings() {
  const api = useApi(),
    navigate = useNavigate()
  const books = useQuery({
    queryKey: ['books'],
    queryFn: () => api.get('/api/v1/books'),
  })
  const settings = useQuery({
    queryKey: ['settings'],
    queryFn: () => api.get('/api/v1/settings'),
  })
  return (
    <div className="page-stack">
      <PageHeader title="设置" description="管理书库、导出作品与查看模型配置" />
      <Card
        title="书库"
        extra={
          <BookLink className="btn sm" to="/wizard">
            新建故事
          </BookLink>
        }
      >
        <PageState loading={books.isPending} error={books.error} onRetry={() => void books.refetch()} />
        {books.data && (
          <DataTable
            rows={books.data.books}
            rowKey={(b: any) => b.name}
            columns={[
              {
                key: 'title',
                label: '书名',
                render: (b: any) => <strong>{b.title}</strong>,
              },
              {
                key: 'chapters',
                label: '进度',
                render: (b: any) => `${b.chapters} 章 · ${(b.chars / 10000).toFixed(1)} 万字`,
              },
              {
                key: 'actions',
                label: '操作',
                render: (b: any) => (
                  <div className="toolbar">
                    <button
                      className="btn sm"
                      disabled={api.book ? b.name === api.book + '.db' : b.default}
                      onClick={() =>
                        navigate('/?book=' + encodeURIComponent(b.default ? '' : b.name.replace(/\.db$/, '')))
                      }
                    >
                      {(api.book ? b.name === api.book + '.db' : b.default) ? '当前书库' : '切换'}
                    </button>
                    <a
                      className="btn sm"
                      href={api.url('/api/v1/export/novel', b.name.replace(/\.db$/, ''))}
                      download={b.title + '.md'}
                    >
                      导出正文
                    </a>
                  </div>
                ),
              },
            ]}
          />
        )}
      </Card>
      <Card title="模型配置">
        <PageState
          loading={settings.isPending}
          error={settings.error}
          onRetry={() => void settings.refetch()}
        />
        {settings.data && (
          <DataTable
            rows={Object.entries(settings.data.models).map(([role, model]: any) => ({ role, ...model }))}
            rowKey={(m: any) => m.role}
            columns={[
              {
                key: 'role',
                label: '创作环节',
                render: (m: any) =>
                  (
                    ({
                      writer: '写作',
                      planner: '规划',
                      reviewer: '审校',
                      revision: '修订',
                      architect: '开书',
                    }) as any
                  )[m.role] || m.role,
              },
              {
                key: 'model',
                label: '模型',
                render: (m: any) => m.model || '未配置',
              },
              {
                key: 'status',
                label: '状态',
                render: (m: any) => (
                  <StatusBadge tone={m.key_set ? 'pass' : 'warn'}>
                    {m.key_set ? '已配置' : '未配置'}
                  </StatusBadge>
                ),
              },
            ]}
          />
        )}
      </Card>
      <Card title="访问方式">
        <StatusBadge tone="pass">公开工作台</StatusBadge>
        <p className="muted">无需登录，所有页面、故事设定和创作操作均可访问。</p>
      </Card>
    </div>
  )
}
