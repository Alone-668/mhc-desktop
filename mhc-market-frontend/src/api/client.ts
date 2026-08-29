export interface MarketSkill {
  slug: string
  display_name: string
  description: string
  category: string
  author: string
  icon?: string
  sha: string
  size: number
  downloads: number
  updated_at: number
  published_at: number
  featured?: number
  rating_avg?: number
  rating_count?: number
}

export interface MarketStory {
  id: string
  title: string
  author: string
  skill_slug: string
  content: string
  created_at: number
}

export interface MySkill {
  slug: string
  sha: string
  size: number
  updated_at: number
  display_name?: string
  icon?: string
  category?: string
  delisted?: boolean  // content matches a delisted market entry
  author?: string  // market entry author when content matches one
  market_slug?: string  // matched market entry key (for delist)
}

export interface Review {
  user: string
  rating: number
  comment: string
  created_at: number
}

export interface Rating {
  slug: string
  average: number
  count: number
}

const API = "/api/v1"

async function j<T>(r: Response): Promise<T> {
  if (r.status === 401) {
    // Expired / invalid token: drop it and land on the login page.
    localStorage.removeItem("mhc-market.token")
    localStorage.removeItem("mhc-market.user")
    if (location.hash !== "#/login") {
      // setTimeout so the thrown error below doesn't race the redirect
      // inside the same call stack.
      setTimeout(() => {
        location.hash = "#/login"
      }, 0)
    }
  }
  if (!r.ok) {
    let detail = r.statusText
    try {
      detail = (await r.json()).detail ?? detail
    } catch {
      /* not json */
    }
    throw new Error(`${r.status}: ${detail}`)
  }
  if (r.status === 204) return undefined as T
  return r.json()
}

function authed(input: string, init: RequestInit = {}): Promise<Response> {
  const headers = new Headers(init.headers)
  const t = localStorage.getItem("mhc-market.token")
  if (t) headers.set("Authorization", `Bearer ${t}`)
  return fetch(input, { ...init, headers })
}

async function errr(r: Response): Promise<Error> {
  let detail = r.statusText
  try {
    detail = (await r.json()).detail ?? detail
  } catch {
    /* not json */
  }
  return new Error(`${r.status}: ${detail}`)
}

export const api = {
  login: (username: string, password: string) =>
    fetch(`${API}/auth/login`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ username, password }),
    }).then(j<{ token: string; username: string; is_admin?: boolean }>),

  listSkills: async (
    q = "",
    category = "",
    sort = "downloads",
    featured = false,
    limit?: number,
    offset = 0,
  ): Promise<{ items: MarketSkill[]; total: number }> => {
    const url =
      `${API}/skills?q=${encodeURIComponent(q)}&category=${encodeURIComponent(category)}` +
      `&sort=${sort}&featured=${featured}` +
      (limit != null ? `&limit=${limit}&offset=${offset}` : "")
    const r = await fetch(url)
    if (!r.ok) throw await errr(r)
    const total = Number(r.headers.get("X-Total-Count") ?? "0")
    return { items: (await r.json()) as MarketSkill[], total }
  },

  getSkill: (slug: string) => fetch(`${API}/skills/${slug}`).then(j<MarketSkill>),

  getSkillFiles: (slug: string) =>
    fetch(`${API}/skills/${encodeURIComponent(slug)}/files`).then(
      j<{ path: string; content: string }[]>,
    ),

  downloadPublic: async (slug: string) => {
    const r = await fetch(`${API}/skills/${encodeURIComponent(slug)}/download`)
    if (!r.ok) throw await errr(r)
    const sha = r.headers.get("X-Content-Sha") ?? ""
    const blob = await r.blob()
    return { blob, sha }
  },

  listStories: () => fetch(`${API}/stories`).then(j<MarketStory[]>),

  getStory: (id: string) => fetch(`${API}/stories/${id}`).then(j<MarketStory>),

  createStory: (body: { title: string; skill_slug: string; content: string }) =>
    authed(`${API}/stories`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(body),
    }).then(j<MarketStory>),

  listMine: () => authed(`${API}/me/skills`).then(j<MySkill[]>),

  downloadMine: async (slug: string) => {
    const r = await authed(`${API}/me/skills/${encodeURIComponent(slug)}`)
    if (!r.ok) throw new Error(`${r.status}`)
    const sha = r.headers.get("X-Content-Sha") ?? ""
    const blob = await r.blob()
    return { blob, sha }
  },

  uploadMine: (slug: string, dataB64: string, sha: string, baseSha?: string) =>
    authed(`${API}/me/skills/${encodeURIComponent(slug)}`, {
      method: "PUT",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ data: dataB64, sha, base_sha: baseSha ?? null }),
    }).then(j<MySkill>),

  getMineMd: (slug: string) =>
    authed(`${API}/me/skills/${encodeURIComponent(slug)}/md`).then(
      j<{ slug: string; name: string; description: string; body: string }>,
    ),

  editMine: (slug: string, body: { description?: string; body?: string }) =>
    authed(`${API}/me/skills/${encodeURIComponent(slug)}/edit`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(body),
    }).then(j<MySkill>),

  deleteMine: (slug: string) =>
    authed(`${API}/me/skills/${encodeURIComponent(slug)}`, {
      method: "DELETE",
    }).then(j<undefined>),

  publishSkill: (
    slug: string,
    dataB64: string,
    sha: string,
    displayName: string,
    description = "",
    category = "other",
    icon = "",
  ) =>
    authed(`${API}/skills/${encodeURIComponent(slug)}`, {
      method: "PUT",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({
        data: dataB64,
        sha,
        display_name: displayName,
        description,
        category,
        icon,
      }),
    }).then(j<MarketSkill>),

  delistSkill: (slug: string) =>
    authed(`${API}/skills/${encodeURIComponent(slug)}`, {
      method: "DELETE",
    }).then(j<undefined>),

  getRating: (slug: string) =>
    fetch(`${API}/skills/${encodeURIComponent(slug)}/rating`).then(j<Rating>),

  listReviews: (slug: string) =>
    fetch(`${API}/skills/${encodeURIComponent(slug)}/reviews`).then(j<Review[]>),

  addReview: (slug: string, rating: number, comment = "") =>
    authed(`${API}/skills/${encodeURIComponent(slug)}/reviews`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ rating, comment }),
    }).then(j<Rating>),
}

export function blobToB64(blob: Blob): Promise<string> {
  return new Promise((resolve, reject) => {
    const r = new FileReader()
    r.onload = () => {
      const res = r.result as string
      resolve(res.slice(res.indexOf(",") + 1))
    }
    r.onerror = () => reject(r.error)
    r.readAsDataURL(blob)
  })
}

export function fileToB64(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader()
    reader.onload = () => {
      const result = reader.result as string
      resolve(result.slice(result.indexOf(",") + 1))
    }
    reader.onerror = () => reject(reader.error)
    reader.readAsDataURL(file)
  })
}
