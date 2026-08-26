import CDP from "chrome-remote-interface"

const sleep = (ms) => new Promise((r) => setTimeout(r, ms))
const client = await CDP({ host: "127.0.0.1", port: 9222 })
const { Runtime, Page } = client
await Runtime.enable()
await Page.enable()

let failures = 0
function check(name, ok, detail) {
  console.log(`  ${ok ? "PASS" : "FAIL"} ${name}${detail ? " — " + detail : ""}`)
  if (!ok) failures++
}

// === Sidebar question marks with tooltips on Skills / MCP / Tools ===
await Page.navigate({ url: "http://127.0.0.1:5180/?reload=1" })
await sleep(2500)
await Page.navigate({ url: "http://127.0.0.1:5180/#/chat" })
await sleep(2500)
const helps = await Runtime.evaluate({ expression: `(() => {
  const out = []
  for (const fold of [...document.querySelectorAll('.fold')]) {
    const title = fold.querySelector('.fold-title')?.textContent?.trim()
    const help = fold.querySelector('.fold-help')
    if (!title || !help) continue
    const svg = help.querySelector('svg')
    out.push({ title, hasIcon: !!svg, tip: help.getAttribute('title') || '' })
  }
  return out
})()`, returnByValue: true })
const byTitle = (t) => helps.result.value.find((x) => x.title === t) || {}
check("Skills fold has ? icon with tooltip", !!byTitle('技能')?.hasIcon && !!byTitle('技能')?.tip, JSON.stringify(byTitle('技能')))
check("MCP fold has ? icon with tooltip", !!byTitle('MCP')?.hasIcon && !!byTitle('MCP')?.tip, JSON.stringify(byTitle('MCP')))
check("Tools fold has ? icon with tooltip", !!byTitle('工具')?.hasIcon && !!byTitle('工具')?.tip, JSON.stringify(byTitle('工具')))

// === Right sidebar: edit-mode toggle + rename + bulk select/clear ===
// Seed the sidebar with at least 3 sessions so the per-row checkbox
// count check is independent of whatever state previous runs left.
await Runtime.evaluate({ expression: `
  (async () => {
    const { useSessionsStore } = await import('/src/stores/sessions.ts')
    const s = useSessionsStore()
    await s.refresh()
    while (s.items.length < 3) await s.create()
  })()
`, awaitPromise: true })
await sleep(800)
const sidebar = await Runtime.evaluate({ expression: `(() => {
  const list = document.querySelector('.sessions')
  if (!list) return { ok: false }
  const items = list.querySelectorAll('.list li')
  return {
    ok: true,
    count: items.length,
    hasBulkBar: !!list.querySelector('.bulk-bar'),
    hasClearBtn: !!list.querySelector('.ic-btn.danger'),
    hasEditBtn: !!list.querySelector('.ic-btn[title="Edit"], .ic-btn[title="\u7f16\u8f91"]'),
    hasNewBtn: !!list.querySelector('.new'),
    hasRenameTitle: items.length > 0 ? items[0].querySelector('.t')?.getAttribute('title') : '',
    rowCheckboxes: list.querySelectorAll('.row-check').length,
    hasDelButtons: !!items[0]?.querySelector('.del'),
  }
})()`, returnByValue: true })
check("normal mode: no bulk-bar visible", !sidebar.result.value.hasBulkBar)
check("normal mode: no row checkboxes visible", sidebar.result.value.rowCheckboxes === 0, `count=${sidebar.result.value.rowCheckboxes}`)
check("normal mode: edit button present", sidebar.result.value.hasEditBtn)
check("normal mode: new-session button present", sidebar.result.value.hasNewBtn)
check("normal mode: single-delete x button still present", sidebar.result.value.hasDelButtons)
check("session title shows rename hint", /rename|\u91cd\u547d\u540d/.test(sidebar.result.value.hasRenameTitle), sidebar.result.value.hasRenameTitle)

