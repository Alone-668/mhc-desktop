// Auth token helpers.
//
// Token persistence is intentionally separate from the auth store so
// the store can be replaced (or mocked in tests) without losing the
// persistence layer. The token lives in localStorage under
// ``mhc.auth.token``; cleared on logout.
//
// We also stash the per-user upstream-market credential (cookie,
// OAuth token, whatever the enterprise IdP gave us) under
// ``mhc.auth.upstream`` so deploy's marketplace provider can
// forward it. The kernel middleware namespaces any
// ``X-MHC-Upstream-…`` header it sees into
// ``request.state.upstream_headers``.

const LS_KEY = "mhc.auth.token"
const LS_UPSTREAM_KEY = "mhc.auth.upstream"

export function getAuthToken(): string | null {
  try {
    const v = localStorage.getItem(LS_KEY)
    return v && v.length > 0 ? v : null
  } catch {
    return null
  }
}

export function setAuthToken(token: string): void {
  try {
    localStorage.setItem(LS_KEY, token)
  } catch {
    // ignore — likely quota / privacy mode
  }
}

export function clearAuthToken(): void {
  try {
    localStorage.removeItem(LS_KEY)
    localStorage.removeItem(LS_UPSTREAM_KEY)
  } catch {
    // ignore
  }
}

/** Read the upstream-market credential the user logged in with.
 *
 *  ``null`` when no credential was supplied (e.g. the mock auth
 *  flow). The marketplace provider on the deploy side will fall
 *  back to anonymous calls when this is missing.
 */
export function getUpstreamCredential(): string | null {
  try {
    const v = localStorage.getItem(LS_UPSTREAM_KEY)
    return v && v.length > 0 ? v : null
  } catch {
    return null
  }
}

/** Persist the upstream-market credential returned at login time.
 *
 *  Typically a cookie string (``session=…; csrf=…``) or an OAuth
 *  bearer token. Stored in localStorage so it survives a renderer
 *  reload; cleared on logout (see ``clearAuthToken``).
 */
export function setUpstreamCredential(credential: string | null): void {
  try {
    if (credential === null || credential.length === 0) {
      localStorage.removeItem(LS_UPSTREAM_KEY)
    } else {
      localStorage.setItem(LS_UPSTREAM_KEY, credential)
    }
  } catch {
    // ignore
  }
}