<script setup lang="ts">
import { computed, ref, watch } from "vue"
import { useProvidersStore } from "../stores/providers"
import type { Provider, ProviderModel, ProviderType } from "../api/client"
import { t } from "../i18n"

const props = defineProps<{
  editing?: Provider | null
}>()

const emit = defineEmits<{
  created: [provider: Provider]
  cancel: []
}>()

const store = useProvidersStore()

const name = ref("")
const providerType = ref<ProviderType>("openai")
const apiKey = ref("")
const baseUrl = ref("")
const defaultModel = ref("")
const description = ref("")
const modelParams = ref("{}")
const paramsError = ref<string | null>(null)
const submitting = ref(false)
const errorMsg = ref<string | null>(null)

// Models list — one row per model. The wire-format field ``code`` is
// what we send to the LLM API, so we treat it as the model's id in
// the UI ("Model ID"). Adding a row inserts an empty stub; the user
// edits code / display_name / max_context in place.
const models = ref<ProviderModel[]>([])

function addModel() {
  models.value = [
    ...models.value,
    { code: "", display_name: "", max_context: 0 },
  ]
}
function removeModel(idx: number) {
  models.value = models.value.filter((_, i) => i !== idx)
}
function moveModel(idx: number, dir: -1 | 1) {
  const j = idx + dir
  if (j < 0 || j >= models.value.length) return
  const next = [...models.value]
  ;[next[idx], next[j]] = [next[j], next[idx]]
  models.value = next
}

const cleanedModels = computed<ProviderModel[]>(() => {
  const out: ProviderModel[] = []
  for (const m of models.value) {
    const code = m.code.trim()
    if (!code) continue
    out.push({
      code,
      display_name: (m.display_name ?? "").trim() || code,
      max_context: Number(m.max_context) > 0 ? Number(m.max_context) : 0,
    })
  }
  return out
})



// Edit mode: seed from the provider being edited. The backend
// masks api_key on read (***abcd) and the frontend cannot show
// the real value, so we leave the field empty on entry — the
// backend treats empty as "keep the existing key" on PUT.
const existingApiKey = ref("")
watch(
  () => props.editing,
  (p) => {
    if (!p) return
    name.value = p.name
    providerType.value = p.provider_type
    apiKey.value = ""
    existingApiKey.value = p.api_key ?? ""
    baseUrl.value = p.base_url
    defaultModel.value = p.default_model
    description.value = p.description
    modelParams.value = JSON.stringify(p.model_params ?? {}, null, 2)
    models.value = (p.models ?? []).map((m) => ({ ...m }))
  },
  { immediate: true },
)

// In edit mode the api_key field is optional — leave blank to keep
// the saved key. Create mode still requires it (no saved key yet).
const canSubmit = computed(() => {
  if (name.value.trim().length === 0) return false
  if (props.editing) return true
  return apiKey.value.trim().length > 0
})

async function submit() {
  if (!canSubmit.value) return
  submitting.value = true
  errorMsg.value = null
  paramsError.value = null
  let params: Record<string, unknown> = {}
  const trimmed = modelParams.value.trim()
  if (trimmed) {
    try {
      const parsed = JSON.parse(trimmed)
      if (typeof parsed !== "object" || parsed === null || Array.isArray(parsed)) {
        throw new Error("must be a JSON object")
      }
      params = parsed as Record<string, unknown>
    } catch (e) {
      paramsError.value = e instanceof Error ? e.message : String(e)
      submitting.value = false
      return
    }
  }
  try {
    const body = {
      name: name.value.trim(),
      provider_type: providerType.value,
      api_key: apiKey.value.trim(),
      base_url: baseUrl.value.trim(),
      default_model: defaultModel.value.trim(),
      description: description.value.trim(),
      model_params: params,
      models: cleanedModels.value,
    }
    if (props.editing) {
      const updated = await store.update(props.editing.name, body)
      emit("created", updated)
    } else {
      const created = await store.create(body)
      emit("created", created)
    }
  } catch (e) {
    errorMsg.value = e instanceof Error ? e.message : String(e)
  } finally {
    submitting.value = false
  }
}
</script>

