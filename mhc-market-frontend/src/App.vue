<script setup lang="ts">
import { computed, ref } from "vue"
import { RouterLink, RouterView, useRoute, useRouter } from "vue-router"
import { currentUser, logout } from "./api/auth"
import { locale, setLocale, t } from "./i18n"
import { isDark, toggleTheme } from "./theme"
import AppToast from "./components/AppToast.vue"
import { marketQuery } from "./lib/market"

const router = useRouter()
const route = useRoute()
const menuOpen = ref(false)
// Login is a standalone full-viewport page: no top nav, no tools/avatar.
const isLogin = computed(() => route.name === "login")
// Reactive identity: read from the token store, updated on route change so
// the avatar reflects the signed-in user immediately after login.
const me = ref(currentUser())

function onAvatar() {
  menuOpen.value = !menuOpen.value
}
function doLogout() {
  menuOpen.value = false
  logout()
  router.push({ name: "login" })
}
function onDocClick(e: MouseEvent) {
  if (!(e.target as HTMLElement).closest(".avatar-wrap")) menuOpen.value = false
}
router.afterEach(() => {
  me.value = currentUser()
})
if (typeof document !== "undefined") {
  document.addEventListener("click", onDocClick)
}
</script>

<template>
  <div class="shell">
    <nav v-if="!isLogin" class="nav">
      <div class="nav-inner">
        <RouterLink to="/" class="brand">
          <span class="logo">🧩</span>
          <span class="brand-name">{{ t("market.title") }}</span>
        </RouterLink>
        <div class="nav-links">
          <RouterLink to="/" class="nav-item">{{ t("nav.market") }}</RouterLink>
          <RouterLink to="/mine" class="nav-item">{{ t("nav.mine") }}</RouterLink>
        </div>
        <div class="nav-search">
          <svg class="s-icon" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><circle cx="11" cy="11" r="7" /><line x1="21" y1="21" x2="16.65" y2="16.65" /></svg>
          <input v-model="marketQuery" :placeholder="t('nav.search')" />
        </div>
        <div class="nav-tools">
          <button class="icon-btn" :title="isDark ? t('theme.light') : t('theme.dark')" @click="toggleTheme">
            <span v-if="isDark">🌙</span><span v-else>☀️</span>
          </button>
          <button class="icon-btn" :title="locale === 'zh' ? 'English' : '中文'" @click="setLocale(locale === 'zh' ? 'en' : 'zh')">
            {{ locale === "zh" ? "EN" : "中" }}
          </button>
          <div class="avatar-wrap">
            <button class="avatar" @click="onAvatar">{{ me.charAt(0).toUpperCase() || "A" }}</button>
            <div v-if="menuOpen" class="menu">
              <div class="menu-user">{{ me }}</div>
              <button class="menu-item logout" @click="doLogout">{{ t("nav.logout") }}</button>
            </div>
          </div>
        </div>
      </div>
    </nav>

    <main :class="['main', { login: isLogin }]">
      <RouterView />
    </main>

    <AppToast />
  </div>
</template>

<style>
/* ── design tokens ── */
:root {
  --bg: #f6f7f9; --bg-elev: #ffffff; --surface-2: #f1f3f6;
  --border: #e6e8ee; --border-strong: #d6dae2;
  --text: #10131a; --text-mid: #5c6470; --text-faint: #9aa3b0;
  --accent: #2563eb; --accent-strong: #1d4fd8; --accent-soft: #eef3ff; --accent-fg: #ffffff;
  --success: #16a34a; --success-soft: #eefaf2;
  --danger: #dc2626; --danger-soft: #fdf0ef; --warn: #d97706; --warn-soft: #fff8eb;
  --radius-card: 14px; --radius-btn: 9px; --radius-pill: 999px;
  --shadow-sm: 0 1px 2px rgba(16,19,26,.05), 0 1px 3px rgba(16,19,26,.04);
  --shadow-md: 0 4px 16px rgba(16,19,26,.06), 0 1px 3px rgba(16,19,26,.05);
  --shadow-lg: 0 16px 48px rgba(16,19,26,.14), 0 2px 8px rgba(16,19,26,.06);
  --ease: cubic-bezier(.16,1,.3,1);
}
:root[data-theme="dark"] {
  --bg: #0c0f14; --bg-elev: #141922; --surface-2: #1b2130;
  --border: #232a38; --border-strong: #2f3848;
  --text: #eef1f6; --text-mid: #9aa3b2; --text-faint: #6b7484;
  --accent: #4f83f7; --accent-strong: #6a97f9; --accent-soft: #1a2740; --accent-fg: #0b0e14;
  --success: #34d399; --success-soft: #0f2b22;
  --danger: #f87171; --danger-soft: #2b1616; --warn: #fbbf24; --warn-soft: #2b2410;
  --shadow-sm: 0 1px 2px rgba(0,0,0,.3); --shadow-md: 0 4px 16px rgba(0,0,0,.4); --shadow-lg: 0 16px 48px rgba(0,0,0,.6);
}