// === Click the edit button -> checkboxes appear ===
await Runtime.evaluate({ expression: `
  (async () => {
    const icBtns = [...document.querySelectorAll('.sessions .ic-btn')]
    const edit = icBtns.find(b => /edit|\u7f16\u8f91/i.test(b.title))
    edit?.click()
    await new Promise(r => setTimeout(r, 200))
    return { clicked: !!edit }
  })()
`, awaitPromise: true })
await sleep(400)
const editMode = await Runtime.evaluate({ expression: `(() => {
  const list = document.querySelector('.sessions')
  if (!list) return null
  return {
    hasBulkBar: !!list.querySelector('.bulk-bar'),
    rowCheckboxes: list.querySelectorAll('.row-check').length,
    hasDelButtons: !!list.querySelectorAll('.list .del').length,
    hasDoneBtn: !!list.querySelector('.ic-btn[title="Done"], .ic-btn[title="\u5b8c\u6210"]'),
    hasClearBtn: !!list.querySelector('.ic-btn.danger'),
    hasNewBtn: !!list.querySelector('.new'),
    hasEditBtn: !!list.querySelector('.ic-btn[title="Edit"], .ic-btn[title="\u7f16\u8f91"]'),
  }
})()`, returnByValue: true })
check("edit mode: bulk-bar appears", !!editMode?.result?.value?.hasBulkBar)
check("edit mode: row checkboxes appear", ((editMode?.result?.value?.rowCheckboxes ?? 0)) >= 3, `count=${editMode?.rowCheckboxes}`)
check("edit mode: per-row x delete buttons hidden", !editMode?.result?.value?.hasDelButtons)
check("edit mode: done button replaces edit button", editMode?.result?.value?.hasDoneBtn && !editMode?.result?.value?.hasEditBtn)
check("edit mode: clear-all button present", !!editMode?.result?.value?.hasClearBtn)
check("edit mode: new-session button hidden", !editMode?.result?.value?.hasNewBtn)

// Exit edit mode
await Runtime.evaluate({ expression: `
  (async () => {
    const btns = [...document.querySelectorAll('.sessions .ic-btn')]
    const done = btns.find(b => /done|\u5b8c\u6210/i.test(b.title))
    done?.click()
    await new Promise(r => setTimeout(r, 200))
    return { clicked: !!done }
  })()
`, awaitPromise: true })
await sleep(400)
const afterExit = await Runtime.evaluate({ expression: `(() => {
  const list = document.querySelector('.sessions')
  return {
    hasBulkBar: !!list.querySelector('.bulk-bar'),
    rowCheckboxes: list.querySelectorAll('.row-check').length,
    hasEditBtn: !!list.querySelector('.ic-btn[title="Edit"], .ic-btn[title="\u7f16\u8f91"]'),
    hasNewBtn: !!list.querySelector('.new'),
  }
})()`, returnByValue: true })
check("after exit edit mode: bulk-bar gone", !afterExit?.result?.value?.hasBulkBar)
check("after exit edit mode: checkboxes gone", (afterExit?.result?.value?.rowCheckboxes ?? 0) === 0)
check("after exit edit mode: edit button back", !!afterExit?.result?.value?.hasEditBtn)
check("after exit edit mode: new-session button back", !!afterExit?.result?.value?.hasNewBtn)

// === ProviderForm: models editor with model ID + display + max context ===
await Page.navigate({ url: "http://127.0.0.1:5180/#/providers" })
await sleep(1500)
await Runtime.evaluate({ expression: `
  (async () => {
    const { useProvidersStore } = await import('/src/stores/providers.ts')
    const ps = useProvidersStore()
    await ps.refresh()
    // Find the Edit button on the first card
    const btns = [...document.querySelectorAll('.card .btn-secondary')]
    btns[0]?.click()
  })()
`, awaitPromise: true })
await sleep(800)
const form = await Runtime.evaluate({ expression: `(() => {
  const modal = document.querySelector('.modal')
  if (!modal) return { modal: false }
  const rows = [...modal.querySelectorAll('.models-row')]
  return {
    modal: true,
    hasModelsBlock: !!modal.querySelector('.models-block'),
    rowCount: rows.length,
    hasCodeInput: rows.every(r => r.querySelector('.m-code')),
    hasDisplayInput: rows.every(r => r.querySelector('.m-display')),
    hasCtxInput: rows.every(r => r.querySelector('.m-ctx')),
    hasAddBtn: !!modal.querySelector('.add-model'),
  }
})()`, returnByValue: true })
check("ProviderForm: models editor block present", form.result.value.hasModelsBlock)
check("ProviderForm: model rows have code/display/ctx inputs", form.result.value.rowCount >= 1 && form.result.value.hasCodeInput && form.result.value.hasDisplayInput && form.result.value.hasCtxInput, `rows=${form.result.value.rowCount}`)
check("ProviderForm: add-model button present", form.result.value.hasAddBtn)

