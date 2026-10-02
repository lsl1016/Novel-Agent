import { create } from 'zustand'

interface SessionState {
  token: string | null
  role: string | null
  authEnabled: boolean
  book: string | null
  setSession: (token: string, role: string, authEnabled: boolean) => void
  setBook: (book: string | null) => void
  logout: () => void
}

export const useSession = create<SessionState>((set) => ({
  token: sessionStorage.getItem('novel_token'),
  role: sessionStorage.getItem('novel_role'),
  authEnabled: true,
  book: sessionStorage.getItem('novel_book'),
  setSession: (token, role, authEnabled) => {
    sessionStorage.setItem('novel_token', token)
    sessionStorage.setItem('novel_role', role)
    set({ token, role, authEnabled })
  },
  setBook: (book) => {
    if (book) sessionStorage.setItem('novel_book', book)
    else sessionStorage.removeItem('novel_book')
    set({ book })
  },
  logout: () => {
    sessionStorage.removeItem('novel_token')
    sessionStorage.removeItem('novel_role')
    set({ token: null, role: null })
  },
}))
