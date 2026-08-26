<script setup lang="ts">
import { computed, onMounted, ref, watch } from "vue"
import { useThemeStore } from "../stores/theme"
import { useOnboardingStore } from "../stores/onboarding"
import { useAppMetaStore } from "../stores/appMeta"
import { usePrefsStore } from "../stores/prefs"
import { locale, setLocale, t, type Locale } from "../i18n"

const theme = useThemeStore()
const onboarding = useOnboardingStore()
const appMeta = useAppMetaStore()
const prefs = usePrefsStore()
const isDark = computed(() => theme.theme === "dark")
const isZh = computed(() => locale.value === "zh")

// Local edit buffer so typing doesn't snap to defaults until the user
// blurs / presses Enter; the store stays the source of truth on save.
const titleDraft = ref(appMeta.title)
watch(titleDraft, (v) => appMeta.setTitle(v))

// Same pattern for the system-prompt addition: keep an editable draft,
// flush to the backend on Save (explicit) so we don't hit the API on
// every keystroke. The server strips whitespace; the draft is what
// the user is currently typing, so we keep leading/trailing spaces
// in the textarea but trim before sending.
const promptDraft = ref<string>("")
const promptSaving = ref(false)
const promptError = ref<string | null>(null)
const promptSavedAt = ref<string>("")

onMounted(async () => {
  await prefs.load()
  promptDraft.value = prefs.systemPromptAddition
})

async function savePromptAddition() {
  promptSaving.value = true
  promptError.value = null
  try {
    const next = await prefs.save(promptDraft.value)
    promptDraft.value = next.system_prompt_addition
    promptSavedAt.value = next.updated_at
  } catch (e) {
    promptError.value = e instanceof Error ? e.message : String(e)
  } finally {
    promptSaving.value = false
  }
}

function pickLocale(l: Locale) {
  if (locale.value !== l) setLocale(l)
}

// Reset the dismissal flag so the overlay re-opens on next show.
// The store handles loading the card list if it isn't already cached.
async function replayTour() {
  onboarding.reset()
  onboarding.index = 0
  await onboarding.load()
  onboarding.open()
}
</script>

<template>
  <div class="settings">
    <div class="body">
      <header class="head">
        <h2>{{ t("settings.title") }}</h2>
        <p class="sub">{{ t("settings.subtitle") }}</p>
      </header>

      <section class="group">
        <h3>{{ t("settings.appearance") }}</h3>

        <div class="row">
          <div class="row-text">
            <div class="row-title">{{ t("settings.theme") }}</div>
            <div class="row-desc">{{ t("settings.themeDesc") }}</div>
          </div>
          <div class="seg" role="radiogroup" :aria-label="t('settings.theme')">
            <button
              type="button"
              role="radio"
              :aria-checked="!isDark"
              :class="['seg-opt', { active: !isDark }]"
              @click="theme.theme !== 'light' && theme.toggle()"
            >
              {{ t("settings.themeLight") }}
            </button>
            <button
              type="button"
              role="radio"
              :aria-checked="isDark"
              :class="['seg-opt', { active: isDark }]"
              @click="theme.theme !== 'dark' && theme.toggle()"
            >
              {{ t("settings.themeDark") }}
            </button>
          </div>
        </div>

        <div class="row">
          <div class="row-text">
            <div class="row-title">{{ t("settings.language") }}</div>
            <div class="row-desc">{{ t("settings.languageDesc") }}</div>
          </div>
          <div
            class="seg"
            role="radiogroup"
            :aria-label="t('settings.language')"
          >
            <button
              type="button"
              role="radio"
              :aria-checked="!isZh"
              :class="['seg-opt', { active: !isZh }]"
              @click="pickLocale('en')"
            >
              {{ t("settings.languageEn") }}
            </button>
            <button
              type="button"
              role="radio"
              :aria-checked="isZh"
              :class="['seg-opt', { active: isZh }]"
              @click="pickLocale('zh')"
            >
              {{ t("settings.languageZh") }}
            </button>
          </div>
        </div>

        <div class="row">
          <div class="row-text">
            <div class="row-title">{{ t("settings.appTitle") }}</div>
            <div class="row-desc">{{ t("settings.appTitleDesc") }}</div>
          </div>
          <input
            class="title-input"
            type="text"
            maxlength="64"
            :value="titleDraft"
            :placeholder="appMeta.title"
            :aria-label="t('settings.appTitle')"
            @input="titleDraft = ($event.target as HTMLInputElement).value"
          />
        </div>
      </section>

      <section class="group">
        <h3>{{ t("settings.aiBehavior") }}</h3>
        <div class="row row-stack">
          <div class="row-text">
            <div class="row-title">{{ t("settings.systemPromptAddition") }}</div>
            <div class="row-desc">
              {{ t("settings.systemPromptAdditionDesc") }}
            </div>
          </div>
          <textarea
            class="prompt-input"
            rows="6"
            :value="promptDraft"
            :placeholder="t('settings.systemPromptAdditionPlaceholder')"
            :aria-label="t('settings.systemPromptAddition')"
            :disabled="promptSaving"
            @input="
              promptDraft = ($event.target as HTMLTextAreaElement).value
            "
          />
          <div class="prompt-actions">
            <button
              class="seg-opt"
              type="button"
              :disabled="
                promptSaving
                || promptDraft.trim() === prefs.systemPromptAddition
              "
              @click="savePromptAddition"
            >
              {{ promptSaving ? t("settings.saving") : t("settings.save") }}
            </button>
            <span v-if="promptError" class="prompt-error">{{ promptError }}</span>
            <span v-else-if="promptSavedAt" class="prompt-saved">
              {{ t("settings.savedAt", { time: promptSavedAt }) }}
            </span>
          </div>
        </div>
      </section>

      <section class="group">
        <h3>{{ t("settings.about") }}</h3>
        <div class="row">
          <div class="row-text">
            <div class="row-title">{{ t("common.brand") }}</div>
            <div class="row-desc">{{ t("settings.aboutDesc") }}</div>
          </div>
        </div>
        <div class="row">
          <div class="row-text">
            <div class="row-title">{{ t("settings.tour") }}</div>
            <div class="row-desc">{{ t("settings.tourDesc") }}</div>
          </div>
          <button class="seg-opt" type="button" @click="replayTour">
            {{ t("onboarding.start") }}
          </button>
        </div>
      </section>
    </div>
  </div>
