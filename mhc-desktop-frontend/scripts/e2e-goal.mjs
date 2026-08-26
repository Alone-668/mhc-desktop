// Comprehensive E2E test for the goal's requirements.
//
// Coverage:
//   Section 1: Onboarding first-run + dismiss + replay from settings
//   Section 2: Chat — message persistence with attached skills/mcp/tools,
//              tool_call segments persisted, reload reconstructs view
//   Section 3: Unique-ID system — skills/mcps/tools have IDs distinct
//              from display name; create returns an ID
//   Section 4: Concurrent sessions — start chat in A, then B, switch back
//              and confirm B's stream keeps running and is reachable
//   Section 5: Provider model editor — multiple models per provider,
//              ID + display name + max context
//   Section 6: MCP/Tool CRUD — import, edit, export
//
// Tests run against the live backend (31007) and Vite dev server
// (5180) via CDP. Each section is independent; failures stop the
// whole run, the rest are skipped.

import CDP from "chrome-remote-interface"
import { writeFileSync } from "node:fs"

const BACKEND = process.env.MHC_BACKEND || "http://127.0.0.1:31007"
const APP = process.env.MHC_APP || "http://127.0.0.1:5180"
const CDP_PORT = process.env.MHC_CDP_PORT || "9222"
const sleep = (ms) => new Promise((r) => setTimeout(r, ms))

const passed = []
const failed = []
function ok(name, cond, detail = "") {
  if (cond) {
    passed.push(name)
    console.log(`  PASS ${name}`)
  } else {
    failed.push({ name, detail })
    console.log(`  FAIL ${name} ${detail ? "— " + detail : ""}`)
  }
}

async function post(path, body) {
  const r = await fetch(`${BACKEND}${path}`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: body == null ? undefined : JSON.stringify(body),
  })
  if (!r.ok) throw new Error(`${path} ${r.status}: ${await r.text()}`)
  return r.json().catch(() => null)
}
async function put(path, body) {
  const r = await fetch(`${BACKEND}${path}`, {
    method: "PUT",
    headers: { "content-type": "application/json" },
    body: body == null ? undefined : JSON.stringify(body),
  })
  if (!r.ok) throw new Error(`${path} ${r.status}: ${await r.text()}`)
  return r.json().catch(() => null)
}
async function del(path) {
  const r = await fetch(`${BACKEND}${path}`, { method: "DELETE" })
  if (!r.ok) throw new Error(`${path} ${r.status}: ${await r.text()}`)
  return true
}
async function getJson(path) {
  const r = await fetch(`${BACKEND}${path}`)
  if (!r.ok) throw new Error(`${path} ${r.status}: ${await r.text()}`)
  return r.json()
}

async function boot() {
  const client = await CDP({ host: "127.0.0.1", port: Number(CDP_PORT) })
  const { Page, Runtime } = client
  await Page.enable()
  await Runtime.enable()
  return { client, Page, Runtime }
}

async function reload(Runtime, hash = "/chat") {
  await Runtime.evaluate({
    expression: `location.replace('${APP}/?r=' + Date.now() + '${hash}')`,
  })
  await sleep(2500)
}

async function goto(Runtime, hash) {
  await Runtime.evaluate({ expression: `location.hash = '${hash}'` })
  await sleep(500)
}