* { box-sizing: border-box; }
html, body { margin: 0; padding: 0; }
body { font-family: -apple-system, BlinkMacSystemFont, "PingFang SC", "Segoe UI", Roboto, sans-serif; background: var(--bg); color: var(--text); -webkit-font-smoothing: antialiased; text-rendering: optimizeLegibility; line-height: 1.5; min-height: 100dvh; }
h1,h2,h3,h4 { margin: 0; letter-spacing: -0.02em; font-weight: 700; }
a { color: inherit; text-decoration: none; }

/* ── top nav (per design reference) ── */
.nav { position: sticky; top: 0; z-index: 40; background: color-mix(in srgb, var(--bg-elev) 88%, transparent); backdrop-filter: saturate(160%) blur(14px); border-bottom: 1px solid var(--border); }
.nav-inner { max-width: 1200px; margin: 0 auto; padding: 0 24px; height: 64px; display: flex; align-items: center; gap: 28px; }
.nav-tools { display: flex; align-items: center; gap: 10px; margin-left: auto; }
.nav-tools .avatar-wrap { margin-left: 2px; }
/* Pill icon buttons, matching the nav-item / nav-search radius system. */
.icon-btn {
  min-width: 34px;
  height: 34px;
  padding: 0 11px;
  border: 0;
  border-radius: var(--radius-pill);
  background: transparent;
  color: var(--text-mid);
  font: inherit;
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
  display: grid;
  place-items: center;
  transition: background .15s, color .15s;
}
.icon-btn:hover { background: var(--surface-2); color: var(--text); }
.brand { display: flex; align-items: center; gap: 10px; font-weight: 800; font-size: 17px; letter-spacing: -0.02em; }
.brand .logo { width: 30px; height: 30px; border-radius: 9px; background: linear-gradient(135deg, var(--accent), #7c3aed); display: grid; place-items: center; color: #fff; font-size: 15px; }
.nav-links { display: flex; gap: 4px; flex: 1; }
.nav-item { padding: 8px 16px; border-radius: var(--radius-pill); color: var(--text-mid); font-size: 14.5px; font-weight: 500; transition: color .15s, background .15s; }
.nav-item:hover { color: var(--text); }
.nav-item.router-link-active { color: var(--accent); background: var(--accent-soft); font-weight: 600; }
.nav-search { display: flex; align-items: center; gap: 8px; background: var(--surface-2); border: 1px solid transparent; border-radius: var(--radius-pill); padding: 9px 16px; width: 240px; transition: border-color .15s, background .15s; }
.nav-search:focus-within { border-color: var(--accent); background: var(--bg-elev); }
.nav-search .s-icon { color: var(--text-faint); flex-shrink: 0; }
.nav-search input { border: 0; background: transparent; font-size: 13.5px; outline: none; width: 100%; color: var(--text); }

/* avatar + dropdown */
.avatar-wrap { position: relative; }
.avatar { width: 36px; height: 36px; border-radius: 50%; border: 0; background: linear-gradient(135deg, #3b82f6, #6366f1); color: #fff; font-weight: 700; font-size: 15px; cursor: pointer; display: grid; place-items: center; }
.avatar:hover { filter: brightness(1.08); }
.menu { position: absolute; right: 0; top: calc(100% + 10px); background: var(--bg-elev); border: 1px solid var(--border); border-radius: 12px; box-shadow: var(--shadow-lg); min-width: 180px; padding: 6px; z-index: 50; }
.menu-user { padding: 8px 12px 10px; font-size: 13px; font-weight: 600; border-bottom: 1px solid var(--border); margin-bottom: 4px; }
.menu-item { display: block; width: 100%; text-align: left; padding: 8px 12px; border: 0; background: transparent; border-radius: 8px; font: inherit; font-size: 13.5px; color: var(--text-mid); cursor: pointer; }
.menu-item:hover { background: var(--surface-2); color: var(--text); }
.menu-item.logout { color: var(--danger); }

.main { max-width: 1200px; margin: 0 auto; padding: 28px 24px 80px; }
.main.login { max-width: none; padding: 0; }

/* ── shared primitives ── */
.btn { font: inherit; font-size: 14px; padding: 9px 16px; border-radius: var(--radius-btn); cursor: pointer; border: 1px solid var(--border-strong); background: var(--bg-elev); color: var(--text); font-weight: 500; transition: transform .12s var(--ease), background .15s, border-color .15s, box-shadow .15s; display: inline-flex; align-items: center; gap: 6px; }
.btn:hover { background: var(--surface-2); border-color: var(--border-strong); }
.btn:active { transform: translateY(1px); }
.btn:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }
.btn:disabled { opacity: .5; cursor: not-allowed; }
.btn.primary { background: var(--accent); border-color: var(--accent); color: var(--accent-fg); }
.btn.primary:hover { background: var(--accent-strong); border-color: var(--accent-strong); }
.btn.ghost { border: 0; background: transparent; color: var(--text-mid); }
.btn.ghost:hover { background: var(--surface-2); color: var(--text); }
.btn.danger { color: var(--danger); border-color: color-mix(in srgb, var(--danger) 30%, var(--border)); }
.btn.danger:hover { background: var(--danger-soft); }

.label { display: block; font-size: 13px; color: var(--text-mid); margin-bottom: 6px; font-weight: 500; }
.input, .textarea, .select { font: inherit; padding: 11px 14px; border: 1px solid var(--border-strong); border-radius: var(--radius-btn); background: var(--bg-elev); color: var(--text); transition: border-color .15s, box-shadow .15s; width: 100%; }
.input:focus, .textarea:focus, .select:focus { outline: none; border-color: var(--accent); box-shadow: 0 0 0 3px color-mix(in srgb, var(--accent) 18%, transparent); }
.textarea { resize: vertical; line-height: 1.6; }
.field-error { color: var(--danger); font-size: 12.5px; margin-top: 6px; }

.badge { font-size: 12px; padding: 3px 10px; border-radius: var(--radius-pill); font-weight: 600; }
.badge.blue { background: var(--accent-soft); color: var(--accent); }
.badge.gray { background: var(--surface-2); color: var(--text-mid); }
.badge.green { background: var(--success-soft); color: var(--success); }
.badge.amber { background: var(--warn-soft); color: var(--warn); }
.banner { border-radius: 10px; padding: 10px 14px; font-size: 13.5px; margin-bottom: 16px; }
.banner.error { background: var(--danger-soft); color: var(--danger); border: 1px solid color-mix(in srgb, var(--danger) 24%, transparent); }
.banner.success { background: var(--success-soft); color: var(--success); border: 1px solid color-mix(in srgb, var(--success) 24%, transparent); }

.section-title { font-size: 13px; color: var(--text-faint); text-transform: uppercase; letter-spacing: .07em; margin: 20px 0 12px; font-weight: 600; }
.section-title em { color: var(--accent); font-style: normal; }
.muted { color: var(--text-mid); }
.faint { color: var(--text-faint); }
code { background: var(--surface-2); border-radius: 6px; padding: 2px 7px; font-size: 12.5px; color: var(--text-mid); }
.empty { text-align: center; padding: 64px 24px; }
.empty .e-icon { font-size: 40px; margin-bottom: 12px; }
.skeleton { border-radius: var(--radius-card); min-height: 120px; }

@media (prefers-reduced-motion: reduce) { * { animation-duration: .001ms !important; transition-duration: .001ms !important; } }
</style>
