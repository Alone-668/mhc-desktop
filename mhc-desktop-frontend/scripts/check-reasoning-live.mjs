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

await client.close()
console.log(failures ? `FAIL (${failures})` : "ALL REASONING CHECKS PASSED")
process.exit(failures ? 1 : 0)
