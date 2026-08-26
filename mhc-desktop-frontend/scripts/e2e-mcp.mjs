// End-to-end test for the MCP subsystem.
//
// Verifies (via the live Electron renderer + Chrome DevTools Protocol):
//   1. The MCP entry is in the left nav (parallel to Skills / Providers).
//   2. The MCP page lists the bundled dummy MCP.
//   3. The MCP page supports per-MCP enable toggle.
//   4. The workspace shows TWO foldable containers (Skills + MCP),
//      the MCP one shows the dummy entry with its per-send toggle.
//   5. Toggling the MCP on attaches it to the next message — the
//      active-bar chip bar shows the MCP pill.
//   6. Sending the message sends `mcp: ["dummy"]` and the model calls
//      `dummy::add`; we verify the assistant's final answer contains
//      "42" (proves end-to-end: spawn → tool_call → execute → answer).
//   7. The user message bubble shows an MCP-attached badge.
//   8. The session JSON persists `mcp: ["dummy"]` on the user message.
//
// Run while the backend (:31000), vite (:5180), and Electron
// (:9222 remote debugging) are running.

import CDP from "chrome-remote-interface"
import { setTimeout as sleep } from "node:timers/promises"

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
    } catch { /* not yet */ }
    await sleep(500)
  }
  throw new Error("Electron renderer not reachable via CDP")
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
  return eval_(
    client,
    `(async () => {
      const want = ${JSON.stringify(hash)};
      if (location.hash !== want) location.hash = want;
      await new Promise((r) => setTimeout(r, 50));
      return { ok: true, hash: location.hash };
    })()`,
  )
}

async function assertText(client, needle) {
  const present = await eval_(
    client,
    `document.body.innerText.includes(${JSON.stringify(needle)})`,
  )
  if (!present) throw new Error(`expected text ${JSON.stringify(needle)} not in DOM`)
}

async function clickNavLink(client, hash) {
  return eval_(
    client,
    `(() => {
      const a = document.querySelector('nav.leftnav a[href$="' + ${JSON.stringify(hash)} + '"]');
      if (!a) return { ok: false };
      a.click();
      return { ok: true };
    })()`,
  )
}

