import { defineStore } from "pinia"
import { computed, ref } from "vue"
import { api, type AuthUser } from "../api/client"
import {
  clearAuthToken,
  setAuthToken,
  setUpstreamCredential,
} from "../api/auth-token"

/** Auth state for the SPA.
 *
 *  Three lifecycle moments:
 *  - ``bootstrap()`` runs once when the backend becomes reachable.
 *    It calls ``/auth/me`` with whatever token is in localStorage;
 *    if that succeeds the user stays logged in, otherwise the token
 *    is cleared.
 *  - ``login()`` posts credentials, persists the token, and stores
 *    the principal in memory.
 *  - ``logout()`` posts ``/auth/logout`` to invalidate the server-
 *    side token and clears local state. The SPA then bounces to
 *    the login view via the router guard.
 */
export const useAuthStore = defineStore("auth", () => {
  const user = ref<AuthUser | null>(null)
  const token = ref<string | null>(null)
  const loading = ref(false)
  const error = ref<string | null>(null)
  /** Set during the very first bootstrap so the router can wait on
   *  the /me round-trip before deciding to redirect to /login. */
  const bootstrapped = ref(false)

  const isAuthenticated = computed(
    () => token.value !== null && user.value !== null,
  )

  /** Restore session from localStorage + /me round-trip. Idempotent
   *  — second invocation is a no-op. Returns when the round-trip
   *  is done (success OR failure) so the caller can chain a
   *  redirect. */
  async function bootstrap(): Promise<void> {
    if (bootstrapped.value) return
    bootstrapped.value = true
    // Read token from localStorage so the store stays the single
    // source of truth after this point.
    const t = localStorage.getItem("mhc.auth.token")
    if (!t) return
    token.value = t
    loading.value = true
    try {
      const r = await api.me()
      user.value = r.user
      // /me re-emits the upstream credential so the SPA can
      // rehydrate it after a renderer reload (the IdP may have
      // rotated it). Always overwrite; a missing one clears.
      setUpstreamCredential(r.upstream_credential ?? null)
    } catch {
      // Stale token or backend error — clean up so the user lands
      // on the login screen.
      token.value = null
      user.value = null
      clearAuthToken()
    } finally {
      loading.value = false
    }
  }

  async function login(username: string, password: string): Promise<void> {
    loading.value = true
    error.value = null
    try {
      const r = await api.login(username, password)
      token.value = r.token
      user.value = r.user
      setAuthToken(r.token)
      // Server may have returned a credential the SPA must forward
      // on every subsequent request so deploy's marketplace
      // provider can hit the upstream skill market as this user.
      // ``None`` for the mock; real IdPs fill it in.
      setUpstreamCredential(r.upstream_credential ?? null)
    } catch (e) {
      error.value = e instanceof Error ? e.message : String(e)
      // Defensive: never leave a half-set state if the server
      // returned a malformed body (shouldn't, but cheap insurance).
      token.value = null
      user.value = null
      clearAuthToken()
      throw e
    } finally {
      loading.value = false
    }
  }

  async function logout(): Promise<void> {
    try {
      // Best-effort server-side invalidation. If it fails (token
      // already expired, network down) we still clear local state
      // so the SPA bounces to login.
      await api.logout()
    } catch {
      // ignore
    } finally {
      token.value = null
      user.value = null
      clearAuthToken()
    }
  }

  function clearError(): void {
    error.value = null
  }

  return {
    user,
    token,
    loading,
    error,
    bootstrapped,
    isAuthenticated,
    bootstrap,
    login,
    logout,
    clearError,
  }
})