// === Context usage: circular SVG ring + percentage label ===
// Close the modal first
await Runtime.evaluate({ expression: `document.querySelector('.modal .btn-secondary')?.click()` })
await sleep(400)
await Page.navigate({ url: "http://127.0.0.1:5180/#/chat" })
await sleep(2500)
// Send a message so contextUsage is populated (it shows after 'done' event)
await Runtime.evaluate({ expression: `
  (async () => {
    const { useSessionsStore } = await import('/src/stores/sessions.ts')
    const s = useSessionsStore()
    await s.refresh()
    if (!s.currentId) await s.create()
  })()
`, awaitPromise: true })
await Runtime.evaluate({ expression: `
  (() => {
    const ta = document.querySelector('.composer-input')
    const setter = Object.getOwnPropertyDescriptor(window.HTMLTextAreaElement.prototype, 'value').set
    setter.call(ta, 'ctx meter probe')
    ta.dispatchEvent(new Event('input', { bubbles: true }))
  })()
` })
await sleep(200)
await Runtime.evaluate({ expression: `document.querySelector('.ax-send').click()` })
// Wait for context meter to appear (it appears once usage is reported)
let meter = null
for (let i = 0; i < 30; i++) {
  await sleep(1000)
  const r = await Runtime.evaluate({ expression: `(() => {
    const m = document.querySelector('.ctx-meter')
    if (!m) return null
    const ring = m.querySelector('.ctx-ring-fill')
    const label = m.querySelector('.ctx-meter-label')
    return {
      hasMeter: true,
      hasSvgRing: !!m.querySelector('svg.ctx-ring'),
      hasRingFill: !!ring,
      ringClass: ring?.getAttribute('class') || '',
      labelClass: label?.getAttribute('class') || '',
      labelText: label?.textContent?.trim() || '',
      dasharray: ring?.getAttribute('stroke-dasharray') || '',
    }
  })()`, returnByValue: true })
  meter = r.result.value
  if (meter?.hasRingFill) break
}
check("context meter renders SVG ring", !!meter?.hasSvgRing)
check("context meter shows percentage label", !!meter?.labelText, meter?.labelText)
check("context meter ring fill has warn class", /ctx-warn/.test(meter?.ringClass || ''), meter?.ringClass)

// === Streaming indicator: visible while waiting, gone after done ===
// Send another message to trigger streaming UI
await Runtime.evaluate({ expression: `
  (() => {
    const ta = document.querySelector('.composer-input')
    const setter = Object.getOwnPropertyDescriptor(window.HTMLTextAreaElement.prototype, 'value').set
    setter.call(ta, 'stream indicator probe')
    ta.dispatchEvent(new Event('input', { bubbles: true }))
  })()
` })
await sleep(200)
await Runtime.evaluate({ expression: `document.querySelector('.ax-send').click()` })
// Check immediately
await sleep(500)
const streamingBar = await Runtime.evaluate({ expression: `(() => {
  const bar = document.querySelector('.streaming-bar')
  if (!bar) return null
  return {
    visible: true,
    hasDots: !!bar.querySelector('.streaming-bar-dots'),
    dotsCount: bar.querySelectorAll('.streaming-bar-dots span').length,
    label: bar.querySelector('.streaming-bar-label')?.textContent?.trim() || '',
  }
})()`, returnByValue: true })
check("streaming bar appears during generation", !!streamingBar?.result?.value?.visible && streamingBar?.result?.value?.dotsCount === 3, JSON.stringify(streamingBar?.result?.value))
check("streaming bar shows localized label", !!streamingBar?.result?.value?.label && streamingBar?.result?.value?.label.length > 0, streamingBar?.result?.value?.label)

// Wait for stream to finish, then verify it disappears
for (let i = 0; i < 30; i++) {
  await sleep(1000)
  const r = await Runtime.evaluate({ expression: `document.querySelector('.streaming-bar')`, returnByValue: true })
  if (!r.result.value) { i = 30; break }
}
const after = await Runtime.evaluate({ expression: `document.querySelector('.streaming-bar')`, returnByValue: true })
check("streaming bar disappears after stream completes", !after.result.value)

