// Auth token for the market web app. Login exchanges the same demo
// accounts the desktop ships with; token lives in localStorage.
const KEY = "mhc-market.token"
const USER_KEY = "mhc-market.user"

export function isAuthed(): boolean {
  return !!localStorage.getItem(KEY)
}

export function currentUser(): string {
  return localStorage.getItem(USER_KEY) ?? ""
}

export function saveToken(token: string, username: string): void {
  localStorage.setItem(KEY, token)
  localStorage.setItem(USER_KEY, username)
}

export function logout(): void {
  localStorage.removeItem(KEY)
  localStorage.removeItem(USER_KEY)
}

export function token(): string {
  return localStorage.getItem(KEY) ?? ""
}