</template>

<style scoped>
.settings {
  height: 100%;
  overflow-y: auto;
  background: var(--bg);
  color: var(--text);
}
.body {
  max-width: clamp(720px, 78vw, 960px);
  margin: 0 auto;
  padding: 32px 24px;
}
.head h2 {
  margin: 0;
  font-size: 22px;
  font-weight: 600;
  color: var(--text);
}
.head .sub {
  margin: 6px 0 28px;
  color: var(--text-mid);
  font-size: 13px;
}
.group {
  border-top: 1px solid var(--border-faint);
  padding-top: 24px;
  margin-top: 24px;
}
.group h3 {
  margin: 0 0 14px;
  font-size: 11px;
  font-weight: 600;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  color: var(--text-faint);
}
.row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 24px;
  padding: 16px 0;
  border-bottom: 1px solid var(--border-faint);
}
.row:last-of-type {
  border-bottom: 0;
}
.row-text {
  min-width: 0;
}
.row-title {
  font-size: 14px;
  font-weight: 500;
  color: var(--text);
}
.row-desc {
  margin-top: 4px;
  font-size: 12.5px;
  color: var(--text-mid);
  line-height: 1.5;
}
.seg {
  flex-shrink: 0;
  display: inline-flex;
  background: var(--bg-subtle);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 2px;
}
.seg-opt {
  border: 0;
  background: transparent;
  color: var(--text-mid);
  font-size: 12.5px;
  padding: 5px 14px;
  border-radius: 6px;
  cursor: pointer;
  transition: background 120ms ease, color 120ms ease;
  font-family: inherit;
}
.seg-opt:hover {
  color: var(--text);
}
.seg-opt.active {
  background: var(--bg);
  color: var(--text);
  box-shadow: var(--shadow-toggle);
}
.about {
  padding: 12px 0;
}
.title-input {
  font: inherit;
  font-size: 13px;
  color: var(--text);
  background: var(--bg);
  border: 1px solid var(--border);
  border-radius: 6px;
  padding: 6px 10px;
  width: 220px;
  outline: none;
  transition: border-color 120ms ease, box-shadow 120ms ease;
}
.title-input:focus {
  border-color: var(--accent);
  box-shadow: 0 0 0 3px var(--accent-soft);
}
.row.row-stack {
  flex-direction: column;
  align-items: stretch;
  gap: 12px;
}
.prompt-input {
  font: inherit;
  font-size: 13px;
  color: var(--text);
  background: var(--bg);
  border: 1px solid var(--border);
  border-radius: 6px;
  padding: 10px 12px;
  width: 100%;
  outline: none;
  resize: vertical;
  min-height: 120px;
  font-family: ui-monospace, SFMono-Regular, Consolas, "Liberation Mono", monospace;
  transition: border-color 120ms ease, box-shadow 120ms ease;
}
.prompt-input:focus {
  border-color: var(--accent);
  box-shadow: 0 0 0 3px var(--accent-soft);
}
.prompt-input:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}
.prompt-actions {
  display: flex;
  align-items: center;
  gap: 12px;
  font-size: 12px;
  color: var(--text-mid);
}
.prompt-error {
  color: #d44;
}
.prompt-saved {
  color: var(--text-faint);
}
</style>
