<script setup lang="ts">
import { onMounted, ref } from "vue"
import { useRouter } from "vue-router"
import { useAuthStore } from "../stores/auth"
import { useThemeStore } from "../stores/theme"
import { t } from "../i18n"

const router = useRouter()
const auth = useAuthStore()
const theme = useThemeStore()

const username = ref("")
const password = ref("")
const submitting = ref(false)
const formError = ref<string | null>(null)

onMounted(() => {
  // If the user landed on /login while already authenticated
  // (e.g. typed the URL after a refresh), bounce them to chat.
  if (auth.isAuthenticated) {
    void router.replace("/chat")
  }
})

async function submit() {
  formError.value = null
  if (!username.value.trim() || !password.value) {
    formError.value = t("login.errorMissing")
    return
  }
  submitting.value = true
  try {
    await auth.login(username.value.trim(), password.value)
    // Navigate to the chat view; router guard will let us through
    // because we're now authenticated.
    await router.push("/chat")
  } catch (e) {
    // Backend returned 401 for bad credentials, or some other error.
    // The store already cleared the error after the throw; surface a
    // user-readable message without leaking server detail.
    formError.value = t("login.failed")
  } finally {
    submitting.value = false
    password.value = ""
  }
}
</script>

<template>
  <div class="login-shell">
    <!-- Five ribbons that snake across the viewport as a single
         regular weave. Each is a stroked path: stroke-width (90)
         extends the same distance along the normal at every point
         of the curve, so band width is mathematically constant
         along the entire length — no thin spots at the crests.
         Each wave is a TRUE sine with a rounded crest: one
         480-unit period is built from eight 60-unit Hermite
         segments whose endpoints carry the analytic sine slope
         (dy/dx = 2*pi*A/lambda * cos). At the crest (x=120) and
         trough (x=360) the slope is exactly 0, so the peak is
         horizontal and smooth — no sharp corner (the previous
         quarter-period kappa hack put the crest on a segment
         boundary with a 29deg tangent jump, hence the spike).
         The curve actually reaches the 52-unit amplitude, is
         symmetric, and matches sin(x) to within O(60^3). Pitch
         is 180 (band width 90 + gap 90 — gap equals band width). Every ribbon shares the
         same template with its own y-centre at an equal 180-unit
         gap, and all are perfectly in phase, so every crest and
         trough sits on the same vertical line. The viewBox is
         1920x1080 and preserveAspectRatio is "xMidYMid slice":
         the SVG scales uniformly (stroke width stays constant at
         every point, regardless of window aspect — the old
         "none" mode stretched non-uniformly on any non-16:9
         window, making the band look thicker in some spots) and
         excess is cropped from the sides. Wavelength 480 units
         (~720px, 2.67 full waves on screen), max slope ~30deg.
         The stage is tilted -15deg and the whole aligned stack
         slides sideways on a shared 14s loop. -->
    <div class="ribbon-bg" aria-hidden="true">
      <div class="ribbon-stage">
        <svg
          class="ribbon ribbon--white"
          viewBox="0 0 1920 1080"
          preserveAspectRatio="xMidYMid slice"
          xmlns="http://www.w3.org/2000/svg"
        >
          <path
            d="M0,150.0 C20.0,163.62 40.0,177.15 60,186.77 C80.0,196.39 100.0,202.0 120,202.0 C140.0,202.0 160.0,196.39 180,186.77 C200.0,177.15 220.0,163.62 240,150.0 C260.0,136.38 280.0,122.85 300,113.23 C320.0,103.61 340.0,98.0 360,98.0 C380.0,98.0 400.0,103.61 420,113.23 C440.0,122.85 460.0,136.38 480,150.0 C500.0,163.62 520.0,177.15 540,186.77 C560.0,196.39 580.0,202.0 600,202.0 C620.0,202.0 640.0,196.39 660,186.77 C680.0,177.15 700.0,163.62 720,150.0 C740.0,136.38 760.0,122.85 780,113.23 C800.0,103.61 820.0,98.0 840,98.0 C860.0,98.0 880.0,103.61 900,113.23 C920.0,122.85 940.0,136.38 960,150.0 C980.0,163.62 1000.0,177.15 1020,186.77 C1040.0,196.39 1060.0,202.0 1080,202.0 C1100.0,202.0 1120.0,196.39 1140,186.77 C1160.0,177.15 1180.0,163.62 1200,150.0 C1220.0,136.38 1240.0,122.85 1260,113.23 C1280.0,103.61 1300.0,98.0 1320,98.0 C1340.0,98.0 1360.0,103.61 1380,113.23 C1400.0,122.85 1420.0,136.38 1440,150.0 C1460.0,163.62 1480.0,177.15 1500,186.77 C1520.0,196.39 1540.0,202.0 1560,202.0 C1580.0,202.0 1600.0,196.39 1620,186.77 C1640.0,177.15 1660.0,163.62 1680,150.0 C1700.0,136.38 1720.0,122.85 1740,113.23 C1760.0,103.61 1780.0,98.0 1800,98.0 C1820.0,98.0 1840.0,103.61 1860,113.23 C1880.0,122.85 1900.0,136.38 1920,150.0"
            fill="none"
            stroke="#ffffff"
            stroke-width="90"
          />
        </svg>
        <svg
          class="ribbon ribbon--pink"
          viewBox="0 0 1920 1080"
          preserveAspectRatio="xMidYMid slice"
          xmlns="http://www.w3.org/2000/svg"
        >
          <path
            d="M0,330.0 C20.0,343.62 40.0,357.15 60,366.77 C80.0,376.39 100.0,382.0 120,382.0 C140.0,382.0 160.0,376.39 180,366.77 C200.0,357.15 220.0,343.62 240,330.0 C260.0,316.38 280.0,302.85 300,293.23 C320.0,283.61 340.0,278.0 360,278.0 C380.0,278.0 400.0,283.61 420,293.23 C440.0,302.85 460.0,316.38 480,330.0 C500.0,343.62 520.0,357.15 540,366.77 C560.0,376.39 580.0,382.0 600,382.0 C620.0,382.0 640.0,376.39 660,366.77 C680.0,357.15 700.0,343.62 720,330.0 C740.0,316.38 760.0,302.85 780,293.23 C800.0,283.61 820.0,278.0 840,278.0 C860.0,278.0 880.0,283.61 900,293.23 C920.0,302.85 940.0,316.38 960,330.0 C980.0,343.62 1000.0,357.15 1020,366.77 C1040.0,376.39 1060.0,382.0 1080,382.0 C1100.0,382.0 1120.0,376.39 1140,366.77 C1160.0,357.15 1180.0,343.62 1200,330.0 C1220.0,316.38 1240.0,302.85 1260,293.23 C1280.0,283.61 1300.0,278.0 1320,278.0 C1340.0,278.0 1360.0,283.61 1380,293.23 C1400.0,302.85 1420.0,316.38 1440,330.0 C1460.0,343.62 1480.0,357.15 1500,366.77 C1520.0,376.39 1540.0,382.0 1560,382.0 C1580.0,382.0 1600.0,376.39 1620,366.77 C1640.0,357.15 1660.0,343.62 1680,330.0 C1700.0,316.38 1720.0,302.85 1740,293.23 C1760.0,283.61 1780.0,278.0 1800,278.0 C1820.0,278.0 1840.0,283.61 1860,293.23 C1880.0,302.85 1900.0,316.38 1920,330.0"
            fill="none"
            stroke="#fa66e4"
            stroke-width="90"
          />
        </svg>
        <svg
          class="ribbon ribbon--blue"
          viewBox="0 0 1920 1080"
          preserveAspectRatio="xMidYMid slice"
          xmlns="http://www.w3.org/2000/svg"
        >
          <path
            d="M0,510.0 C20.0,523.62 40.0,537.15 60,546.77 C80.0,556.39 100.0,562.0 120,562.0 C140.0,562.0 160.0,556.39 180,546.77 C200.0,537.15 220.0,523.62 240,510.0 C260.0,496.38 280.0,482.85 300,473.23 C320.0,463.61 340.0,458.0 360,458.0 C380.0,458.0 400.0,463.61 420,473.23 C440.0,482.85 460.0,496.38 480,510.0 C500.0,523.62 520.0,537.15 540,546.77 C560.0,556.39 580.0,562.0 600,562.0 C620.0,562.0 640.0,556.39 660,546.77 C680.0,537.15 700.0,523.62 720,510.0 C740.0,496.38 760.0,482.85 780,473.23 C800.0,463.61 820.0,458.0 840,458.0 C860.0,458.0 880.0,463.61 900,473.23 C920.0,482.85 940.0,496.38 960,510.0 C980.0,523.62 1000.0,537.15 1020,546.77 C1040.0,556.39 1060.0,562.0 1080,562.0 C1100.0,562.0 1120.0,556.39 1140,546.77 C1160.0,537.15 1180.0,523.62 1200,510.0 C1220.0,496.38 1240.0,482.85 1260,473.23 C1280.0,463.61 1300.0,458.0 1320,458.0 C1340.0,458.0 1360.0,463.61 1380,473.23 C1400.0,482.85 1420.0,496.38 1440,510.0 C1460.0,523.62 1480.0,537.15 1500,546.77 C1520.0,556.39 1540.0,562.0 1560,562.0 C1580.0,562.0 1600.0,556.39 1620,546.77 C1640.0,537.15 1660.0,523.62 1680,510.0 C1700.0,496.38 1720.0,482.85 1740,473.23 C1760.0,463.61 1780.0,458.0 1800,458.0 C1820.0,458.0 1840.0,463.61 1860,473.23 C1880.0,482.85 1900.0,496.38 1920,510.0"
            fill="none"
            stroke="#2563eb"
            stroke-width="90"
          />
        </svg>
        <svg
          class="ribbon ribbon--orange"
          viewBox="0 0 1920 1080"
          preserveAspectRatio="xMidYMid slice"
          xmlns="http://www.w3.org/2000/svg"
        >
          <path
            d="M0,690.0 C20.0,703.62 40.0,717.15 60,726.77 C80.0,736.39 100.0,742.0 120,742.0 C140.0,742.0 160.0,736.39 180,726.77 C200.0,717.15 220.0,703.62 240,690.0 C260.0,676.38 280.0,662.85 300,653.23 C320.0,643.61 340.0,638.0 360,638.0 C380.0,638.0 400.0,643.61 420,653.23 C440.0,662.85 460.0,676.38 480,690.0 C500.0,703.62 520.0,717.15 540,726.77 C560.0,736.39 580.0,742.0 600,742.0 C620.0,742.0 640.0,736.39 660,726.77 C680.0,717.15 700.0,703.62 720,690.0 C740.0,676.38 760.0,662.85 780,653.23 C800.0,643.61 820.0,638.0 840,638.0 C860.0,638.0 880.0,643.61 900,653.23 C920.0,662.85 940.0,676.38 960,690.0 C980.0,703.62 1000.0,717.15 1020,726.77 C1040.0,736.39 1060.0,742.0 1080,742.0 C1100.0,742.0 1120.0,736.39 1140,726.77 C1160.0,717.15 1180.0,703.62 1200,690.0 C1220.0,676.38 1240.0,662.85 1260,653.23 C1280.0,643.61 1300.0,638.0 1320,638.0 C1340.0,638.0 1360.0,643.61 1380,653.23 C1400.0,662.85 1420.0,676.38 1440,690.0 C1460.0,703.62 1480.0,717.15 1500,726.77 C1520.0,736.39 1540.0,742.0 1560,742.0 C1580.0,742.0 1600.0,736.39 1620,726.77 C1640.0,717.15 1660.0,703.62 1680,690.0 C1700.0,676.38 1720.0,662.85 1740,653.23 C1760.0,643.61 1780.0,638.0 1800,638.0 C1820.0,638.0 1840.0,643.61 1860,653.23 C1880.0,662.85 1900.0,676.38 1920,690.0"
            fill="none"
            stroke="#f4840c"
            stroke-width="90"
          />
        </svg>
        <svg
          class="ribbon ribbon--cyan"
          viewBox="0 0 1920 1080"
          preserveAspectRatio="xMidYMid slice"
          xmlns="http://www.w3.org/2000/svg"
        >
          <path
            d="M0,870.0 C20.0,883.62 40.0,897.15 60,906.77 C80.0,916.39 100.0,922.0 120,922.0 C140.0,922.0 160.0,916.39 180,906.77 C200.0,897.15 220.0,883.62 240,870.0 C260.0,856.38 280.0,842.85 300,833.23 C320.0,823.61 340.0,818.0 360,818.0 C380.0,818.0 400.0,823.61 420,833.23 C440.0,842.85 460.0,856.38 480,870.0 C500.0,883.62 520.0,897.15 540,906.77 C560.0,916.39 580.0,922.0 600,922.0 C620.0,922.0 640.0,916.39 660,906.77 C680.0,897.15 700.0,883.62 720,870.0 C740.0,856.38 760.0,842.85 780,833.23 C800.0,823.61 820.0,818.0 840,818.0 C860.0,818.0 880.0,823.61 900,833.23 C920.0,842.85 940.0,856.38 960,870.0 C980.0,883.62 1000.0,897.15 1020,906.77 C1040.0,916.39 1060.0,922.0 1080,922.0 C1100.0,922.0 1120.0,916.39 1140,906.77 C1160.0,897.15 1180.0,883.62 1200,870.0 C1220.0,856.38 1240.0,842.85 1260,833.23 C1280.0,823.61 1300.0,818.0 1320,818.0 C1340.0,818.0 1360.0,823.61 1380,833.23 C1400.0,842.85 1420.0,856.38 1440,870.0 C1460.0,883.62 1480.0,897.15 1500,906.77 C1520.0,916.39 1540.0,922.0 1560,922.0 C1580.0,922.0 1600.0,916.39 1620,906.77 C1640.0,897.15 1660.0,883.62 1680,870.0 C1700.0,856.38 1720.0,842.85 1740,833.23 C1760.0,823.61 1780.0,818.0 1800,818.0 C1820.0,818.0 1840.0,823.61 1860,833.23 C1880.0,842.85 1900.0,856.38 1920,870.0"
            fill="none"
            stroke="#54bcce"
            stroke-width="90"
          />
        </svg>
      </div>
    </div>

    <!-- Theme toggle — top-right of the viewport, frosted glass
         pill. Icon swaps based on active theme. -->
    <button
      class="theme-toggle"
      type="button"
      :aria-label="t('login.toggleTheme')"
      @click="theme.toggle()"
    >
      <svg
        v-if="theme.theme === 'dark'"
        viewBox="0 0 24 24"
        xmlns="http://www.w3.org/2000/svg"
        aria-hidden="true"
      >
        <!-- sun -->
        <circle cx="12" cy="12" r="4.5" fill="currentColor" />
        <g stroke="currentColor" stroke-width="1.8" stroke-linecap="round">
          <line x1="12" y1="2.5" x2="12" y2="5.5" />
          <line x1="12" y1="18.5" x2="12" y2="21.5" />
          <line x1="2.5" y1="12" x2="5.5" y2="12" />
          <line x1="18.5" y1="12" x2="21.5" y2="12" />
          <line x1="5.2" y1="5.2" x2="7.3" y2="7.3" />
          <line x1="16.7" y1="16.7" x2="18.8" y2="18.8" />
          <line x1="5.2" y1="18.8" x2="7.3" y2="16.7" />
          <line x1="16.7" y1="7.3" x2="18.8" y2="5.2" />
        </g>
      </svg>
      <svg
        v-else
        viewBox="0 0 24 24"
        xmlns="http://www.w3.org/2000/svg"
        aria-hidden="true"
      >
        <!-- moon -->
        <path
          d="M21.5 12.6A9.5 9.5 0 0 1 11.4 2.5 7.5 7.5 0 1 0 21.5 12.6Z"
          fill="currentColor"
        />
      </svg>
    </button>

    <form class="card" @submit.prevent="submit">
      <div class="brand">
        <img class="logo" src="/brand.svg" alt="" />
        <span class="brand-name">{{ t("login.brand") }}</span>
      </div>
      <h1 class="title">{{ t("login.title") }}</h1>

      <label class="field">
        <span class="field-label">{{ t("login.username") }}</span>
        <input
          v-model="username"
          class="field-input"
          type="text"
          name="username"
          autocomplete="username"
          autocapitalize="off"
          spellcheck="false"
          :disabled="submitting"
        />
      </label>

      <label class="field">
        <span class="field-label">{{ t("login.password") }}</span>
        <input
          v-model="password"
          class="field-input"
          type="password"
          name="password"
          autocomplete="current-password"
          :disabled="submitting"
        />
      </label>

      <div v-if="formError" class="error" role="alert">{{ formError }}</div>

      <button
        class="submit"
        type="submit"
        :disabled="submitting"
      >
        {{ submitting ? t("login.submitting") : t("login.submit") }}
      </button>
    </form>
  </div>
