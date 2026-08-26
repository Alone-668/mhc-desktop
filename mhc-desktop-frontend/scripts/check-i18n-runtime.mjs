// Runtime smoke test for the i18n module. Stubs browser globals, then
// imports the actual src/i18n.ts via tsx to verify setLocale / t() /
// param substitution actually work the way the components use them.
//
// Run: npx tsx scripts/check-i18n-runtime.mts

// Stub the browser globals that vue runtime-dom and i18n.ts touch at
// module load time. localStorage and navigator.language need to be
// user-writable; document needs createElement for vue's template cache.
const fakeStorage = {
  _data: {},
  getItem(k) {
    return this._data[k] ?? null
  },
  setItem(k, v) {
    this._data[k] = String(v)
  },
  removeItem(k) {
    delete this._data[k]
  },
}
Object.defineProperty(globalThis, "localStorage", {
  value: fakeStorage,
  configurable: true,
})
Object.defineProperty(globalThis.navigator, "language", {
  value: "en-US",
  configurable: true,
})
Object.defineProperty(globalThis, "document", {
  value: {
    createElement() {
      return {
        content: { cloneNode: () => ({}) },
        cloneNode: () => ({}),
        innerHTML: "",
      }
    },
    createElementNS() {
      return { innerHTML: "" }
    },
    documentElement: {
      setAttribute(k, v) {
        this[k] = v
      },
      getAttribute(k) {
        return this[k] ?? null
      },
    },
  },
  configurable: true,
})

const { locale, t, setLocale } = await import("../src/i18n.ts")

const checks = [
  // [expression, expected]
  ["t('nav.chat') === 'Chat'", t("nav.chat") === "Chat"],
  ["t('chat.emptyTitle')", t("chat.emptyTitle") === "Ask anything"],
  [
    "t('common.confirmDeleteProvider', { name: 'openai-1' })",
    t("common.confirmDeleteProvider", { name: "openai-1" }) ===
      'Delete provider "openai-1"?',
  ],
]

for (const [label, ok] of checks) {
  if (!ok) {
    console.error("FAIL:", label)
    process.exit(1)
  }
  console.log("ok:", label)
}

// Switching to Chinese should flip every lookup.
setLocale("zh")
const zhChecks = [
  ["locale.value === 'zh'", locale.value === "zh"],
  ["t('nav.chat') === '对话'", t("nav.chat") === "对话"],
  ["t('chat.emptyTitle') === '随便问'", t("chat.emptyTitle") === "随便问"],
  [
    "t('common.confirmDeleteProvider', { name: 'foo' }) === '确认删除服务商 \"foo\"？'",
    t("common.confirmDeleteProvider", { name: "foo" }) ===
      '确认删除服务商 "foo"？',
  ],
]
for (const [label, ok] of zhChecks) {
  if (!ok) {
    console.error("FAIL after switch:", label)
    process.exit(1)
  }
  console.log("ok:", label)
}

// Switching back should restore English (and persist).
setLocale("en")
if (t("nav.chat") !== "Chat") {
  console.error("FAIL: locale did not flip back")
  process.exit(1)
}
if (globalThis.localStorage.getItem("mhc.locale") !== "en") {
  console.error("FAIL: locale not persisted")
  process.exit(1)
}
console.log("ok: locale persisted to localStorage")

// Missing keys fall back to the key itself (so typos are visible in dev).
if (t("nonexistent.key") !== "nonexistent.key") {
  console.error("FAIL: missing-key fallback broken")
  process.exit(1)
}
console.log("ok: missing-key fallback")

// Plural: en one vs other
import("../src/i18n.ts").then(({ t, locale }) => {
  locale.value = "en"
  const one = t("skills.activeChip", { count: 1 })
  const many = t("skills.activeChip", { count: 3 })
  if (!one.includes("1 skill ") || one.includes("1 skills")) {
    console.error("FAIL: en singular plural: ", JSON.stringify(one))
    process.exit(1)
  }
  if (!many.includes("3 skills") || !many.includes("3 skills ")) {
    console.error("FAIL: en plural plural: ", JSON.stringify(many))
    process.exit(1)
  }
  console.log("ok: en plural one vs other")
  locale.value = "zh"
  const z1 = t("chat.attachedSkills", { count: 1 })
  const z3 = t("chat.attachedSkills", { count: 3 })
  if (!z3.includes("3") || !z3.includes("技能")) {
    console.error("FAIL: zh plural: ", JSON.stringify(z3))
    process.exit(1)
  }
  console.log("ok: zh plural: ", JSON.stringify(z1), "|", JSON.stringify(z3))
  console.log("\nall runtime checks passed")
})