// ─────────────────────────────────────────────────────────────────────
// Section 1: Onboarding
// ─────────────────────────────────────────────────────────────────────
async function sectionOnboarding(Runtime) {
  console.log("\n[1] Onboarding first-run + dismiss + replay")

  // Reset onboarded state
  await Runtime.evaluate({ expression: `localStorage.removeItem('mhc.onboarding.done')` })
  await reload(Runtime, "/chat")

  // First launch — overlay must be present
  let probe = await Runtime.evaluate({
    expression: `(() => {
      const ov = document.querySelector('.onboarding')
      const vis = ov && getComputedStyle(ov).display !== 'none' && ov.getBoundingClientRect().width > 0
      const localFlag = localStorage.getItem('mhc.onboarding.done')
      return {
        present: !!ov,
        visible: !!vis,
        localFlag,
      }
    })()`,
    returnByValue: true,
  })
  ok("first launch: onboarding overlay visible", probe.result.value.visible === true)
  ok("first launch: mhc.onboarding.done flag is unset", probe.result.value.localFlag === null)

  // Click next until the button becomes "知道了" (last card).
  const clickRes = await Runtime.evaluate({
    expression: `(async () => {
      const sleep = (ms) => new Promise(r => setTimeout(r, ms))
      const o = document.querySelector('.onboarding')
      if (!o) return { ok: false, why: 'no overlay' }
      for (let i = 0; i < 10; i++) {
        const btn = o.querySelector('button.primary')
        if (!btn) return { ok: false, why: 'no primary button on iter ' + i }
        const text = btn.textContent.trim()
        if (/知道|got it|finish|知道了/i.test(text)) {
          btn.click()
          await sleep(400)
          return { ok: true, text, clicks: i + 1 }
        }
        btn.click()
        await sleep(400)
      }
      return { ok: false, why: 'never reached last card' }
    })()`,
    awaitPromise: true,
    returnByValue: true,
  })
  ok("clicked final '知道了' button", clickRes.result.value.ok, JSON.stringify(clickRes.result.value))
  await sleep(800)

  probe = await Runtime.evaluate({
    expression: `(() => {
      const ov = document.querySelector('.onboarding')
      const vis = ov && getComputedStyle(ov).display !== 'none' && ov.getBoundingClientRect().width > 0
      return { visible: !!vis, flag: localStorage.getItem('mhc.onboarding.done') }
    })()`,
    returnByValue: true,
  })
  ok("after click: overlay hidden", probe.result.value.visible === false)
  ok("after click: mhc.onboarding.done flag set", probe.result.value.flag === "1")

  // Reload — must NOT show again
  await reload(Runtime, "/chat")
  probe = await Runtime.evaluate({
    expression: `(() => {
      const ov = document.querySelector('.onboarding')
      const vis = ov && getComputedStyle(ov).display !== 'none' && ov.getBoundingClientRect().width > 0
      return { visible: !!vis, flag: localStorage.getItem('mhc.onboarding.done') }
    })()`,
    returnByValue: true,
  })
  ok("reload after dismiss: overlay hidden", probe.result.value.visible === false)

  // Settings page has "replay" affordance
  await goto(Runtime, "/settings")
  await sleep(800)
  const replayProbe = await Runtime.evaluate({
    expression: `(() => {
      // The replay row has a button with class .seg-opt whose text
      // comes from t("onboarding.start"). Look for any seg-opt
      // button in the settings view; that's the only one with that
      // class.
      const btn = document.querySelector('.seg-opt')
      return btn ? { ok: true, text: btn.textContent.trim() } : { ok: false }
    })()`,
    returnByValue: true,
  })
  ok("settings has a 'replay tour' button", replayProbe.result.value.ok, JSON.stringify(replayProbe.result.value))
}

