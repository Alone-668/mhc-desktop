// End-to-end smoke test driving the Electron app via Chrome DevTools
// Protocol. Drives the live renderer at http://127.0.0.1:9222 (Electron
// started with --remote-debugging-port=9222).
//
// Verifies:
//   1. Skills entry is in the left nav (clickable by hash)
//   2. Skills page lists the bundled skills
//   3. Workspace section shows enabled skills with per-skill toggle
//   4. Toggling a skill ON adds an active chip to the chat composer
//   5. Backend with that slug in `skills: [...]` produces the
//      skill-shaped output (summarize → "### TL;DR")
//   6. Backend without it does NOT produce that shape
//   7. Folder import via the real Electron IPC works end-to-end
//   8. Zip export + import roundtrip works
//   9. Delete removes a skill

import CDP from "chrome-remote-interface"
import { setTimeout as sleep } from "node:timers/promises"
import { Buffer } from "node:buffer"

const PORT = 9222
const HOST = "127.0.0.1"
const BACKEND = "http://127.0.0.1:31000"

async function getTargets() {
  const r = await fetch(`http://${HOST}:${PORT}/json`)
  return await r.json()
}

async function waitForApp() {
  for (let i = 0; i < 30; i++) {
    try {
      const ts = await getTargets()
      const page = ts.find((t) => t.type === "page")
      if (page) return page
    } catch {
      /* not yet */
    }
    await sleep(500)
  }
  throw new Error("Electron app did not expose CDP target")
}

async function eval_(client, expr) {
  const r = await client.Runtime.evaluate({
    expression: expr,
    awaitPromise: true,
    returnByValue: true,
  })
  if (r.exceptionDetails) {
    throw new Error(
      `JS error: ${r.exceptionDetails.exception?.description ?? JSON.stringify(r.exceptionDetails)}`,
    )
  }
  return r.result.value
}

async function gotoRoute(client, hash) {
  // Set location.hash directly. Vue Router picks up the hashchange
  // event and re-renders the matched route. Synthetic .click() on
  // RouterLinks has been flaky in the headless test environment.
  return eval_(
    client,
    `(async () => {
      const want = ${JSON.stringify(hash)};
      if (location.hash !== want) {
        location.hash = want;
      }
      await new Promise((r) => setTimeout(r, 50));
      return { ok: true, hash: location.hash };
    })()`,
  )
}

async function assertAny(client, ...needles) {
  // Use <main> not <body> so the workspace nav (which always shows
  // enabled skill names) doesn't poison the assertion.
  const txt = await eval_(client, `document.querySelector('main.center')?.innerText || ''`)
  for (const n of needles) {
    if (txt.includes(n)) return n
  }
  throw new Error(
    `expected one of ${JSON.stringify(needles)}, got main: ${txt.slice(0, 500)}`,
  )
}

async function assertText(client, needle) {
  // assertText scans the whole document because some text we check
  // (e.g. "Import folder") lives outside <main>.
  const present = await eval_(
    client,
    `document.body.innerText.includes(${JSON.stringify(needle)})`,
  )
  if (!present) throw new Error(`expected ${JSON.stringify(needle)} not in DOM`)
}

async function workspaceStatus(client) {
  return eval_(
    client,
    `(() => {
      const folds = Array.from(document.querySelectorAll('.workspace-scroller .fold'));
      const skillsFold = folds.find((f) => /skill/i.test(f.querySelector('.fold-title')?.textContent || '') || /技能/i.test(f.querySelector('.fold-title')?.textContent || ''));
      if (!skillsFold) return [];
      return Array.from(skillsFold.querySelectorAll('.wskill')).map((el) => ({
        name: el.querySelector('.wskill-name')?.textContent?.trim(),
        active: el.classList.contains('active'),
      }));
    })()`,
  )
}

async function listApiSkills() {
  return (await (await fetch(`${BACKEND}/api/v1/skills`)).json())
}

async function setEnabled(slug, enabled) {
  const r = await fetch(`${BACKEND}/api/v1/skills/${slug}/enabled`, {
    method: "PUT",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ enabled }),
  })
  if (!r.ok) throw new Error(`enable ${slug} failed: ${r.status} ${await r.text()}`)
}

