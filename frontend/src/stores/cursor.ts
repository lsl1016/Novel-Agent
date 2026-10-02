import { create } from 'zustand'

/** 章节时光轴(全局时间游标):拖到第 N 章,全站 D2 视图按"截至第 N 章"重渲染。
 *  回拨正确性由服务端保证(chapter_at_or_before 语义),前端只做 key 联动。 */
interface CursorState {
  chapter: number | null
  setChapter: (n: number) => void
}

export const useCursor = create<CursorState>((set) => ({
  chapter: sessionStorage.getItem('novel_cursor')
    ? Number(sessionStorage.getItem('novel_cursor'))
    : null,
  setChapter: (n) => {
    sessionStorage.setItem('novel_cursor', String(n))
    set({ chapter: n })
  },
}))
