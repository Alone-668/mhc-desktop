<script setup lang="ts">
import { onMounted, ref } from "vue"
import { useProvidersStore } from "../stores/providers"
import ProviderForm from "../components/ProviderForm.vue"
import type { Provider } from "../api/client"
import { ask } from "../lib/confirm"
import { t } from "../i18n"

// "Models" is the page the user lands on to configure which LLMs
// they can talk to. The actual data is providers (each carries a
// list of models); we surface that as a "Service providers" sub-
// section so the primary unit on this page is the model.

const store = useProvidersStore()

const adding = ref(false)
const editing = ref<Provider | null>(null)
const toggling = ref<string | null>(null)
const importError = ref<string | null>(null)

onMounted(() => {
  store.refresh()
})

async function onCreated(_p: Provider) {
  adding.value = false
  editing.value = null
  await store.refresh()
}

async function removeProvider(name: string) {
  const ok = await ask({
    title: t("models.confirmDeleteProviderTitle"),
    message: t("common.confirmDeleteProvider", { name }),
    tone: "danger",
    confirmLabel: t("common.delete"),
  })
  if (!ok) return
  try {
    await store.remove(name)
  } catch (e) {
    importError.value = e instanceof Error ? e.message : String(e)
  }
}

function editProvider(p: Provider) {
  adding.value = false
  editing.value = p
}

async function toggle(p: Provider) {
  if (toggling.value) return
  toggling.value = p.name
  try {
    await store.setEnabled(p.name, !(p.enabled !== false))
  } catch (e) {
    alert(e instanceof Error ? e.message : String(e))
  } finally {
    toggling.value = null
  }
}

function isOn(p: Provider): boolean {
  return p.enabled !== false
}
</script>

<template>
  <section class="page">
    <header class="head">
      <h2>{{ t("models.title") }}</h2>
      <button class="btn-primary" @click="adding = true">
        {{ t("models.addProvider") }}
      </button>
    </header>

    <p class="hint">{{ t("models.hint") }}</p>

    <h3 class="section-h">{{ t("models.providerSection") }}</h3>

    <div
      v-if="store.loading && store.items.length === 0"
      class="loading"
    >
      {{ t("common.loading") }}
    </div>
    <p v-if="importError" class="error">{{ importError }}</p>
    <p v-else-if="store.error" class="error">{{ store.error }}</p>
    <p
      v-else-if="store.items.length === 0"
      class="muted"
      v-html="t('models.providersEmpty')"
    />

    <ul v-else class="list">
      <li
        v-for="p in store.items"
        :key="p.name"
        class="card"
        :class="{ off: !isOn(p) }"
      >
        <div class="row">
          <div class="grow">
            <div class="title">
              {{ p.name }}
              <span class="type">· {{ p.provider_type }}</span>
              <span v-if="!isOn(p)" class="off-badge">{{
                t("models.providerOff")
              }}</span>
            </div>
            <div class="sub">
              {{ p.default_model || t("models.noDefaultModel") }}
              <span v-if="p.base_url"> · {{ p.base_url }}</span>
            </div>
            <code class="key">{{ p.api_key }}</code>
          </div>
          <div class="card-actions">
            <label
              class="switch"
              :title="isOn(p) ? t('models.providerDisable') : t('models.providerEnable')"
            >
              <input
                type="checkbox"
                :checked="isOn(p)"
                :disabled="toggling === p.name"
                @change="toggle(p)"
              />
              <span class="slider" />
            </label>
            <button class="btn-secondary" @click="editProvider(p)">
              {{ t("models.editProvider") }}
            </button>
            <button class="btn-danger" @click="removeProvider(p.name)">
              {{ t("models.providerDelete") }}
            </button>
          </div>
        </div>
      </li>
    </ul>

    <div
      v-if="adding"
      class="modal-bg"
      @click.self="adding = false"
    >
      <div class="modal">
        <h3>{{ t("models.addProviderTitle") }}</h3>
        <ProviderForm @created="onCreated" @cancel="adding = false" />
      </div>
    </div>
    <div
      v-if="editing"
      class="modal-bg"
      @click.self="editing = null"
    >
      <div class="modal">
        <h3>{{ t("models.editProvider") }} · {{ editing.name }}</h3>
        <ProviderForm
          :editing="editing"
          @created="onCreated"
          @cancel="editing = null"
        />
      </div>
    </div>
  </section>
</template>