</template>

<style scoped>
/* ── Shell ────────────────────────────────────────────────────────
   Solid colour per theme. The wavy ribbon layer sits between
   the bg and the card. */

.login-shell {
  position: relative;
  display: flex;
  align-items: center;
  justify-content: center;
  height: 100%;
  width: 100%;
  overflow: hidden;
  padding: 24px;
  background: var(--login-shell-bg);
  color: var(--login-shell-fg);
  transition:
    background-color 240ms ease,
    color 240ms ease;
}

/* ── Wavy ribbon backdrop ───────────────────────────────────────
   Five SVG ribbons, each stroked with one saturated logo colour,
   all sharing the exact same bezier shape so every wave lines
   up and the vertical gaps are identical. The stage tilts the
   whole weave -7deg; each ribbon runs the same 30s loop with a
   staggered delay so the aligned geometry stays intact while
   the weave flows sideways. */

.ribbon-bg {
  position: absolute;
  inset: 0;
  pointer-events: none;
  z-index: 0;
  overflow: hidden;
}

/* Oversized stage that gets tilted. At 15deg the rotated rectangle
   needs roughly 25% extra on each side before it stops exposing
   corners of the shell, hence the 150%/150% size. */
.ribbon-stage {
  position: absolute;
  left: -25%;
  top: -25%;
  width: 150%;
  height: 150%;
  transform: rotate(-15deg);
}