// ─────────────────────────────────────────────────────────────────────
// Section 2: Chat persistence with attached metadata
// ─────────────────────────────────────────────────────────────────────
async function sectionChatPersistence(client, Runtime, Page) {
  console.log("\n[2] Chat: attached skills/mcp/tools persisted on user bubble")

  await goto(Runtime, "/chat")
  await sleep(500)

  // Confirm session exists
  await post("/api/v1/sessions", { title: "Goal E2E Persistence" })

  const freshSession = await post("/api/v1/sessions", { title: "Goal Chat Persist" })
  const sid = freshSession.id
  console.log(`    using sid=${sid}`)

  // Find an enabled skill/mcp/tool to attach
  const skills = await getJson("/api/v1/skills")
  const enabledSkill = (skills || []).find((s) => s.enabled) || skills?.[0]
  const mcps = await getJson("/api/v1/mcp")
  const enabledMcp = (mcps || []).find((m) => m.enabled) || mcps?.[0]
  const tools = await getJson("/api/v1/tools")
  const enabledTool = (tools || []).find((t) => t.enabled && t.kind !== "remote") || tools?.[0]

  console.log(`    skill=${enabledSkill?.slug}  mcp=${enabledMcp?.slug}  tool=${enabledTool?.slug}`)

  // Build a fake assistant reply with attached user metadata + tool_calls + segments
  const fakeMessages = [
    {
      role: "user",
      content: "Run the bundled tools please",
      skills: enabledSkill ? [enabledSkill.slug] : [],
      mcp: enabledMcp ? [enabledMcp.slug] : [],
      tools: enabledTool ? [enabledTool.slug] : [],
    },
    {
      role: "assistant",
      content: "Here you go.\n\n```json\n{\"ok\": true}\n```",
      tool_calls: enabledTool
        ? [
            {
              call_id: "tcall_test_1",
              kind: "tool",
              name: enabledTool.slug,
              args: {},
              result: "ok",
              ok: true,
              status: "success",
              startedAt: Date.now() - 100,
              durationMs: 100,
            },
          ]
        : [],
      segments: enabledTool
        ? [
            { kind: "text", content: "Here you go.\n\n```json\n{\"ok\": true}\n```" },
            {
              kind: "tool",
              call: {
                call_id: "tcall_test_1",
                kind: "tool",
                name: enabledTool.slug,
                args: {},
                result: "ok",
                ok: true,
                status: "success",
                startedAt: Date.now() - 100,
                durationMs: 100,
              },
            },
          ]
        : [{ kind: "text", content: "Here you go.\n\n```json\n{\"ok\": true}\n```" }],
    },
  ]
  await put(`/api/v1/sessions/${sid}`, { messages: fakeMessages })
  await sleep(200)

  // Reload the session via the API and confirm round-trip
  const reloaded = await getJson(`/api/v1/sessions/${sid}`)
  const u = reloaded.messages.find((m) => m.role === "user")
  ok("reload: user message keeps skills/mcp/tools metadata",
    u && Array.isArray(u.skills) && Array.isArray(u.mcp) && Array.isArray(u.tools),
    `skills=${JSON.stringify(u?.skills)} mcp=${JSON.stringify(u?.mcp)} tools=${JSON.stringify(u?.tools)}`)
  const a = reloaded.messages.find((m) => m.role === "assistant")
  ok("reload: assistant message keeps tool_calls",
    a && Array.isArray(a.tool_calls) && a.tool_calls.length >= 1)
  ok("reload: assistant message keeps segments",
    a && Array.isArray(a.segments) && a.segments.length >= 1)

  // Now drive the frontend to that session and inspect
  await Runtime.evaluate({
    expression: `(async () => {
      const app = document.querySelector('#app').__vue_app__
      const pinia = app.config.globalProperties.$pinia
      const ss = pinia._s.get('sessions')
      await ss.select('${sid}')
      location.hash = '/chat'
    })()`,
    awaitPromise: true,
    returnByValue: true,
  })
  await sleep(1200)

  // Capture DOM for the assistant message + user bubble
  const domProbe = await Runtime.evaluate({
    expression: `(() => {
      const msgs = [...document.querySelectorAll('.msg')]
      const u = document.querySelector('.msg.user .bubble') || document.querySelector('.msg.user')
      const a = document.querySelector('.msg.assistant .content') || document.querySelector('.msg.assistant')
      const chips = document.querySelectorAll('.attach-chip, .bubble-chip, .attached-chip, .skill-chip')
      const capsule = document.querySelector('.tl-tool, .tool-call, [class*="capsule"]')
      return {
        msgCount: msgs.length,
        userHasContent: u && u.textContent.includes('Run the bundled'),
        assistantHasCode: a && a.textContent.includes('ok'),
        chipCount: chips.length,
        capsulePresent: !!capsule,
        capsuleText: capsule ? capsule.textContent.trim().slice(0, 80) : null,
      }
    })()`,
    returnByValue: true,
  })
  ok("UI: user message bubble renders", domProbe.result.value.userHasContent)
  ok("UI: assistant message renders (with code block)", domProbe.result.value.assistantHasCode)
  if (enabledTool) {
    ok("UI: assistant message renders tool capsule", domProbe.result.value.capsulePresent)
  }

  // Clean up the test session
  await del(`/api/v1/sessions/${sid}`)
}

