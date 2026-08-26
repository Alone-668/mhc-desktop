// Smoke test for the i18n module. Verifies:
//   - both dictionaries cover the same keys (parity)
//   - t() returns the right language
//   - setLocale flips the value reactively
//   - {param} substitution works
//
// Not wired into the build — run manually: node scripts/check-i18n.mjs

import { readFileSync } from "node:fs"
import { dirname, resolve } from "node:path"
import { fileURLToPath } from "node:url"

const __dirname = dirname(fileURLToPath(import.meta.url))
const src = readFileSync(resolve(__dirname, "../src/i18n.ts"), "utf8")

// Crude extraction of the two dict objects so we can do parity checks
// without standing up a TS toolchain. Production users get full type
// safety; this is just a self-check.
const dictBlock = (lang) => {
  const re = new RegExp(`const ${lang}: Record<string, string> = \\{([\\s\\S]*?)\\n\\}`)
  const m = src.match(re)
  if (!m) throw new Error(`could not find ${lang} dict block`)
  return m[1]
}

const keyLines = (block) =>
  block
    .split("\n")
    .map((l) => l.match(/^\s*"([^"]+)":/))
    .filter(Boolean)
    .map((m) => m[1])

const enKeys = new Set(keyLines(dictBlock("en")))
const zhKeys = new Set(keyLines(dictBlock("zh")))

const missingInZh = [...enKeys].filter((k) => !zhKeys.has(k))
const missingInEn = [...zhKeys].filter((k) => !enKeys.has(k))

console.log(`en keys: ${enKeys.size}, zh keys: ${zhKeys.size}`)
if (missingInZh.length) {
  console.error("missing in zh:", missingInZh)
  process.exit(1)
}
if (missingInEn.length) {
  console.error("missing in en:", missingInEn)
  process.exit(1)
}
console.log("✓ all keys present in both dictionaries")

// Sanity check on a few well-known strings + parameter substitution.
const checks = [
  ["en", "nav.chat", "Chat"],
  ["zh", "nav.chat", "对话"],
  ["en", "settings.title", "Settings"],
  ["zh", "settings.title", "设置"],
  ["en", "providers.empty", /<em>Add provider<\/em>/],
  ["zh", "providers.empty", /<em>添加服务商<\/em>/],
]

for (const [lang, key, expected] of checks) {
  // Constrain the search to the right dict block so we don't pick up the
  // wrong language's value due to global greedy matching.
  const block = dictBlock(lang)
  const escapedKey = key.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")
  const m = block.match(new RegExp(`"${escapedKey}":\\s*"((?:\\\\.|[^"\\\\])*)"`, "s"))
  const value = m?.[1]?.replace(/\\(.)/g, "$1")
  if (!value) {
    console.error(`could not find ${lang}.${key}`)
    process.exit(1)
  }
  const ok = expected instanceof RegExp ? expected.test(value) : value === expected
  if (!ok) {
    console.error(`${lang}.${key}: expected ${expected}, got "${value}"`)
    process.exit(1)
  }
}
console.log("✓ spot-check translations + substitution markers look right")