.ribbon {
  position: absolute;
  left: 0;
  top: 0;
  width: 200%;
  height: 100%;
  /* All five ribbons share the exact same delay (0) and duration,
     so they are perfectly in phase forever: every crest and every
     trough of every band sits on the same vertical line, and the
     gaps between bands stay identical. The whole aligned stack
     then slides sideways as one unit — the flow the user wants,
     with zero disorder. Each ribbon is a stroked path, so the
     stroke-width (90) guarantees uniform band width along its
     entire length. 14s keeps the flow lively. */
  animation: ribbon-flow 14s linear infinite;
  will-change: transform;
}

@keyframes ribbon-flow {
  from {
    transform: translateX(0);
  }
  to {
    /* Exactly one 960-unit period of the 1920-unit viewBox. The
       path repeats identically every 960 units, so this loop is
       seamless. */
    transform: translateX(-50%);
  }
}

/* ── Theme toggle ─────────────────────────────────────────────────
   Frosted glass pill pinned to the top-right. Icon is strictly
   centred via flex + display:block on the SVG. */

.theme-toggle {
  position: absolute;
  top: 18px;
  right: 18px;
  z-index: 2;
  width: 38px;
  height: 38px;
  display: flex;
  align-items: center;
  justify-content: center;
  border: 1px solid var(--login-toggle-border);
  border-radius: 999px;
  background: var(--login-toggle-bg);
  color: var(--login-toggle-fg);
  cursor: pointer;
  backdrop-filter: blur(10px) saturate(160%);
  -webkit-backdrop-filter: blur(10px) saturate(160%);
  box-shadow: 0 4px 14px var(--login-toggle-shadow);
  transition:
    transform 160ms ease,
    background-color 200ms ease,
    border-color 200ms ease,
    color 200ms ease;
}
.theme-toggle svg {
  display: block;
  flex-shrink: 0;
  width: 20px;
  height: 20px;
}
.theme-toggle:hover {
  transform: translateY(-1px);
}
.theme-toggle:active {
  transform: translateY(0);
}
.theme-toggle:focus-visible {
  outline: 2px solid var(--brand);
  outline-offset: 2px;
}