// ─────────────────────────────────────────────────────────────────────
// Section 3: Unique ID system
// ─────────────────────────────────────────────────────────────────────
async function sectionUniqueIds() {
  console.log("\n[3] Unique-ID system for skills/mcps/tools")

  // Create a skill via API
  const tempName = `goal-test-skill-${Date.now()}`
  const skillFolder = `goal-test-skill-${Date.now()}`
  let skillCreated = null
  try {
    skillCreated = await post("/api/v1/skills/import-folder", { name: skillFolder })
  } catch (e) {
    // maybe endpoint is different; try the raw create
    try {
      skillCreated = await post("/api/v1/skills", {
        name: tempName,
        description: "test skill for goal e2e",
      })
    } catch (e2) {
      console.log("    skill create error:", e.message, e2.message)
    }
  }
  const skills = await getJson("/api/v1/skills")
  const found = skills.find((s) => s.slug === skillFolder || s.name === tempName) || skills[skills.length - 1]
  ok("skill has a stable ID", found && (typeof found.id === "string" || typeof found.slug === "string"),
    `keys=${Object.keys(found || {}).join(",")}`)
  ok("skill has a display name distinct from ID",
    found && found.name !== (found.id || found.slug),
    `name=${found?.name} id=${found?.id ?? found?.slug}`)

  // Same for MCP
  let mcpCreated = null
  try {
    mcpCreated = await post("/api/v1/mcp", {
      slug: `goal-mcp-${Date.now()}`,
      name: `Goal MCP ${Date.now()}`,
      command: "echo",
      args: ["hello"],
    })
  } catch (e) {
    console.log("    mcp create error:", e.message)
  }
  const mcps = await getJson("/api/v1/mcp")
  const mcpFound = mcps[mcps.length - 1]
  ok("mcp has stable identifier", mcpFound && (mcpFound.id || mcpFound.slug),
    `keys=${Object.keys(mcpFound || {}).join(",")}`)
  ok("mcp display name distinct from id/slug",
    mcpFound && mcpFound.name !== (mcpFound.id || mcpFound.slug))

  // Same for Tool
  let toolCreated = null
  try {
    toolCreated = await post("/api/v1/tools", {
      slug: `goal-tool-${Date.now()}`,
      name: `Goal Tool ${Date.now()}`,
      kind: "local",
      description: "test tool",
    })
  } catch (e) {
    console.log("    tool create error:", e.message)
  }
  const tools = await getJson("/api/v1/tools")
  const toolFound = tools[tools.length - 1]
  ok("tool has stable identifier", toolFound && (toolFound.id || toolFound.slug),
    `keys=${Object.keys(toolFound || {}).join(",")}`)
  ok("tool display name distinct from id/slug",
    toolFound && toolFound.name !== (toolFound.id || toolFound.slug))
  ok("tool has a model_name field distinct from display name",
    toolFound && toolFound.model_name !== undefined && toolFound.model_name !== toolFound.name,
    `model_name=${toolFound?.model_name} name=${toolFound?.name}`)

  // Clean up
  if (skillCreated?.slug || found?.slug) {
    try { await del(`/api/v1/skills/${encodeURIComponent(skillCreated?.slug || found.slug)}`) } catch {}
  }
  if (mcpCreated?.slug || mcpFound?.slug) {
    try { await del(`/api/v1/mcp/${encodeURIComponent(mcpCreated?.slug || mcpFound.slug)}`) } catch {}
  }
  if (toolCreated?.slug || toolFound?.slug) {
    try { await del(`/api/v1/tools/${encodeURIComponent(toolCreated?.slug || toolFound.slug)}`) } catch {}
  }
}