<template>
  <form class="form" @submit.prevent="submit">
    <label>
      <span>{{ t("providerForm.name") }}</span>
      <input
        v-model="name"
        :placeholder="t('providerForm.namePlaceholder')"
        required
      />
    </label>
    <label>
      <span>{{ t("providerForm.apiKey") }}</span>
      <input
        v-model="apiKey"
        type="password"
        :placeholder="
          editing && existingApiKey
            ? existingApiKey
            : t('providerForm.apiKeyPlaceholder')
        "
        :required="!editing"
      />
      <small v-if="editing" class="hint">{{
        t("providerForm.apiKeyKeepHint")
      }}</small>
    </label>
    <label>
      <span>{{ t("providerForm.providerType") }}</span>
      <select v-model="providerType">
        <option value="openai">{{ t("providerForm.openai") }}</option>
        <option value="anthropic">{{ t("providerForm.anthropic") }}</option>
      </select>
    </label>
    <label>
      <span>{{ t("providerForm.baseUrl") }}</span>
      <input
        v-model="baseUrl"
        :placeholder="t('providerForm.baseUrlPlaceholder')"
      />
    </label>
    <label>
      <span>{{ t("providerForm.defaultModel") }}</span>
      <input
        v-model="defaultModel"
        :placeholder="t('providerForm.defaultModelPlaceholder')"
      />
    </label>
    <label>
      <span>{{ t("providerForm.description") }}</span>
      <input v-model="description" />
    </label>

    <div class="models-block">
      <div class="models-head">
        <span class="models-label">{{ t("providerForm.models") }}</span>
        <button
          type="button"
          class="add-model"
          @click="addModel"
        >
          + {{ t("providerForm.addModel") }}
        </button>
      </div>
      <p class="models-hint">{{ t("providerForm.modelsHint") }}</p>
      <div v-if="models.length === 0" class="models-empty">
        {{ t("providerForm.modelsEmpty") }}
      </div>
      <ul v-else class="models-list">
        <li
          v-for="(m, idx) in models"
          :key="idx"
          class="models-row"
        >
          <input
            v-model="m.code"
            class="m-code"
            :placeholder="t('providerForm.modelCodePlaceholder')"
            spellcheck="false"
          />
          <input
            v-model="m.display_name"
            class="m-display"
            :placeholder="t('providerForm.modelDisplayPlaceholder')"
            spellcheck="false"
          />
          <input
            v-model.number="m.max_context"
            type="number"
            min="0"
            step="1000"
            class="m-ctx"
            :placeholder="t('providerForm.modelCtxPlaceholder')"
          />
          <div class="m-actions">
            <button
              type="button"
              class="m-act"
              :disabled="idx === 0"
              :title="t('providerForm.moveUp')"
              @click="moveModel(idx, -1)"
            >↑</button>
            <button
              type="button"
              class="m-act"
              :disabled="idx === models.length - 1"
              :title="t('providerForm.moveDown')"
              @click="moveModel(idx, 1)"
            >↓</button>
            <button
              type="button"
              class="m-act danger"
              :title="t('providerForm.removeModel')"
              @click="removeModel(idx)"
            >×</button>
          </div>
        </li>
      </ul>
    </div>

    <label>
      <span>{{ t("providerForm.modelParams") }}</span>
      <textarea
        v-model="modelParams"
        class="mono params-input"
        rows="3"
        placeholder='{"reasoning_effort": "high"}'
      />
      <small v-if="paramsError" class="error">{{ paramsError }}</small>
    </label>
    <p v-if="errorMsg" class="error">{{ errorMsg }}</p>
    <div class="actions">
      <button type="button" class="btn-secondary" @click="emit('cancel')">
        {{ t("common.cancel") }}
      </button>
      <button
        type="submit"
        class="btn-primary"
        :disabled="!canSubmit || submitting"
      >
        {{ submitting ? t("common.saving") : t("common.save") }}
      </button>
    </div>
  </form>
</template>

<style scoped>
.form {
  display: grid;
  gap: 12px;
}
label {
  display: grid;
  gap: 4px;
  font-size: 13px;
}
label > span {
  color: var(--text-mid);
  font-weight: 500;
}
input,
select {
  padding: 8px 10px;
  border: 1px solid var(--border-mid);
  border-radius: 6px;
  font: inherit;
  background: var(--bg);
  color: var(--text);
}
textarea.params-input {
  padding: 8px 10px;
  border: 1px solid var(--border-mid);
  border-radius: 6px;
  font-family: var(--font-mono);
  font-size: 12px;
  background: var(--bg);
  color: var(--text);
  resize: vertical;
}
.models-block {
  display: grid;
  gap: 6px;
  padding-top: 4px;
}
.models-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.models-label {
  font-size: 13px;
  font-weight: 500;
  color: var(--text-mid);
}
.add-model {
  background: var(--bg);
  border: 1px solid var(--border-mid);
  border-radius: 6px;
  padding: 4px 10px;
  cursor: pointer;
  font: inherit;
  font-size: 12.5px;
  color: var(--text-mute);
  transition: background 120ms ease, border-color 120ms ease;
}
.add-model:hover {
  background: var(--bg-hover);
  border-color: var(--accent);
  color: var(--text);
}
.models-hint {
  font-size: 11.5px;
  color: var(--text-faint);
  margin: 0;
}
.models-empty {
  font-size: 12px;
  color: var(--text-faint);
  padding: 8px 10px;
  border: 1px dashed var(--border);
  border-radius: 6px;
  text-align: center;
}
.models-list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: grid;
  gap: 6px;
}
.models-row {
  display: grid;
  grid-template-columns: minmax(110px, 1fr) minmax(120px, 1.1fr) 100px auto;
  gap: 6px;
  align-items: center;
}
.models-row input {
  font-family: var(--font-mono);
  font-size: 12.5px;
  min-width: 0;
  width: 100%;
}
.models-row .m-display {
  font-family: inherit;
}
.m-actions {
  display: flex;
  gap: 2px;
}
.m-act {
  width: 26px;
  height: 28px;
  border: 1px solid var(--border-mid);
  background: var(--bg);
  border-radius: 4px;
  cursor: pointer;
  color: var(--text-mute);
  font-size: 13px;
  line-height: 1;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  padding: 0;
  transition: background 120ms ease, color 120ms ease, border-color 120ms ease;
}
.m-act:hover:not(:disabled) {
  background: var(--bg-hover);
  color: var(--text);
}
.m-act.danger:hover:not(:disabled) {
  color: var(--danger);
  border-color: var(--danger-border);
}
.m-act:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}
.actions {
  display: flex;
  gap: 8px;
  justify-content: flex-end;
  margin-top: 8px;
}
.btn-primary,
.btn-secondary {
  padding: 8px 14px;
  border-radius: 6px;
  font: inherit;
  cursor: pointer;
  border: 1px solid transparent;
}
.btn-primary {
  background: var(--brand);
  color: white;
  border-color: var(--brand);
}
.btn-primary:disabled {
  background: var(--brand-soft);
  border-color: var(--brand-soft);
  cursor: not-allowed;
}
.btn-secondary {
  background: var(--bg);
  color: var(--text-mute);
  border-color: var(--border-mid);
}
.error {
  color: var(--danger);
  font-size: 13px;
  margin: 0;
}
.hint {
  color: var(--text-faint);
  font-size: 11.5px;
  margin-top: 2px;
}
</style>