/* ── Card ─────────────────────────────────────────────────────────
   Frosted glass so the ribbon backdrop is hinted at the edges
   without hurting readability. */

.card {
  position: relative;
  z-index: 1;
  width: min(360px, 100%);
  display: flex;
  flex-direction: column;
  gap: 14px;
  padding: 28px;
  border: 1px solid var(--login-card-border);
  border-radius: 14px;
  background: var(--login-card-bg);
  color: var(--login-card-fg);
  backdrop-filter: blur(18px) saturate(160%);
  -webkit-backdrop-filter: blur(18px) saturate(160%);
  box-shadow: var(--login-card-shadow);
  transition:
    background-color 240ms ease,
    border-color 240ms ease,
    color 240ms ease,
    box-shadow 240ms ease;
}

.brand {
  display: flex;
  align-items: center;
  gap: 8px;
  font-weight: 600;
  color: inherit;
  margin-bottom: 4px;
}
.logo {
  width: 22px;
  height: 22px;
  display: block;
  border-radius: 5px;
}
.brand-name {
  font-size: 14px;
}

.title {
  font-size: 18px;
  font-weight: 600;
  color: inherit;
  margin: 0 0 4px;
}

.field {
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.field-label {
  font-size: 12px;
  color: var(--text-mid);
  font-weight: 500;
}
.field-input {
  font: inherit;
  padding: 9px 11px;
  border: 1px solid var(--login-input-border);
  border-radius: 6px;
  background: var(--login-input-bg);
  color: var(--login-input-fg);
  outline: none;
  transition:
    border-color 120ms ease,
    box-shadow 120ms ease,
    background-color 200ms ease,
    color 200ms ease;
}
.field-input::placeholder {
  color: var(--text-faint);
}
.field-input:focus {
  border-color: var(--brand);
  box-shadow: 0 0 0 3px var(--login-input-focus-ring);
}
.field-input:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

.error {
  font-size: 12px;
  color: var(--danger);
  background: var(--danger-bg);
  border: 1px solid var(--danger-border);
  padding: 6px 10px;
  border-radius: 6px;
}

.submit {
  font: inherit;
  font-weight: 600;
  font-size: 13px;
  padding: 9px 12px;
  border: 0;
  border-radius: 6px;
  background: var(--brand);
  color: #ffffff;
  cursor: pointer;
  transition:
    background-color 120ms ease,
    opacity 120ms ease,
    transform 120ms ease;
}
.submit:hover:not(:disabled) {
  background: var(--brand-hover);
}
.submit:active:not(:disabled) {
  transform: translateY(1px);
}
.submit:disabled {
  opacity: 0.6;
  cursor: progress;
}

/* ── Theme palettes ──────────────────────────────────────────────
   Light theme: warm off-white shell, dark text on translucent
   white card. The ribbons are vivid but slightly tamed so they
   don't fight the light surface.

   Dark theme: deep navy shell, light text on translucent dark
   card. Ribbons run at nearly full opacity — pure white plus
   pure saturated logo colours. */

:root[data-theme="light"] .login-shell {
  --login-shell-bg: #f3f5f9;
  --login-shell-fg: #0f172a;
  --login-card-bg: rgba(255, 255, 255, 0.78);
  --login-card-border: rgba(15, 23, 42, 0.08);
  --login-card-fg: #0f172a;
  --login-card-shadow:
    0 10px 36px rgba(15, 23, 42, 0.10),
    0 0 0 1px rgba(15, 23, 42, 0.04) inset;
  --login-input-bg: rgba(255, 255, 255, 0.85);
  --login-input-border: rgba(15, 23, 42, 0.14);
  --login-input-fg: #0f172a;
  --login-input-focus-ring: rgba(37, 99, 235, 0.18);
  --login-toggle-bg: rgba(255, 255, 255, 0.7);
  --login-toggle-border: rgba(15, 23, 42, 0.12);
  --login-toggle-fg: #0f172a;
  --login-toggle-shadow: rgba(15, 23, 42, 0.08);
}
:root[data-theme="light"] .ribbon {
  /* Vivid but slightly tamed on the light shell so the card stays
     readable; still far bolder than the old 0.22 slashes. */
  opacity: 0.85;
}
:root[data-theme="light"] .ribbon--white {
  opacity: 1;
}

:root[data-theme="dark"] .login-shell {
  --login-shell-bg: #03040a;
  --login-shell-fg: #f3f4f6;
  --login-card-bg: rgba(11, 15, 26, 0.62);
  --login-card-border: rgba(255, 255, 255, 0.08);
  --login-card-fg: #f3f4f6;
  --login-card-shadow:
    0 10px 36px rgba(0, 0, 0, 0.55),
    0 0 0 1px rgba(255, 255, 255, 0.04) inset;
  --login-input-bg: rgba(11, 15, 26, 0.55);
  --login-input-border: rgba(255, 255, 255, 0.14);
  --login-input-fg: #f3f4f6;
  --login-input-focus-ring: rgba(96, 165, 250, 0.28);
  --login-toggle-bg: rgba(11, 15, 26, 0.62);
  --login-toggle-border: rgba(255, 255, 255, 0.12);
  --login-toggle-fg: #f3f4f6;
  --login-toggle-shadow: rgba(0, 0, 0, 0.45);
}
:root[data-theme="dark"] .ribbon {
  /* User asked for pure / nearly-pure colours — these are as bold
     as they get without burying the frosted card. */
  opacity: 0.95;
}
:root[data-theme="dark"] .ribbon--white {
  opacity: 1;
}

/* Respect users who've asked the OS for less motion. */
@media (prefers-reduced-motion: reduce) {
  .ribbon {
    animation: none;
  }
  .theme-toggle,
  .submit {
    transition: none;
  }
}
</style>