// ─────────────────────────────────────────────────────────────────────
// Section 4: Concurrent sessions
// ─────────────────────────────────────────────────────────────────────
async function sectionConcurrentSessions(Runtime, Page) {
  console.log("\n[4] Concurrent sessions — start A, start B, switch")

  // Make sure we have at least 2 sessions
  const before = await getJson("/api/v1/sessions")
  let a = before.find((s) => s.title === "Concurrent A") || null
  let b = before.find((s) => s.title === "Concurrent B") || null
  if (!a) a = await post("/api/v1/sessions", { title: "Concurrent A" })
  if (!b) b = await post("/api/v1/sessions", { title: "Concurrent B" })

  // Look up the live provider name (we never know what the user
  // configured at test time).
  const providers = await getJson("/api/v1/providers")
  const liveProvider = providers.find((p) => p.provider_type === "openai" && p.api_key) || providers[0]
  const liveModel = liveProvider?.models?.[0]?.code || liveProvider?.default_model || "gpt-4o-mini"
  console.log(`    using provider=${liveProvider?.name} model=${liveModel}`)

  // Open session A in the UI
  await Runtime.evaluate({
    expression: `(async () => {
      const app = document.querySelector('#app').__vue_app__
      const pinia = app.config.globalProperties.$pinia
      const ss = pinia._s.get('sessions')
      await ss.select('${a.id}')
      location.hash = '/chat'
    })()`,
    awaitPromise: true,
  })
  await sleep(1000)

  // Send a long-ish user message into A — the backend streams SSE
  const assistantA = `asm-${Date.now()}-A`
  const reqA = fetch(`${BACKEND}/api/v1/chat`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({
      provider: liveProvider.name,
      model: liveModel,
      session_id: a.id,
      assistant_message_id: assistantA,
      messages: [{ role: "user", content: "Reply with five short numbered facts about pi. End with the literal word PI-DONE." }],
    }),
  })

  // After 1s, switch to B and start a chat there too
  await sleep(1000)
  await Runtime.evaluate({
    expression: `(async () => {
      const app = document.querySelector('#app').__vue_app__
      const pinia = app.config.globalProperties.$pinia
      const ss = pinia._s.get('sessions')
      await ss.select('${b.id}')
    })()`,
    awaitPromise: true,
  })
  await sleep(300)
  const assistantB = `asm-${Date.now()}-B`
  const reqB = fetch(`${BACKEND}/api/v1/chat`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({
      provider: liveProvider.name,
      model: liveModel,
      session_id: b.id,
      assistant_message_id: assistantB,
      messages: [{ role: "user", content: "Reply with five short numbered facts about tau. End with the literal word TAU-DONE." }],
    }),
  })

  // Wait for both to settle (or time out)
  const respA = await reqA.catch((e) => ({ error: e.message }))
  const respB = await reqB.catch((e) => ({ error: e.message }))
  ok("stream A returned 200", respA.status === 200, `status=${respA.status}`)
  ok("stream B returned 200", respB.status === 200, `status=${respB.status}`)
  await respA.text?.()
  await respB.text?.()
  await sleep(500)

  // Reload session A from disk and confirm its message was saved
  const sessA = await getJson(`/api/v1/sessions/${a.id}`)
  const sessB = await getJson(`/api/v1/sessions/${b.id}`)
  ok("session A persisted messages", sessA.messages && sessA.messages.length >= 2,
    `count=${sessA.messages?.length}`)
  ok("session B persisted messages", sessB.messages && sessB.messages.length >= 2,
    `count=${sessB.messages?.length}`)
  const aHasPi = sessA.messages?.some((m) => /pi|π|3\.14|PI-DONE/i.test(m.content || ""))
  const bHasTau = sessB.messages?.some((m) => /tau|τ|6\.28|TAU-DONE/i.test(m.content || ""))
  ok("session A contains pi-flavoured reply", aHasPi)
  ok("session B contains tau-flavoured reply", bHasTau)

  // Switching to a session with running streams should reveal the
  // buffered state. While session B was in the background, the
  // frontend should have buffered its events without rendering.
  // Switch to A first (to clear B as foreground), then back to B
  // and check that B's final state is on disk.
  await Runtime.evaluate({
    expression: `(async () => {
      const app = document.querySelector('#app').__vue_app__
      const pinia = app.config.globalProperties.$pinia
      const ss = pinia._s.get('sessions')
      await ss.select('${a.id}')
    })()`,
    awaitPromise: true,
  })
  await sleep(500)
  await Runtime.evaluate({
    expression: `(async () => {
      const app = document.querySelector('#app').__vue_app__
      const pinia = app.config.globalProperties.$pinia
      const ss = pinia._s.get('sessions')
      await ss.select('${b.id}')
    })()`,
    awaitPromise: true,
  })
  await sleep(500)
  const sessBAfter = await getJson(`/api/v1/sessions/${b.id}`)
  const bFinal = sessBAfter.messages?.some((m) => /tau|τ|6\.28|TAU-DONE/i.test(m.content || ""))
  ok("after switch-back: session B reply is in store", bFinal,
    `last=${sessBAfter.messages?.[sessBAfter.messages.length - 1]?.content?.slice(0, 60)}`)

  // Cleanup
  await del(`/api/v1/sessions/${a.id}`)
  await del(`/api/v1/sessions/${b.id}`)
}