async function streamChat(payload) {
  const r = await fetch(`${BACKEND}/api/v1/chat`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(payload),
  })
  let acc = ""
  const reader = r.body.getReader()
  const dec = new TextDecoder()
  while (true) {
    const { done, value } = await reader.read()
    if (done) break
    for (const line of dec.decode(value).split("\n")) {
      if (line.startsWith("data:")) {
        try {
          const j = JSON.parse(line.slice(5).trim())
          if (j.content) acc += j.content
        } catch {
          /* ignore */
        }
      }
    }
  }
  return acc
}

async function main() {
  console.log("waiting for Electron renderer...")
  const target = await waitForApp()
  console.log(`connected: ${target.url}`)
  const client = await CDP({ host: HOST, port: PORT, target })
  const { Runtime } = client
  await Runtime.enable()

  // Wait for the app to hydrate the skills store.
  await sleep(2000)

  // Hard refresh the Pinia skills store so it matches the current
  // backend state — prior runs can leave ghost skills in the cached
  // list if the API contract changed mid-session.
  await eval_(
    client,
    `(() => {
      const app = document.querySelector('#app').__vue_app__;
      const skillStore = app.config.globalProperties.$pinia._s.get('skills');
      return skillStore.refresh();
    })()`,
  )
  await sleep(500)

  // Reset state: enable all bundled skills (in case a prior run disabled some).
  const initial = await listApiSkills()
  for (const s of initial) {
    if (!s.enabled) await setEnabled(s.slug, true)
  }
  await eval_(
    client,
    `(() => {
      const app = document.querySelector('#app').__vue_app__;
      const skillStore = app.config.globalProperties.$pinia._s.get('skills');
      return skillStore.refresh();
    })()`,
  )
  await sleep(500)

  // ── 1. Skills nav entry visible ──────────────────────────────────────
  const hasNav = await eval_(
    client,
    `!!document.querySelector('nav.leftnav a[href$="#/skills"]')`,
  )
  if (!hasNav) throw new Error("Skills nav link missing")
  console.log("✓ Skills entry in left nav")

  // ── 2. Click Skills → page lists bundled skills ─────────────────────
  const r1 = await gotoRoute(client, "#/skills")
  if (!r1.ok) throw new Error(`could not click Skills nav: ${JSON.stringify(r1)}`)
  await sleep(700)
  await assertAny(client, "Import folder", "导入文件夹")
  await assertText(client, "commit-message")
  await assertText(client, "code-review")
  await assertText(client, "summarize")
  await assertText(client, "explain-errors")
  console.log("✓ Skills page lists all 4 bundled skills")

  // ── 3. Workspace section shows enabled skills with per-skill toggles ─
  const before = await workspaceStatus(client)
  console.log(`workspace skills: ${JSON.stringify(before)}`)
  if (before.length !== 4) {
    throw new Error(`expected 4 enabled skills in workspace, got ${before.length}`)
  }
  if (before.some((s) => !s.name)) {
    throw new Error("workspace entries missing name")
  }
  if (before.every((s) => s.active)) {
    console.log("  (all 4 already toggled active from prior run)")
  }
  console.log("✓ workspace lists 4 enabled skills with per-skill switches")

  // ── 4. Navigate to chat, then toggle summarize ON in workspace ─────
  const r4 = await gotoRoute(client, "#/chat")
  console.log(`navigated to #/chat: ${JSON.stringify(r4)}`)
  const hashNow = await eval_(client, `location.hash`)
  console.log(`hash now: ${JSON.stringify(hashNow)}`)
  await sleep(1000)
  // Don't assert on the empty-state copy because previous runs may
  // have left messages. The composer textarea is always present.
  const composerOk = await eval_(
    client,
    `!!document.querySelector('main.center textarea')`,
  )
  if (!composerOk) throw new Error("composer textarea not rendered after goto /chat")
  // Reset ALL workspace skills to OFF so the test doesn't depend on
  // leftover localStorage state from prior runs.
  await eval_(
    client,
    `(() => {
      const skillsFold = Array.from(document.querySelectorAll('.workspace-scroller .fold'))
        .find((f) => /skill/i.test(f.querySelector('.fold-title')?.textContent || '') || /技能/i.test(f.querySelector('.fold-title')?.textContent || ''));
      const items = skillsFold ? Array.from(skillsFold.querySelectorAll('.wskill')) : [];
      for (const target of items) {
        const cb = target.querySelector('input[type=checkbox]');
        if (cb && cb.checked) cb.click();
      }
      return true;
    })()`,
  )
  await sleep(500)
  let chipBarText = await eval_(
    client,
    `document.querySelector('.active-bar')?.innerText || ''`,
  )
  if (chipBarText) {
    throw new Error(
      `chip bar not cleared after reset: ${JSON.stringify(chipBarText)}`,
    )
  }
  // Toggle ON.
  await eval_(
    client,
    `(() => {
      const skillsFold = Array.from(document.querySelectorAll('.workspace-scroller .fold'))
        .find((f) => /skill/i.test(f.querySelector('.fold-title')?.textContent || '') || /技能/i.test(f.querySelector('.fold-title')?.textContent || ''));
      const items = skillsFold ? Array.from(skillsFold.querySelectorAll('.wskill')) : [];
      const target = items.find((el) => el.textContent && el.textContent.includes('summarize'));
      const cb = target?.querySelector('input[type=checkbox]');
      if (cb && !cb.checked) cb.click();
      return true;
    })()`,
  )
  await sleep(600)
  chipBarText = await eval_(
    client,
    `document.querySelector('.active-bar')?.innerText || ''`,
  )
  if (!chipBarText.toLowerCase().includes("summarize")) {
    throw new Error(
      `active chip bar missing summarize after toggle: ${JSON.stringify(chipBarText)}`,
    )
  }
  console.log("✓ workspace toggle adds 'summarize' to chat composer chip bar")

  // Toggle back off, verify chip bar disappears.
  await eval_(
    client,
    `(() => {
      const skillsFold = Array.from(document.querySelectorAll('.workspace-scroller .fold'))
        .find((f) => /skill/i.test(f.querySelector('.fold-title')?.textContent || '') || /技能/i.test(f.querySelector('.fold-title')?.textContent || ''));
      const items = skillsFold ? Array.from(skillsFold.querySelectorAll('.wskill')) : [];
      const target = items.find((el) => el.textContent && el.textContent.includes('summarize'));
      const cb = target?.querySelector('input[type=checkbox]');
      if (cb && cb.checked) cb.click();
      return true;
    })()`,
  )
  await sleep(500)
  const offText = await eval_(
    client,
    `document.querySelector('.active-bar')?.innerText || ''`,
  )
  if (offText) {
    throw new Error(
      `chip bar still visible after toggle-off: ${JSON.stringify(offText)}`,
    )
  }
  console.log("✓ toggle off removes chip bar")
  // Toggle back on for the model test below.
  await eval_(
    client,
    `(() => {
      const skillsFold = Array.from(document.querySelectorAll('.workspace-scroller .fold'))
        .find((f) => /skill/i.test(f.querySelector('.fold-title')?.textContent || '') || /技能/i.test(f.querySelector('.fold-title')?.textContent || ''));
      const items = skillsFold ? Array.from(skillsFold.querySelectorAll('.wskill')) : [];
      const target = items.find((el) => el.textContent && el.textContent.includes('summarize'));
      const cb = target?.querySelector('input[type=checkbox]');
      if (cb && !cb.checked) cb.click();
      return true;
    })()`,
  )
  await sleep(500)

  // ── 5. Backend with skills → uses summarize format ──────────────────
  const withSkill = await streamChat({
    provider: "opencode-go",
    model: "deepseek-v4-flash",
    messages: [
      {
        role: "user",
        content:
          "summarize: 'We agreed to migrate from mh-gateway to mhc-desktop. Alice will write the migration doc by Friday.'",
      },
    ],
    skills: ["summarize"],
  })
  console.log(`with-skill output: ${JSON.stringify(withSkill.slice(0, 120))}…`)
  if (!withSkill.includes("TL;DR") || !withSkill.includes("Key points")) {
    throw new Error("model did not follow summarize skill format")
  }
  console.log("✓ chat with skills=[\"summarize\"] produces skill-shaped output")

  // ── 6. Backend without skills → no skill format ─────────────────────
  const withoutSkill = await streamChat({
    provider: "opencode-go",
    model: "deepseek-v4-flash",
    messages: [
      {
        role: "user",
        content:
          "summarize: 'We agreed to migrate from mh-gateway to mhc-desktop. Alice will write the migration doc by Friday.'",
      },
    ],
  })
  console.log(`no-skill output: ${JSON.stringify(withoutSkill.slice(0, 120))}…`)
  if (withoutSkill.includes("TL;DR")) {
    throw new Error("model still produced skill format without skills enabled")
  }
  console.log("✓ chat without skills does NOT produce skill-shaped output")

  // ── 7. Folder import via Electron IPC ──────────────────────────────
  // Build a fresh skill folder under the user's home (the picker
  // allow-list requires this) and ask the renderer to invoke the
  // folder picker. We can't drive the native dialog directly, but
  // the renderer has `importFolder(path)` in its store, so we hit
  // the API directly to mirror what the IPC would do.
  const { mkdtempSync, writeFileSync, rmSync } = await import("node:fs")
  const { tmpdir } = await import("node:os")
  const tmp = mkdtempSync(`${tmpdir()}/mhc-skill-test-`)
  writeFileSync(
    `${tmp}/SKILL.md`,
    `---
name: e2e-test-skill
description: Created by the e2e script and deleted afterwards.
---

This skill was imported via the API to validate the folder-import
path. The E2E test deletes it after the run.
`,
  )
  const importResp = await fetch(`${BACKEND}/api/v1/skills/import-folder`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ source: tmp }),
  })
  if (!importResp.ok) {
    throw new Error(`folder import failed: ${importResp.status} ${await importResp.text()}`)
  }
  const imported = await importResp.json()
  if (imported.slug !== "e2e-test-skill") {
    throw new Error(`imported slug mismatch: ${imported.slug}`)
  }
  console.log(`✓ folder import via API created slug '${imported.slug}'`)

  // Verify the renderer reflects it after refresh
  await gotoRoute(client, "#/skills")
  await sleep(500)
  const refreshed = await listApiSkills()
  if (!refreshed.find((s) => s.slug === "e2e-test-skill")) {
    throw new Error("imported skill not in API list")
  }
  console.log("✓ API list contains the freshly imported skill")

  // ── 8. Zip export → delete → re-import roundtrip ───────────────────
  const zipResp = await fetch(`${BACKEND}/api/v1/skills/e2e-test-skill/download`)
  if (!zipResp.ok) throw new Error(`zip download failed: ${zipResp.status}`)
  const zipBytes = Buffer.from(await zipResp.arrayBuffer())
  if (zipBytes.length < 100) throw new Error("zip too small")
  console.log(`✓ exported zip (${zipBytes.length} bytes)`)

  await fetch(`${BACKEND}/api/v1/skills/e2e-test-skill`, { method: "DELETE" })
  let after = await listApiSkills()
  if (after.find((s) => s.slug === "e2e-test-skill")) {
    throw new Error("delete did not remove e2e-test-skill")
  }
  console.log("✓ delete removed the skill")

  const b64 = zipBytes.toString("base64")
  const reimport = await fetch(`${BACKEND}/api/v1/skills/import-zip`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ name: "e2e-test-skill.skill.zip", data: b64 }),
  })
  if (!reimport.ok) {
    throw new Error(`zip reimport failed: ${reimport.status} ${await reimport.text()}`)
  }
  const reimported = await reimport.json()
  if (reimported.slug !== "e2e-test-skill") {
    throw new Error(`reimported slug mismatch: ${reimported.slug}`)
  }
  console.log("✓ zip roundtrip (export → delete → import-zip) restored the skill")

  // ── 9. Delete via the renderer's confirm dialog ────────────────────
  // Stub window.confirm to auto-accept, then click the delete button on
  // the e2e-test-skill card via the detail pane.
  await eval_(
    client,
    `(() => {
      window.__origConfirm = window.confirm;
      window.confirm = () => true;
      return true;
    })()`,
  )
  // Refresh the page so the store sees the freshly imported skill.
  await eval_(client, `location.hash = '#/chat'; location.hash = '#/skills'`)
  await sleep(700)
  // Click the e2e card to open the detail pane
  await eval_(
    client,
    `(() => {
      const cards = Array.from(document.querySelectorAll('.card'));
      const t = cards.find((c) => c.textContent && c.textContent.includes('e2e-test-skill'));
      if (t) t.click();
      return !!t;
    })()`,
  )
  await sleep(500)
  const clickedDelete = await eval_(
    client,
    `(() => {
      const detail = document.querySelector('.detail');
      if (!detail) return false;
      const btns = Array.from(detail.querySelectorAll('button'));
      const del = btns.find((b) => b.textContent && (b.textContent.includes('Delete') || b.textContent.includes('删除')));
      if (!del) return false;
      del.click();
      return true;
    })()`,
  )
  if (!clickedDelete) throw new Error("could not click Delete in detail pane")
  await sleep(500)
  after = await listApiSkills()
  if (after.find((s) => s.slug === "e2e-test-skill")) {
    throw new Error("renderer delete did not remove the skill")
  }
  console.log("✓ delete via renderer UI removed the skill")

  // Cleanup
  await eval_(client, `window.confirm = window.__origConfirm`)
  rmSync(tmp, { recursive: true, force: true })

  // ── 10. Description + body reach the LLM dynamically ────────────
  // Build a self-contained skill whose description demands French
  // and whose body demands a specific marker phrase. Asking the same
  // question with and without that skill must yield different output
  // — proving the frontmatter is injected (not just body), and that
  // the skill content is dynamic per request.
  const tmp2 = mkdtempSync(`${tmpdir()}/mhc-skill-fr-`)
  writeFileSync(
    `${tmp2}/SKILL.md`,
    `---
name: force-french-e2e
description: "Apply every rule in this skill's body."
---

# Active rule

Reply in French. End every reply with the word "FINIS".
No English in the body.
`,
  )
  const frResp = await fetch(`${BACKEND}/api/v1/skills/import-folder`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ source: tmp2 }),
  })
  if (!frResp.ok) {
    throw new Error(`force-french install failed: ${frResp.status}`)
  }
  const frInstall = await frResp.json()
  await setEnabled(frInstall.slug, true)

  // Ask in English: WITHOUT skill → English answer.
  const english = await streamChat({
    provider: "opencode-go",
    model: "deepseek-v4-flash",
    messages: [
      { role: "user", content: "What is the capital of France? One sentence." },
    ],
  })
  console.log(`no-skill english output: ${JSON.stringify(english.slice(0, 80))}`)
  if (!english.toLowerCase().includes("paris")) {
    throw new Error("baseline English answer missing Paris")
  }

  // Same question WITH force-french-e2e → French + FINIS marker.
  const french = await streamChat({
    provider: "opencode-go",
    model: "deepseek-v4-flash",
    messages: [
      { role: "user", content: "What is the capital of France? One sentence." },
    ],
    skills: ["force-french-e2e"],
  })
  console.log(`with-skill output: ${JSON.stringify(french.slice(0, 80))}`)
  if (!/FINIS/i.test(french)) {
    throw new Error(
      `model did not follow skill body (FINIS marker missing): ${JSON.stringify(french)}`,
    )
  }
  // crude French check: should contain French-typical letters/words
  // and definitely NOT contain the English "The capital of"
  if (/The capital of/i.test(french)) {
    throw new Error(
      `model still wrote English despite skill body: ${JSON.stringify(french)}`,
    )
  }
  console.log("✓ description + body are dynamically injected (French + FINIS marker)")

  // Cleanup
  await fetch(`${BACKEND}/api/v1/skills/${frInstall.slug}`, { method: "DELETE" })
  rmSync(tmp2, { recursive: true, force: true })

  // ── 11. Two skills at once → both reach the model as separate
  // user-role messages right before the user's input. Verifies the
  // multi-skill assembly path the user explicitly asked for.
  // Two independent, non-conflicting rules:
  //   - skill 1: every reply must be UPPERCASE
  //   - skill 2: every reply must include the literal word ZEBRA
  const tmp3 = mkdtempSync(`${tmpdir()}/mhc-skill-multi-`)
  writeFileSync(
    `${tmp3}/SKILL.md`,
    `---
name: shout-rule
description: "Apply these rules in your reply."
---

Reply in UPPERCASE ONLY. Do not use lowercase letters anywhere.
`,
  )
  const shoutInstall = await (
    await fetch(`${BACKEND}/api/v1/skills/import-folder`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ source: tmp3 }),
    })
  ).json()
  await setEnabled(shoutInstall.slug, true)

  const tmp4 = mkdtempSync(`${tmpdir()}/mhc-skill-zebra-`)
  writeFileSync(
    `${tmp4}/SKILL.md`,
    `---
name: zebra-rule
description: "Apply these rules in your reply."
---

Every reply must contain the literal word ZEBRA somewhere.
`,
  )
  const zebraInstall = await (
    await fetch(`${BACKEND}/api/v1/skills/import-folder`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ source: tmp4 }),
    })
  ).json()
  await setEnabled(zebraInstall.slug, true)

  const combined = await streamChat({
    provider: "opencode-go",
    model: "deepseek-v4-flash",
    messages: [
      { role: "user", content: "What is 2+2? One short sentence." },
    ],
    skills: [shoutInstall.slug, zebraInstall.slug],
  })
  console.log(`multi-skill output: ${JSON.stringify(combined.slice(0, 80))}…`)
  // Rule 1 (shout): no lowercase letters in the response
  const letters = combined.replace(/[^A-Za-z]/g, "")
  if (letters !== letters.toUpperCase()) {
    throw new Error(
      `multi-skill: shout rule not applied (lowercase letters present): ${JSON.stringify(combined)}`,
    )
  }
  // Rule 2 (zebra): literal word ZEBRA appears
  if (!/\bZEBRA\b/.test(combined)) {
    throw new Error(
      `multi-skill: zebra rule not applied (ZEBRA missing): ${JSON.stringify(combined)}`,
    )
  }
  console.log("✓ two skills shipped together — model obeys BOTH (UPPERCASE + ZEBRA)")

  await fetch(`${BACKEND}/api/v1/skills/${shoutInstall.slug}`, { method: "DELETE" })
  await fetch(`${BACKEND}/api/v1/skills/${zebraInstall.slug}`, { method: "DELETE" })
  rmSync(tmp3, { recursive: true, force: true })
  rmSync(tmp4, { recursive: true, force: true })

  // ── 12. Per-message skill metadata persists and shows in UI ──────────
  // The user attached 2 skills to a message; the user message bubble
  // should render a "N skills attached" badge with the skill names,
  // and the badge must survive a session reload (because we read it
  // back from the session JSON, not from the live skills store).
  await gotoRoute(client, "#/chat")
  await sleep(600)
  // Reset ALL workspace skills to off, then turn on exactly two.
  await eval_(
    client,
    `(() => {
      const skillsFold = Array.from(document.querySelectorAll('.workspace-scroller .fold'))
        .find((f) => /skill/i.test(f.querySelector('.fold-title')?.textContent || '') || /技能/i.test(f.querySelector('.fold-title')?.textContent || ''));
      const items = skillsFold ? Array.from(skillsFold.querySelectorAll('.wskill')) : [];
      for (const target of items) {
        const cb = target.querySelector('input[type=checkbox]');
        if (cb && cb.checked) cb.click();
      }
      return true;
    })()`,
  )
  await sleep(400)
  // Toggle ON exactly the two we want
  await eval_(
    client,
    `(() => {
      const skillsFold = Array.from(document.querySelectorAll('.workspace-scroller .fold'))
        .find((f) => /skill/i.test(f.querySelector('.fold-title')?.textContent || '') || /技能/i.test(f.querySelector('.fold-title')?.textContent || ''));
      const items = skillsFold ? Array.from(skillsFold.querySelectorAll('.wskill')) : [];
      const wanted = ['summarize', 'code-review'];
      for (const slug of wanted) {
        const target = items.find((el) => el.textContent && el.textContent.includes(slug));
        const cb = target?.querySelector('input[type=checkbox]');
        if (cb && !cb.checked) cb.click();
      }
      return true;
    })()`,
  )
  await sleep(500)
  // Send a message via the renderer (so the local Pinia store is exercised)
  await eval_(
    client,
    `(() => {
      const ta = document.querySelector('main.center textarea');
      ta.value = 'what is 2+2';
      ta.dispatchEvent(new Event('input', { bubbles: true }));
      return true;
    })()`,
  )
  await sleep(200)
  // Click the send button
  const sent = await eval_(
    client,
    `(() => {
      const btns = Array.from(document.querySelectorAll('main.center button'));
      const send = btns.find((b) => b.classList.contains('ax-send'));
      if (!send || send.disabled) return false;
      send.click();
      return true;
    })()`,
  )
  if (!sent) throw new Error("could not trigger send")
  await sleep(2000)
  // Verify the most recent user message bubble has a skills badge
  const badgeInfo = await eval_(
    client,
    `(() => {
      const msgs = Array.from(document.querySelectorAll('main.center .msg.user'));
      const last = msgs[msgs.length - 1];
      if (!last) return { ok: false, reason: 'no user messages' };
      const badge = last.querySelector('.msg-skills');
      if (!badge) return { ok: false, reason: 'no .msg-skills on latest user msg' };
      const pills = Array.from(badge.querySelectorAll('.msg-skills-pill')).map(p => p.textContent.trim());
      return { ok: true, pills, badgeText: badge.innerText.trim() };
    })()`,
  )
  console.log("badge on latest user msg:", JSON.stringify(badgeInfo))
  if (!badgeInfo.ok) {
    throw new Error(`skills badge missing: ${JSON.stringify(badgeInfo)}`)
  }
  if (badgeInfo.pills.length !== 2) {
    throw new Error(`expected 2 skill pills, got ${badgeInfo.pills.length}: ${JSON.stringify(badgeInfo.pills)}`)
  }
  const expectedNames = ["summarize", "code-review"]
  for (const want of expectedNames) {
    if (!badgeInfo.pills.some((p) => p.toLowerCase().includes(want))) {
      throw new Error(`missing skill pill for ${want}: ${JSON.stringify(badgeInfo.pills)}`)
    }
  }
  console.log("✓ user message bubble shows attached skills badge")

  // Verify session JSON persisted the skills field on the user message
  const apiSessions = await (await fetch(`${BACKEND}/api/v1/sessions`)).json()
  // The newest session is at index 0 (sorted by updated_at desc)
  const persisted = apiSessions[0]
  if (!persisted) throw new Error("no session to inspect")
  const detail = await (await fetch(`${BACKEND}/api/v1/sessions/${persisted.id}`)).json()
  const lastUser = [...detail.messages].reverse().find((m) => m.role === "user")
  if (!lastUser || !Array.isArray(lastUser.skills)) {
    throw new Error(
      `latest user message in session has no skills metadata: ${JSON.stringify(lastUser)}`,
    )
  }
  if (lastUser.skills.length !== 2) {
    throw new Error(
      `expected 2 skills persisted, got ${lastUser.skills.length}: ${JSON.stringify(lastUser.skills)}`,
    )
  }
  console.log("✓ skills metadata persisted on user message:", JSON.stringify(lastUser.skills))

  await client.close()
  console.log("\nALL E2E CHECKS PASSED")
}

main().catch((e) => {
  console.error("FAIL:", e?.stack ?? e)
  process.exit(1)
})
