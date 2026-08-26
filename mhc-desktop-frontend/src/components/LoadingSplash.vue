<!--
  LoadingSplash.vue

  Full-window overlay shown while the bundled Python backend is still
  booting. The Electron host spawns the backend as a child process and
  can take 30–90 seconds on a fresh Win11 install (AV scan + cold
  caches). Without this splash the user would double-click the exe,
  see nothing happen, and click again — spawning multiple processes
  that fight over port 8765.

  Visual: the same gem logo from the left sidebar (so the splash looks
  like the app, not a stock "loading…" animation), centred, with a
  soft pulse + a rotating ring, plus the user-customisable app title
  and a "Loading…" hint. Cross-fades to the main shell once the
  backend answers /api/v1/health.
-->

<script setup lang="ts">
import { computed } from "vue"
import { useAppMetaStore } from "../stores/appMeta"
import { useThemeStore } from "../stores/theme"
import { t } from "../i18n"
// Vite turns the public/brand.svg into a hashed asset under dist/.
// The ``?url`` suffix returns the resolved URL string so we get a
// path that works regardless of whether the app is loaded from the
// dev server, the bundled file:// index.html, or the backend's HTTP
// origin (vite copies public/ to dist/ at build time, and the
// bundled backend serves the same dist/ files).
import brandUrl from "/brand.svg?url"

const appMeta = useAppMetaStore()
const theme = useThemeStore()

const titleText = computed(() => appMeta.title)
const themeName = computed(() => theme.theme)

defineProps<{
  /** Optional one-line context, e.g. "正在退出…" for the exit overlay. */
  hint?: string
}>()
</script>

<template>
  <div class="splash" :data-theme="themeName">
    <div class="center">
      <div class="logo-wrap">
        <img class="logo" :src="brandUrl" alt="" />
        <div class="ring" aria-hidden="true"></div>
      </div>
      <div class="title">{{ titleText }}</div>
      <div class="msg">
        {{ hint || t("splash.loading") }}
      </div>
    </div>
  </div>
</template>

<style scoped>
.splash {
  position: fixed;
  inset: 0;
  display: grid;
  place-items: center;
  background: var(--bg);
  color: var(--text);
  z-index: 9999;
  /* Smooth out the transition out: 250 ms fade-out is short enough
     that the user doesn't notice the underlying shell "snap in",
     but long enough to avoid a jarring flash when the backend was
     already up. */
  transition: opacity 250ms ease-out;
}
.splash.fading {
  opacity: 0;
  pointer-events: none;
}

.center {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 18px;
  user-select: none;
}

.logo-wrap {
  position: relative;
  width: 64px;
  height: 64px;
  display: grid;
  place-items: center;
}

.logo {
  width: 56px;
  height: 56px;
  /* Soft pulse to mirror the brand mark alive (not just "Loading…"). */
  animation: splash-pulse 2.4s ease-in-out infinite;
}

.ring {
  position: absolute;
  inset: -4px;
  border-radius: 50%;
  border: 2px solid transparent;
  border-top-color: var(--brand, #2563eb);
  border-right-color: color-mix(in srgb, var(--brand, #2563eb) 35%, transparent);
  animation: splash-spin 1.4s linear infinite;
}

.title {
  font-size: 20px;
  font-weight: 600;
  letter-spacing: 0.02em;
}

.msg {
  font-size: 13px;
  color: var(--text-faint);
  display: flex;
  align-items: center;
  gap: 8px;
}

.msg::before {
  content: "";
  display: inline-block;
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: currentColor;
  opacity: 0.6;
  animation: splash-dot 1.4s ease-in-out infinite;
}

@keyframes splash-pulse {
  0%, 100% { opacity: 0.85; transform: scale(1); }
  50%      { opacity: 1;    transform: scale(1.04); }
}

@keyframes splash-spin {
  to { transform: rotate(360deg); }
}

@keyframes splash-dot {
  0%, 100% { opacity: 0.35; }
  50%      { opacity: 0.95; }
}
</style>