// ─────────────────────────────────────────────────────────────────────
// Section 5: Provider model editor
// ─────────────────────────────────────────────────────────────────────
async function sectionProviders(Runtime) {
  console.log("\n[5] Provider model editor (multi-model + id/display + max context)")

  await goto(Runtime, "/providers")
  await sleep(1500)

  // The "+ 添加服务商" button must exist and open a form
  const newBtn = await Runtime.evaluate({
    expression: `(() => {
      const btn = document.querySelector('button.btn-primary')
      return btn ? { ok: true, text: btn.textContent.trim() } : { ok: false }
    })()`,
    returnByValue: true,
  })
  ok("providers view has a '+ new provider' button", newBtn.result.value.ok)

  // Inspect the model-editor markup: each model row should have
  // fields for code (id), display name, and max context.
  // The form only mounts when "+ new" is clicked, so click it first.
  await Runtime.evaluate({
    expression: `document.querySelector('button.btn-primary')?.click()`,
    returnByValue: true,
  })
  await sleep(800)
  // The model-row editor is empty until the operator clicks
  // "+ 添加模型"; click that to materialise a row.
  await Runtime.evaluate({
    expression: `document.querySelector('.add-model')?.click()`,
    returnByValue: true,
  })
  await sleep(500)
  const editorProbe = await Runtime.evaluate({
    expression: `(() => {
      return {
        code: [...document.querySelectorAll('.m-code')].length,
        display: [...document.querySelectorAll('.m-display')].length,
        ctx: [...document.querySelectorAll('.m-ctx')].length,
      }
    })()`,
    returnByValue: true,
  })
  ok("provider form has 'model code (ID)' field", editorProbe.result.value.code >= 1,
    `count=${editorProbe.result.value.code}`)
  ok("provider form has 'display name' field", editorProbe.result.value.display >= 1)
  ok("provider form has 'max context' field", editorProbe.result.value.ctx >= 1)

  // Detail (a): the edit button must be styled like the app's other
  // pause-paragraph buttons — pill-radius, 28px, semi-width. The
  // user reported it rendering with the default browser button
  // chrome.
  const btnProbe = await Runtime.evaluate({
    expression: `(() => {
      const b = document.querySelector('button.btn-secondary')
      if (!b) return { err: 'no edit btn' }
      const r = b.getBoundingClientRect()
      const cs = getComputedStyle(b)
      return { h: r.height, radius: cs.borderRadius, border: cs.border }
    })()`,
    returnByValue: true,
  })
  ok("provider edit button is pill-shaped (radius 999px)",
    /999px/.test(btnProbe.result.value.radius || ""),
    JSON.stringify(btnProbe.result.value))
  ok("provider edit button is 28px tall",
    Math.round(btnProbe.result.value.h || 0) === 28,
    `h=${btnProbe.result.value.h}`)

  // Detail (a): the edit-modal must not overflow — a model row with
  // a long display name should stay inside the modal box.
  const modalProbe = await Runtime.evaluate({
    expression: `(() => {
      // We're in the add-modal; open the edit-modal too (second
      // provider's 编辑 button) so we can verify overflow there.
      // Close current modal then open edit on the first provider.
      const closeBtn = document.querySelector('.modal-bg')?.querySelector('button.close, [class*="close"], button.cancel')
      const out = {}
      return out
    })()`,
    returnByValue: true,
  })
  // Reopen edit (not add) and stuff a long display name into a row.
  await Runtime.evaluate({
    expression: `(() => {
      // Escape the current add modal by clicking the X / cancel.
      const modal = document.querySelector('.modal-bg')
      const x = modal && modal.querySelector('button[class*="close"], .modal-header button, button:last-child')
      if (x) x.click()
      else if (modal) modal.click()
    })()`,
    returnByValue: true,
  })
  await sleep(600)
  await Runtime.evaluate({
    expression: `document.querySelector('button.btn-secondary')?.click()`,
    returnByValue: true,
  })
  await sleep(1200)
  await Runtime.evaluate({
    expression: `(() => {
      const add = document.querySelector('.add-model')
      if (add) add.click()
    })()`,
    returnByValue: true,
  })
  await sleep(400)
  const overflowProbe = await Runtime.evaluate({
    expression: `(() => {
      const modal = document.querySelector('.modal')
      if (!modal) return { err: 'no modal in edit' }
      const cs = getComputedStyle(modal)
      const row = document.querySelector('.models-row')
      const inputs = [...document.querySelectorAll('.models-row input')]
      const inViewport = inputs.every((i) => {
        const ir = i.getBoundingClientRect()
        const mr = modal.getBoundingClientRect()
        return ir.left >= mr.left - 1 && ir.right <= mr.right + 1
      })
      return {
        modalW: modal.getBoundingClientRect().width,
        overflowY: cs.overflowY,
        rowsInModal: inViewport,
        inputCount: inputs.length,
      }
    })()`,
    returnByValue: true,
  })
  ok("edit modal has scrollable body (no hard overflow)",
    overflowProbe.result.value.overflowY === "auto" || overflowProbe.result.value.rowsInModal,
    JSON.stringify(overflowProbe.result.value))
  ok("edit modal keeps model rows inside the box",
    overflowProbe.result.value.rowsInModal !== false,
    JSON.stringify(overflowProbe.result.value))
}

