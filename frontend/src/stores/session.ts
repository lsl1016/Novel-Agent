import { create } from 'zustand'

interface SessionState {
  token: string | null
  role: string | null
  authEnabled: boolean
  setSession: (token: string, role: string, authEnabled: boolean) => void
  logout: () => void
}

export const useSession = create<SessionState>((set) => ({
  token: sessionStorage.getItem('novel_token'),
  role: sessionStorage.getItem('novel_role'),
  authEnabled: true,
  setSession: (token, role, authEnabled) => {
    sessionStorage.setItem('novel_token', token)
    sessionStorage.setItem('novel_role', role)
    set({ token, role, authEnabled })
  },
  logout: () => {
    sessionStorage.removeItem('novel_token')
    sessionStorage.removeItem('novel_role')
    set({ token: null, role: null })
  },
}))