// === Functional: rename a session via double-click ===
await Page.navigate({ url: "http://127.0.0.1:5180/#/chat" })
await sleep(2500)
// Make sure we have at least 3 sessions so the sidebar assertions
// above (count=3) don't depend on whatever state the previous run
// left behind.
await Runtime.evaluate({ expression: `
  (async () => {
    const { useSessionsStore } = await import('/src/stores/sessions.ts')
    const s = useSessionsStore()
    await s.refresh()
    while (s.items.length < 3) await s.create()
  })()
`, awaitPromise: true })
await sleep(800)
const renamed = await Runtime.evaluate({ expression: `
  (async () => {
    const { useSessionsStore } = await import('/src/stores/sessions.ts')
    const s = useSessionsStore()
    await s.refresh()
    const id = s.items[0].id
    const origTitle = s.items[0].title
    const li = document.querySelectorAll('.sessions .list li')[0]
    const title = li?.querySelector('.t')
    // simulate dblclick
    const evt = new MouseEvent('dblclick', { bubbles: true })
    title?.dispatchEvent(evt)
    await new Promise(r => setTimeout(r, 200))
    const input = li?.querySelector('.rename-input')
    if (!input) return { err: 'no input', origTitle }
    const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set
    setter.call(input, 'Renamed Test')
    input.dispatchEvent(new Event('input', { bubbles: true }))
    const enter = new KeyboardEvent('keydown', { key: 'Enter', bubbles: true })
    input.dispatchEvent(enter)
    await new Promise(r => setTimeout(r, 400))
    await s.refresh()
    const after = s.items.find(x => x.id === id)
    return { origTitle, newTitle: after?.title, id }
  })()
`, awaitPromise: true, returnByValue: true })
check("session rename persists", renamed.result.value?.newTitle === 'Renamed Test', JSON.stringify(renamed.result.value))

// === Functional: batch-delete selected sessions ===
const beforeCount = await Runtime.evaluate({ expression: `
  (async () => {
    const { useSessionsStore } = await import('/src/stores/sessions.ts')
    return (await (await fetch('/api/v1/sessions')).json()).length
  })()
`, awaitPromise: true, returnByValue: true })
const batch = await Runtime.evaluate({ expression: `
  (async () => {
    const { useSessionsStore } = await import('/src/stores/sessions.ts')
    const s = useSessionsStore()
    await s.refresh()
    // Capture current item count to restore if the test fails.
    const before = s.items.length
    if (before === 0) return { before: 0, after: 0, err: 'no sessions' }
    // Enter edit mode by clicking the edit button so the bulk-bar
    // and per-row checkboxes appear.
    const editBtn = [...document.querySelectorAll('.sessions .ic-btn')].find(b => /edit|编辑/i.test(b.title))
    editBtn?.click()
    await new Promise(r => setTimeout(r, 200))
    // Stub confirm() to always return true
    const origConfirm = window.confirm
    window.confirm = () => true
    try {
      await s.removeMany(s.items.map(x => x.id))
      await s.refresh()
      return { before, after: s.items.length }
    } catch (e) {
      return { before, err: e?.message || String(e) }
    } finally {
      window.confirm = origConfirm
    }
  })()
`, awaitPromise: true, returnByValue: true })
check("batch delete removes selected", batch.result.value?.after === 0, JSON.stringify(batch.result.value))

// === Functional: clear-all wipes everything (we already wiped above; verify store is empty + recreate) ===
const afterClear = await Runtime.evaluate({ expression: `
  (async () => {
    const { useSessionsStore } = await import('/src/stores/sessions.ts')
    const s = useSessionsStore()
    await s.refresh()
    return { count: s.items.length }
  })()
`, awaitPromise: true, returnByValue: true })
check("sessions empty after batch delete", afterClear.result.value?.count === 0, JSON.stringify(afterClear.result.value))

// Recreate one so the next test run has data
await Runtime.evaluate({ expression: `
  (async () => {
    const { useSessionsStore } = await import('/src/stores/sessions.ts')
    const s = useSessionsStore()
    await s.create()
  })()
`, awaitPromise: true })

await client.close()

await client.close()
console.log(failures ? `FAIL (${failures})` : "ALL CHECKS PASSED")
process.exit(failures ? 1 : 0)