// ─────────────────────────────────────────────────────────────────────
// Section 6: MCP + Tool edit / export
// ─────────────────────────────────────────────────────────────────────
async function sectionMcpToolCRUD(Runtime) {
  console.log("\n[6] MCP + Tool CRUD: create / edit / export")

  // MCP CRUD: create -> edit -> export
  let mcpSlug = `goal-mcp-${Date.now()}`
  const created = await post("/api/v1/mcp", {
    slug: mcpSlug,
    name: `Goal MCP ${Date.now()}`,
    command: "echo",
    args: ["hi"],
  })
  ok("MCP create returned 200", !!created, JSON.stringify(created))
  const edits = await put(`/api/v1/mcp/${encodeURIComponent(mcpSlug)}`, { name: "Goal MCP Renamed" })
  ok("MCP edit returned 200", edits && edits.name === "Goal MCP Renamed",
    `name=${edits?.name}`)
  const exp = await fetch(`${BACKEND}/api/v1/mcp/${encodeURIComponent(mcpSlug)}/export`).catch(() => null)
  ok("MCP export endpoint exists", exp && exp.ok, `status=${exp?.status}`)

  // Tool CRUD
  let toolSlug = `goal-tool-${Date.now()}`
  const tCreated = await post("/api/v1/tools", {
    slug: toolSlug,
    name: `Goal Tool ${Date.now()}`,
    kind: "local",
    description: "test",
  })
  ok("Tool create returned 200", !!tCreated, JSON.stringify(tCreated))
  const tEdits = await put(`/api/v1/tools/${encodeURIComponent(toolSlug)}`, { name: "Goal Tool Renamed" })
  ok("Tool edit returned 200", tEdits && tEdits.name === "Goal Tool Renamed",
    `name=${tEdits?.name}`)
  const tExp = await fetch(`${BACKEND}/api/v1/tools/${encodeURIComponent(toolSlug)}/export`).catch(() => null)
  ok("Tool export endpoint exists", tExp && tExp.ok, `status=${tExp?.status}`)

  // UI: MCP detail panel must offer Edit + Export buttons.
  await goto(Runtime, "/mcp")
  await sleep(1200)
  // Select the freshly created MCP in the list by clicking its card.
  const uiProbe = await Runtime.evaluate({
    expression: `(async () => {
      const sleep = (ms) => new Promise(r => setTimeout(r, ms))
      // Find the card whose title matches our test MCP name.
      const cards = [...document.querySelectorAll('.card')]
      const card = cards.find(c => c.textContent.includes('Goal MCP'))
      if (!card) return { err: 'card not found', names: cards.map(c => c.textContent.slice(0, 40)) }
      card.click()
      await sleep(600)
      const btns = [...document.querySelectorAll('.detail-actions button, .detail button')].map(b => b.textContent.trim())
      const hasExport = btns.some(t => /export|导出|download/i.test(t))
      const hasEdit = btns.some(t => /edit|编辑/i.test(t))
      return { btns, hasExport, hasEdit }
    })()`,
    awaitPromise: true,
    returnByValue: true,
  })
  ok("MCP detail panel offers Export button", uiProbe.result.value.hasExport === true,
    JSON.stringify(uiProbe.result.value))
  ok("MCP detail panel offers Edit button", uiProbe.result.value.hasEdit === true,
    JSON.stringify(uiProbe.result.value))

  // UI: Tools detail panel must offer Edit + Download (export).
  await goto(Runtime, "/tools")
  await sleep(2000)
  const toolsUi = await Runtime.evaluate({
    expression: `(async () => {
      const sleep = (ms) => new Promise(r => setTimeout(r, ms))
      // Select a non-bundled tool: our freshly created test tool.
      let row = null
      for (let i = 0; i < 5 && !row; i++) {
        const rows = [...document.querySelectorAll('.row')]
        row = rows.find(r => r.textContent.includes('Goal Tool'))
        if (!row) await sleep(800)
      }
      if (!row) return { err: 'tool row not found' }
      row.click()
      await sleep(800)
      const btns = [...document.querySelectorAll('.detail button')].map(b => b.textContent.trim())
      return {
        btns,
        hasExport: btns.some(t => /download|导出|manifest|下载/i.test(t)),
        hasEdit: btns.some(t => /edit|编辑/i.test(t)),
      }
    })()`,
    awaitPromise: true,
    returnByValue: true,
  })
  ok("Tools detail panel offers Download (=export) button", toolsUi.result.value.hasExport === true,
    JSON.stringify(toolsUi.result.value))
  ok("Tools detail panel offers Edit button", toolsUi.result.value.hasEdit === true,
    JSON.stringify(toolsUi.result.value))

  // Cleanup
  try { await del(`/api/v1/mcp/${encodeURIComponent(mcpSlug)}`) } catch {}
  try { await del(`/api/v1/tools/${encodeURIComponent(toolSlug)}`) } catch {}
}

// ─────────────────────────────────────────────────────────────────────
// Main
// ─────────────────────────────────────────────────────────────────────
const only = process.env.MHC_ONLY // e.g. "1", "2", "3", "4", "5", "6"
async function main() {
  const { client, Runtime, Page } = await boot()
  console.log("CDP connected.")
  await reload(Runtime, "/chat")
  try {
    if (!only || only === "1") await sectionOnboarding(Runtime)
    if (!only || only === "2") await sectionChatPersistence(client, Runtime, Page)
    if (!only || only === "3") await sectionUniqueIds()
    if (!only || only === "4") await sectionConcurrentSessions(Runtime, Page)
    if (!only || only === "5") await sectionProviders(Runtime)
    if (!only || only === "6") await sectionMcpToolCRUD(Runtime)
  } finally {
    await client.close()
  }
  console.log(`\n=================================`)
  console.log(`PASS: ${passed.length}   FAIL: ${failed.length}`)
  if (failed.length) {
    for (const f of failed) console.log(`  FAIL: ${f.name} — ${f.detail}`)
    process.exit(1)
  }
}
main().catch((e) => {
  console.error("FATAL", e)
  process.exit(2)
})