<script setup lang="ts">
import { ref } from "vue"
import { useRouter } from "vue-router"
import { api } from "../api/client"
import { saveToken } from "../api/auth"
import { t } from "../i18n"

const router = useRouter()
const username = ref("")
const password = ref("")
const error = ref("")
const fieldError = ref("")
const loading = ref(false)

async function submit() {
  error.value = ""
  fieldError.value = username.value.trim() ? "" : t("login.usernameReq")
  if (!username.value.trim()) return
  loading.value = true
  try {
    const { token, username: u } = await api.login(username.value.trim(), password.value)
    saveToken(token, u)
    router.push({ name: "market" })
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e)
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <div class="auth">
    <!-- brand panel -->
    <aside class="auth-brand">
      <div class="brand-badge"><span>{{ t("market.title") }}</span></div>
      <div class="brand-hero">
        <p class="kicker">{{ t("login.kicker") }}</p>
        <h1>{{ t("login.hero") }}</h1>
        <p class="sub">{{ t("login.subtext") }}</p>
      </div>
      <ul class="perks">
        <li>{{ t("login.perk1") }}</li>
        <li>{{ t("login.perk2") }}</li>
        <li>{{ t("login.perk3") }}</li>
      </ul>
    </aside>

    <!-- form panel -->
    <main class="auth-form">
      <form class="form-card" @submit.prevent="submit">
        <h2>{{ t("login.title") }}</h2>
        <p class="muted">{{ t("login.sub") }}</p>

        <label class="field">
          <span class="label">{{ t("login.username") }}</span>
          <input v-model="username" class="input" autocomplete="username" placeholder="" />
          <p v-if="fieldError" class="field-error">{{ fieldError }}</p>
        </label>
        <label class="field">
          <span class="label">{{ t("login.password") }}</span>
          <input v-model="password" type="password" class="input" autocomplete="current-password" placeholder="" />
        </label>

        <p v-if="error" class="banner error">{{ error }}</p>

        <button class="btn primary login-btn" :disabled="loading || !username.trim()" type="submit">
          {{ loading ? t("login.loading") : t("login.submit") }}
        </button>

        <div class="demo-hint">
          <span class="faint">{{ t("login.demo") }}</span>
          <code>alice / wonderland</code> · <code>bob / builder</code> · <code>demo / demo</code>
        </div>
      </form>
    </main>
  </div>
</template>

<style scoped>
.auth { display: grid; grid-template-columns: 1.1fr 1fr; min-height: 100dvh; }
.auth-brand {
  background:
    radial-gradient(120% 120% at 20% 10%, color-mix(in srgb, var(--accent) 40%, transparent), transparent 60%),
    linear-gradient(160deg, #1a2133, #0c1017);
  color: #eef2f9;
  padding: 48px 56px;
  display: flex;
  flex-direction: column;
  justify-content: space-between;
}
.brand-badge { display: flex; align-items: center; gap: 10px; font-weight: 700; font-size: 17px; letter-spacing: -0.01em; }
.brand-hero { margin: 40px 0; }
.kicker { font-size: 12px; letter-spacing: .18em; color: var(--accent); font-weight: 600; margin: 0 0 16px; text-transform: uppercase; }
.brand-hero h1 { font-size: 42px; line-height: 1.12; letter-spacing: -0.03em; margin: 0 0 20px; white-space: pre-line; }
.brand-hero h1 .hl { background: linear-gradient(90deg, var(--accent), #a78bfa); -webkit-background-clip: text; background-clip: text; color: transparent; }
.brand-hero .sub { color: #a9b3c4; font-size: 16px; max-width: 380px; line-height: 1.6; margin: 0; }
.perks { list-style: none; padding: 0; margin: 0; display: grid; gap: 14px; }
.perks li { font-size: 14.5px; color: #d5dae4; }

.auth-form { display: grid; place-items: center; padding: 40px 24px; }
.form-card { width: 100%; max-width: 360px; display: flex; flex-direction: column; gap: 6px; }
.form-card h2 { font-size: 24px; margin: 0 0 2px; }
.form-card > .muted { font-size: 14px; margin: 0 0 22px; }
.field { margin-bottom: 16px; }
.login-btn { margin-top: 8px; justify-content: center; font-size: 15px; padding: 12px; }
.demo-hint { margin-top: 24px; font-size: 12.5px; text-align: center; }
.demo-hint code { margin: 0 2px; }

@media (max-width: 900px) {
  .auth { grid-template-columns: 1fr; }
  .auth-brand { display: none; }
}
</style>