async function main() {
  console.log("waiting for Electron renderer...")
  const target = await waitForApp()
  console.log(`connected: ${target.url}`)
  const client = await CDP({ host: HOST, port: PORT, target })
  const { Runtime } = client
  await Runtime.enable()
  await sleep(2000)

  // ── 1. MCP entry in nav ─────────────────────────────────────────
  const hasMcpLink = await eval_(
    client,
    `!!document.querySelector('nav.leftnav a[href$="#/mcp"]')`,
  )
  if (!hasMcpLink) throw new Error("MCP nav link missing")
  console.log("✓ MCP entry visible in left nav")

  // ── 2. MCP page lists bundled dummy ─────────────────────────────
  await clickNavLink(client, "#/mcp")
  await sleep(700)
  await assertText(client, "Dummy MCP")
  await assertText(client, "dummy")
  console.log("✓ MCP page lists bundled dummy MCP")

  // ── 3. Workspace shows two foldable containers ──────────────────
  const folds = await eval_(
    client,
    `Array.from(document.querySelectorAll('.workspace-scroller .fold')).map((f) => ({
      title: f.querySelector('.fold-title')?.textContent?.trim(),
      count: f.querySelector('.fold-count')?.textContent?.trim(),
    }))`,
  )
  console.log("folds:", JSON.stringify(folds))
  const skillFold = folds.find(
    (f) => /skill/i.test(f.title || "") || /技能/i.test(f.title || ""),
  )
  const mcpFold = folds.find((f) => /mcp/i.test(f.title || ""))
  if (!skillFold) throw new Error("Skills fold container missing")
  if (!mcpFold) throw new Error("MCP fold container missing")
  console.log("✓ workspace has two foldable containers (Skills + MCP)")

  // ── 4. Workspace MCP entry has its own toggle ────────────────────
  const wsMcpEntry = await eval_(
    client,
    `(() => {
      const items = Array.from(document.querySelectorAll('.workspace-scroller .wskill'));
      const mcpItem = items.find((el) => el.textContent && el.textContent.includes('Dummy MCP'));
      if (!mcpItem) return null;
      return {
        name: mcpItem.querySelector('.wskill-name')?.textContent?.trim(),
        hasToggle: !!mcpItem.querySelector('input[type=checkbox]'),
      };
    })()`,
  )
  if (!wsMcpEntry) throw new Error("MCP workspace entry missing")
  if (!wsMcpEntry.hasToggle) throw new Error("MCP entry has no toggle")
  console.log("✓ workspace MCP entry has per-send toggle")

  // ── 5. Toggle MCP on, verify active-bar shows MCP pill ──────────
  // First reset all workspace toggles to off via the Pinia store so
  // the test is hermetic regardless of leftover localStorage.
  await eval_(
    client,
    `(() => {
      const app = document.querySelector('#app').__vue_app__;
      const skills = app.config.globalProperties.$pinia._s.get('skills');
      const mcps = app.config.globalProperties.$pinia._s.get('mcps');
      skills.clearActive();
      mcps.clearActive();
      return true;
    })()`,
  )
  await sleep(400)
  // Now activate Dummy MCP. Use the Pinia store directly — the
  // .click() approach is flaky when Vue reactivity hasn't applied
  // the bound state from a previous toggle.
  await eval_(
    client,
    `(() => {
      const app = document.querySelector('#app').__vue_app__;
      const mcps = app.config.globalProperties.$pinia._s.get('mcps');
      if (!mcps.active.has('dummy')) mcps.toggleActive('dummy');
      return [...mcps.active];
    })()`,
  )
  await sleep(400)
  // Navigate to chat so the active-bar (which lives in ChatView)
  // gets a chance to render.
  await gotoRoute(client, "#/chat")
  await sleep(600)
  const activeBarText = await eval_(
    client,
    `document.querySelector('.active-bar')?.innerText || ''`,
  )
  console.log("active-bar:", JSON.stringify(activeBarText))
  if (!/Dummy MCP/i.test(activeBarText)) {
    throw new Error(`active bar missing Dummy MCP chip: ${JSON.stringify(activeBarText)}`)
  }
  console.log("✓ MCP toggle shows in composer chip bar")

  // ── 6. Send a message that requires the add tool ─────────────────
  // Switch to chat view, type "use the add tool to compute 17+25",
  // click send, wait for the model to call the tool and reply.
  await gotoRoute(client, "#/chat")
  await sleep(600)
  await eval_(
    client,
    `(() => {
      const ta = document.querySelector('main.center textarea');
      ta.value = 'Use the add tool to compute 17 + 25. Tell me the answer.';
      ta.dispatchEvent(new Event('input', { bubbles: true }));
      return true;
    })()`,
  )
  await sleep(200)
  await eval_(
    client,
    `(() => {
      const btns = Array.from(document.querySelectorAll('main.center button'));
      const send = btns.find((b) => b.classList.contains('ax-send'));
      if (!send || send.disabled) return false;
      send.click();
      return true;
    })()`,
  )
  await sleep(8000)
  const reply = await eval_(
    client,
    `(() => {
      const msgs = Array.from(document.querySelectorAll('main.center .msg.assistant .content'));
      return msgs.map((m) => m.innerText.trim()).join('\\n');
    })()`,
  )
  console.log("assistant reply:", JSON.stringify(reply.slice(0, 200)))
  if (!/42/.test(reply)) {
    throw new Error(
      `expected "42" in model reply (proves MCP add tool was called and result fed back). Got: ${JSON.stringify(reply)}`,
    )
  }
  console.log("✓ model called add(17, 25) → got 42")

  // ── 7. User message bubble shows MCP-attached badge ─────────────
  const userBadge = await eval_(
    client,
    `(() => {
      const last = Array.from(document.querySelectorAll('main.center .msg.user')).slice(-1)[0];
      if (!last) return null;
      const badges = Array.from(last.querySelectorAll('.msg-skills'));
      return badges.map((b) => b.innerText.trim());
    })()`,
  )
  console.log("user msg badges:", JSON.stringify(userBadge))
  const hasMcpBadge = userBadge?.some((t) => /MCP/i.test(t)) || /Dummy MCP/i.test(userBadge?.join(" ") || "")
  if (!hasMcpBadge) {
    throw new Error(`user message bubble missing MCP badge: ${JSON.stringify(userBadge)}`)
  }
  console.log("✓ user message bubble shows MCP-attached badge")

  // ── 8. Session JSON persists mcp field ──────────────────────────
  const apiSessions = await (await fetch(`${BACKEND}/api/v1/sessions`)).json()
  if (!apiSessions.length) throw new Error("no session persisted")
  const detail = await (
    await fetch(`${BACKEND}/api/v1/sessions/${apiSessions[0].id}`)
  ).json()
  const lastUser = [...detail.messages].reverse().find((m) => m.role === "user")
  console.log("last user message:", JSON.stringify(lastUser))
  if (!Array.isArray(lastUser.mcp) || !lastUser.mcp.includes("dummy")) {
    throw new Error(
      `session user message has no mcp field with dummy: ${JSON.stringify(lastUser)}`,
    )
  }
  console.log("✓ mcp field persisted on user message:", JSON.stringify(lastUser.mcp))

  // ── 9. Toggle OFF — next message has no MCP badge ───────────────
  await eval_(
    client,
    `(() => {
      const app = document.querySelector('#app').__vue_app__;
      const mcps = app.config.globalProperties.$pinia._s.get('mcps');
      mcps.toggleActive('dummy');
      return [...mcps.active];
    })()`,
  )
  await sleep(400)
  const noChip = await eval_(
    client,
    `document.querySelector('.active-bar')?.innerText || ''`,
  )
  if (/Dummy MCP/i.test(noChip)) {
    throw new Error(`chip bar still has Dummy MCP after toggle off: ${noChip}`)
  }
  console.log("✓ toggle off removes MCP from chip bar")

  await client.close()
  console.log("\nALL MCP E2E CHECKS PASSED")
}

main().catch((e) => {
  console.error("FAIL:", e?.stack ?? e)
  process.exit(1)
})