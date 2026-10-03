import { createContext, useContext, useEffect, useState, type ReactNode } from 'react'
import {
  QueryClient,
  QueryClientProvider,
  useQuery as useBaseQuery,
  type UseQueryOptions,
} from '@tanstack/react-query'
import { useLocation, useNavigate, useSearchParams, Link, type LinkProps } from 'react-router-dom'
import { createApi, type BookApi } from './client'

const BookContext = createContext<BookApi | null>(null)
export function BookScope({ book, children }: { book: string | null; children: ReactNode }) {
  const [state] = useState(() => {
    const controller = new AbortController()
    return {
      controller,
      api: createApi(book, controller.signal),
      queries: new QueryClient({
        defaultOptions: {
          queries: { retry: 1, refetchOnWindowFocus: false, staleTime: 5000 },
        },
      }),
    }
  })
  useEffect(
    () => () => {
      state.controller.abort()
      void state.queries.cancelQueries()
      state.queries.clear()
    },
    [state],
  )
  return (
    <BookContext.Provider value={state.api}>
      <QueryClientProvider client={state.queries}>{children}</QueryClientProvider>
    </BookContext.Provider>
  )
}
export function useApi() {
  const api = useContext(BookContext)
  if (!api) throw new Error('BookScope is missing')
  return api
}
export function useQuery(options: UseQueryOptions<any, Error, any, readonly unknown[]>) {
  const { book } = useApi()
  return useBaseQuery({
    ...options,
    queryKey: [...options.queryKey, { book }],
  })
}
export function useBookHref() {
  const { book } = useApi()
  const location = useLocation()
  return (path: string) => {
    const url = new URL(path, window.location.origin)
    url.searchParams.set('book', book || '')
    const at = new URLSearchParams(location.search).get('at')
    if (at && !url.searchParams.has('at')) url.searchParams.set('at', at)
    return url.pathname + url.search + url.hash
  }
}
export function useBookNavigate() {
  const navigate = useNavigate(),
    href = useBookHref()
  return (path: string, options?: { replace?: boolean }) => navigate(href(path), options)
}
export function BookLink({ to, ...props }: Omit<LinkProps, 'to'> & { to: string }) {
  const href = useBookHref()
  return <Link to={href(to)} {...props} />
}
export function useFilters() {
  const [params, setParams] = useSearchParams()
  const patch = (values: Record<string, string | number | null>, replace = true) =>
    setParams(
      (prev) => {
        const next = new URLSearchParams(prev)
        Object.entries(values).forEach(([key, value]) =>
          value === null || value === '' ? next.delete(key) : next.set(key, String(value)),
        )
        return next
      },
      { replace },
    )
  return { params, patch }
}
export function useChapterCursor() {
  const { params, patch } = useFilters()
  const at = Number(params.get('at'))
  return {
    chapter: Number.isInteger(at) && at > 0 ? at : null,
    setChapter: (n: number | null) => patch({ at: n }),
  }
}