<style scoped>
.page {
  max-width: 880px;
  margin: 0 auto;
  padding: 32px 24px;
  color: var(--text);
}
.head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 8px;
}
h2 {
  margin: 0;
  font-size: 22px;
  letter-spacing: -0.01em;
}
.hint {
  color: var(--text-mid);
  font-size: 13px;
  margin: 0 0 24px;
}
.section-h {
  margin: 0 0 8px;
  font-size: 11px;
  font-weight: 600;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  color: var(--text-faint);
}
.muted {
  color: var(--text-mid);
}
.list {
  list-style: none;
  padding: 0;
  margin: 0;
  display: grid;
  gap: 8px;
}
.card {
  border: 1px solid var(--border);
  border-radius: 10px;
  padding: 14px 16px;
  background: var(--bg);
  transition: border-color 120ms ease, background 120ms ease, opacity 120ms ease;
}
.card.off {
  opacity: 0.55;
  background: var(--bg-panel);
}
.row {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 16px;
}
.grow {
  min-width: 0;
  flex: 1;
}
.title {
  font-weight: 600;
  font-size: 15px;
  display: flex;
  align-items: center;
  gap: 6px;
}
.type {
  color: var(--text-mid);
  font-weight: 400;
}
.off-badge {
  font-size: 10px;
  letter-spacing: 0.06em;
  text-transform: uppercase;
  color: var(--text-mid);
  background: var(--bg-hover);
  padding: 1px 6px;
  border-radius: 4px;
  font-weight: 600;
}
.sub {
  font-size: 13px;
  color: var(--text-mute);
  margin-top: 2px;
}
.key {
  display: inline-block;
  background: var(--bg-hover);
  padding: 2px 6px;
  border-radius: 4px;
  font-size: 12px;
  margin-top: 6px;
  color: var(--text-mid);
}
.card-actions {
  display: flex;
  align-items: center;
  gap: 14px;
  flex-shrink: 0;
}
.btn-danger {
  background: var(--bg);
  color: var(--danger);
  border: 1px solid var(--danger-border);
  border-radius: 999px;
  height: 28px;
  padding: 0 12px;
  cursor: pointer;
  font-size: 12px;
  font-weight: 500;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  transition: background 120ms ease;
}
.btn-danger:hover {
  background: var(--danger-bg);
}
.btn-secondary {
  background: var(--bg);
  color: var(--text);
  border: 1px solid var(--border);
  border-radius: 999px;
  height: 28px;
  padding: 0 12px;
  cursor: pointer;
  font-size: 12px;
  font-weight: 500;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  transition: background 120ms ease, border-color 120ms ease;
}
.btn-secondary:hover {
  background: var(--bg-subtle);
  border-color: var(--border-mid);
}
.btn-primary {
  background: var(--accent);
  color: var(--accent-fg);
  border: 1px solid var(--accent);
  border-radius: 999px;
  height: 32px;
  padding: 0 16px;
  cursor: pointer;
  font-size: 13px;
  font-weight: 600;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  transition: background 120ms ease, border-color 120ms ease;
}
.btn-primary:hover {
  background: var(--accent-hover);
}
.error {
  color: var(--danger);
}
.loading {
  color: var(--text-mid);
}
.modal-bg {
  position: fixed;
  inset: 0;
  background: var(--backdrop);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 10;
}
.modal {
  background: var(--bg);
  border-radius: 14px;
  padding: 24px;
  width: min(560px, 94vw);
  max-height: 90vh;
  overflow-y: auto;
  box-shadow: var(--shadow-strong);
}
.modal h3 {
  margin: 0 0 16px;
  font-size: 16px;
}

/* Toggle switch */
.switch {
  position: relative;
  display: inline-block;
  width: 36px;
  height: 20px;
  flex-shrink: 0;
  cursor: pointer;
}
.switch input {
  opacity: 0;
  width: 0;
  height: 0;
  position: absolute;
}
.slider {
  position: absolute;
  inset: 0;
  background: var(--border);
  border-radius: 999px;
  transition: background 160ms ease;
}
.slider::before {
  content: "";
  position: absolute;
  width: 16px;
  height: 16px;
  left: 2px;
  top: 2px;
  background: var(--bg);
  border-radius: 50%;
  transition: transform 160ms ease;
  box-shadow: var(--shadow-toggle);
}
.switch input:checked + .slider {
  background: var(--accent);
}
.switch input:checked + .slider::before {
  transform: translateX(16px);
}
.switch input:disabled + .slider {
  opacity: 0.5;
  cursor: not-allowed;
}
</style>