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

// === FIX 3: sidebar click on non-chat page should navigate to /chat ===
await Page.navigate({ url: "http://127.0.0.1:5180/#/providers" })
await sleep(1500)
const beforeNav = await Runtime.evaluate({ expression: `location.hash`, returnByValue: true })
check("started on /providers page", beforeNav.result.value === "#/providers", beforeNav.result.value)

const navResult = await Runtime.evaluate({ expression: `
  (async () => {
    const { useSessionsStore } = await import('/src/stores/sessions.ts')
    const s = useSessionsStore()
    await s.refresh()
    if (s.items.length < 2) await s.create()
    const targetId = s.items[1].id
    const beforeCurrent = s.currentId
    const lis = [...document.querySelectorAll('.sessions .list li')]
    if (lis.length < 2) return { err: 'fewer than 2 li in sidebar', count: lis.length }
    // Click the second li directly by index — titles are not unique.
    lis[1].click()
    await new Promise(r => setTimeout(r, 1000))
    return { targetId, beforeCurrent, afterCurrent: s.currentId, hash: location.hash }
  })()
`, awaitPromise: true, returnByValue: true })
check("sidebar click navigated to /chat from /providers", navResult.result.value.hash === "#/chat", navResult.result.value.hash)
check("sidebar click selected the clicked session", navResult.result.value.afterCurrent === navResult.result.value.targetId, `before=${navResult.result.value.beforeCurrent} after=${navResult.result.value.afterCurrent}`)

await Page.navigate({ url: "http://127.0.0.1:5180/#/chat" })
await sleep(2500)

// Instrument: count reasoning events arriving at the bus before sending
await Runtime.evaluate({ expression: `
  (async () => {
    const { useSessionStreamsStore } = await import('/src/stores/sessionStreams.ts')
    const streams = useSessionStreamsStore()
    window.__evCount = { reasoning: 0, chunk: 0 }
    // wrap subscribe to count
    const orig = streams.subscribe
    streams.subscribe = function(sid, fn) {
      const wrapped = (ev) => {
        if (ev.type === 'reasoning') window.__evCount.reasoning++
        if (ev.type === 'chunk') window.__evCount.chunk++
        fn(ev)
      }
      return orig.call(this, sid, wrapped)
    }
    return true
  })()
`, awaitPromise: true, returnByValue: true })

// create session + select + send
await Runtime.evaluate({ expression: `
  (async () => {
    const { useSessionsStore } = await import('/src/stores/sessions.ts')
    const s = useSessionsStore()
    await s.refresh()
    await s.create()
    return true
  })()
`, awaitPromise: true, returnByValue: true })
await sleep(800)
await Runtime.evaluate({ expression: `
  (() => {
    const ta = document.querySelector('.composer-input')
    const setter = Object.getOwnPropertyDescriptor(window.HTMLTextAreaElement.prototype, 'value').set
    setter.call(ta, '2*3=? simple')
    ta.dispatchEvent(new Event('input', { bubbles: true }))
  })()
`, returnByValue: true })
await sleep(200)
await Runtime.evaluate({ expression: `document.querySelector('.ax-send').click()` })

let last = null
for (let i = 0; i < 60; i++) {
  await sleep(1000)
  const r = await Runtime.evaluate({ expression: `(() => {
    const tl = document.querySelector('.msg.assistant .timeline')
    const th = tl?.querySelector('.tl-thinking')
    return {
      evs: window.__evCount,
      hasThinking: !!th,
      thLen: th?.querySelector('.tl-thinking-body')?.textContent?.length || 0,
      tlChildren: tl ? [...tl.children].map(c => c.className) : [],
      msgDone: !document.querySelector('.msg.assistant.pending'),
    }
  })()`, returnByValue: true })
  last = r.result.value
  if (last.evs.reasoning > 0 && last.msgDone) break
}
check("reasoning SSE events reached the frontend", (last?.evs.reasoning ?? 0) > 0, `count=${last?.evs.reasoning}`)
check("thinking block rendered in the timeline", !!last?.hasThinking, `len=${last?.thLen}`)
check("thinking precedes text", Array.isArray(last?.tlChildren) && last.tlChildren[0] === "tl-thinking", JSON.stringify(last?.tlChildren))

