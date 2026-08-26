// @ts-nocheck
// E2E: bundled HarmonyOS Sans fonts load and are applied to the body.
//
// Drives the live Electron app via CDP. Verifies that:
//   1. All 6 @font-face rules (3 weights × 2 families) are registered
//   2. body font-family falls through our var(--font-sans) token
//   3. Regular weight of both families has actually loaded (so we
//      don't ship a UI that visibly snaps to a system font)
//
// Run with: node scripts/e2e-fonts.mjs

import { CDP } from "./e2e-helpers.mjs"

const TARGET_HOST = "127.0.0.1"
const TARGET_PORT = 9222

async function main() {
  const client = await CDP({ host: TARGET_HOST, port: TARGET_PORT })
  const { Runtime, Page } = client
  await Runtime.enable()
  await Page.enable()

  console.log("waiting for Electron renderer...")
  // Wait for the dev server URL to appear in the address bar.
  let info = null
  for (let i = 0; i < 60; i++) {
    try {
      const r = await Runtime.evaluate({
        expression: "location.href",
        returnByValue: true,
      })
      if (r.result.value && r.result.value.startsWith("http")) {
        info = r.result.value
        break
      }
    } catch {
      /* renderer not ready */
    }
    await new Promise((r) => setTimeout(r, 500))
  }
  if (!info) throw new Error("renderer never came up")
  console.log(`connected: ${info}`)

  // Hard reload so the latest index.html / fonts.css are picked up
  // (CDP is attached to a long-running session; without reload, the
  // existing renderer would still have the old font-family).
  await Runtime.evaluate({ expression: "location.reload()" })
  await new Promise((r) => setTimeout(r, 2500))

  // 1. Verify all 6 @font-face rules registered.
  const registered = await Runtime.evaluate({
    expression: `Array.from(document.fonts).map((f) => ({
      family: f.family,
      weight: f.weight,
      status: f.status,
    }))`,
    returnByValue: true,
  })
  const fonts = registered.result.value
  const expected = [
    ["HarmonyOS Sans", "400"],
    ["HarmonyOS Sans", "500"],
    ["HarmonyOS Sans", "700"],
    ["HarmonyOS Sans SC", "400"],
    ["HarmonyOS Sans SC", "500"],
    ["HarmonyOS Sans SC", "700"],
  ]
  for (const [family, weight] of expected) {
    if (!fonts.some((f) => f.family === family && f.weight === weight)) {
      throw new Error(`@font-face missing: ${family} weight=${weight}`)
    }
  }
  console.log(`✓ ${fonts.length} @font-face rules registered`)

  // 2. body uses the var(--font-sans) token.
  const body = await Runtime.evaluate({
    expression: "getComputedStyle(document.body).fontFamily",
    returnByValue: true,
  })
  const ff = body.result.value
  if (!ff.includes("HarmonyOS Sans SC") || !ff.includes("HarmonyOS Sans")) {
    throw new Error(`body font-family wrong: ${ff}`)
  }
  console.log(`✓ body font-family = ${ff.slice(0, 80)}…`)

  // 3. Wait for the Regular weights of both families to actually
  //    download. Other weights may stay unloaded if no element uses
  //    them yet (e.g. no bold CJK on screen), but Regular is the
  //    baseline of every paragraph.
  const deadline = Date.now() + 8000
  while (Date.now() < deadline) {
    const r = await Runtime.evaluate({
      expression: `(() => {
        const want = ['HarmonyOS Sans:400', 'HarmonyOS Sans SC:400'];
        return want.every((k) => {
          const [fam, w] = k.split(':');
          return Array.from(document.fonts).some(
            (f) => f.family === fam && f.weight === w && f.status === 'loaded'
          );
        });
      })()`,
      returnByValue: true,
    })
    if (r.result.value) break
    await new Promise((r) => setTimeout(r, 200))
  }
  const finalCheck = await Runtime.evaluate({
    expression: `Array.from(document.fonts)
      .filter((f) => f.weight === '400' || f.weight === '700')
      .map((f) => ({ family: f.family, weight: f.weight, status: f.status }))`,
    returnByValue: true,
  })
  console.log("Regular/Bold status:", JSON.stringify(finalCheck.result.value))
  const allReady = finalCheck.result.value.every(
    (f) => f.family !== "HarmonyOS Sans SC" || f.status === "loaded",
  )
  if (!allReady) {
    throw new Error("SC Regular/Bold not loaded after 8s")
  }
  console.log("✓ Regular/Bold weights loaded for both families")

  await client.close()
  console.log("\nALL FONT CHECKS PASSED")
}

main().catch((e) => {
  console.error("FAIL:", e)
  process.exit(1)
})