// Reload -> persistence check.
await Page.navigate({ url: "http://127.0.0.1:5180/#/chat" })
await sleep(2500)
const rp = await Runtime.evaluate({ expression: `
  (async () => {
    const { useSessionsStore } = await import('/src/stores/sessions.ts')
    const s = useSessionsStore()
    await s.refresh()
    if (s.items.length) await s.select(s.items[0].id)
    await new Promise(r => setTimeout(r, 1500))
    const tl = document.querySelector('.msg.assistant .timeline')
    const th = tl?.querySelector('.tl-thinking')
    return {
      hasThinking: !!th,
      thLen: th?.querySelector('.tl-thinking-body')?.textContent?.length || 0,
    }
  })()
`, awaitPromise: true, returnByValue: true })
check("thinking block survives reload", rp.result.value.hasThinking && rp.result.value.thLen > 0, `len=${rp.result.value.thLen}`)

// === FIX 2: user bubble shows attached-tools chip ===
const setup = await Runtime.evaluate({ expression: `
  (async () => {
    const { useSessionsStore } = await import('/src/stores/sessions.ts')
    const { useToolsStore } = await import('/src/stores/tools.ts')
    const { useMCPsStore } = await import('/src/stores/mcps.ts')
    const { useSkillsStore } = await import('/src/stores/skills.ts')
    const s = useSessionsStore()
    await s.refresh()
    await s.create()
    const tools = useToolsStore()
    const mcps = useMCPsStore()
    const skills = useSkillsStore()
    if (tools.items.length === 0) await tools.refresh()
    if (mcps.items.length === 0) await mcps.refresh()
    if (skills.items.length === 0) await skills.refresh()
    const skillSlug = (skills.items.find(x => x.slug === 'summarize') || skills.items[0]).slug
    const mcpSlug = (mcps.items.find(x => x.slug === 'dummy-mcp') || mcps.items[0]).slug
    const toolSlug = (tools.items.find(x => x.slug === 'now') || tools.items[0]).slug
    // setCurrentSession must run BEFORE toggle so toggle persists to the
    // right session's localStorage key.
    skills.setCurrentSession(s.currentId)
    mcps.setCurrentSession(s.currentId)
    tools.setCurrentSession(s.currentId)
    if (!skills.active.has(skillSlug)) skills.toggleActive(skillSlug)
    if (!mcps.active.has(mcpSlug)) mcps.toggleActive(mcpSlug)
    if (!tools.active.has(toolSlug)) tools.toggleActive(toolSlug)
    return {
      sid: s.currentId,
      skills: [...skills.active],
      mcps: [...mcps.active],
      tools: [...tools.active],
    }
  })()
`, awaitPromise: true, returnByValue: true })
console.log("attached:", setup.result.value)

await Runtime.evaluate({ expression: `
  (() => {
    const ta = document.querySelector('.composer-input')
    const setter = Object.getOwnPropertyDescriptor(window.HTMLTextAreaElement.prototype, 'value').set
    setter.call(ta, 'probe')
    ta.dispatchEvent(new Event('input', { bubbles: true }))
  })()
`, returnByValue: true })
await sleep(200)
await Runtime.evaluate({ expression: `document.querySelector('.ax-send').click()` })

let chips = null
for (let i = 0; i < 30; i++) {
  await sleep(1000)
  const r = await Runtime.evaluate({ expression: `(() => {
    const user = document.querySelector('.msg.user')
    if (!user) return null
    const all = [...user.querySelectorAll('.msg-skills')]
    const toolChip = all.find(c => c.classList.contains('msg-tools'))
    return {
      count: all.length,
      hasSkills: all.some(c => !c.classList.contains('msg-tools')),
      hasMCP: all.length >= 1,
      hasTools: !!toolChip,
      toolIcon: toolChip?.querySelector('.msg-skills-icon')?.textContent || '',
      toolPills: toolChip?.querySelectorAll('.msg-skills-pill').length || 0,
    }
  })()`, returnByValue: true })
  chips = r.result.value
  if (chips && chips.hasSkills && chips.hasMCP && chips.hasTools) break
}
check("user bubble shows attached-skills chip", !!chips?.hasSkills, `chips=${chips?.count}`)
check("user bubble shows attached-MCP chip", !!chips?.hasMCP)
check("user bubble shows attached-tools chip", !!chips?.hasTools, `icon=${chips?.toolIcon} pills=${chips?.toolPills}`)

await client.close()
console.log(failures ? `FAIL (${failures})` : "ALL REASONING CHECKS PASSED")
process.exit(failures ? 1 : 0)
