// Verify the graceful-shutdown wiring: window.__mhcFlush is exposed
// and the sessionStreams bus can be driven through a cancel-all
// cycle.

import CDP from "chrome-remote-interface"
const sleep = (ms) => new Promise((r) => setTimeout(r, ms))

const client = await CDP({ host: "127.0.0.1", port: 9222 })
const { Runtime, Page } = client
await Runtime.enable()
await Page.enable()

await Runtime.evaluate({
  expression: `localStorage.setItem('mhc.onboarding.done','1')`,
})
await Runtime.evaluate({ expression: "location.reload()" })
await sleep(3500)

const r = await Runtime.evaluate({
  expression: `(() => {
    const flush = window.__mhcFlush;
    return typeof flush === 'function' ? 'ok' : 'missing';
  })()`,
  returnByValue: true,
})
console.log("window.__mhcFlush:", r.result.value)

// Spawn a synthetic streaming session and verify flush returns its count
const sess = await fetch("http://127.0.0.1:31001/api/v1/sessions", {
  method: "POST",
  headers: { "content-type": "application/json" },
  body: JSON.stringify({ title: "shutdown test" }),
}).then((r) => r.json())

await Runtime.evaluate({
  expression: `(() => {
    const app = document.querySelector('#app').__vue_app__;
    const streams = app.config.globalProperties.$pinia._s.get('sessionStreams');
    const state = streams.getState('${sess.id}');
    state.streaming = true;
    state.assistantMessageId = 'm-1';
    state.assistantContent = 'about to die';
    return state.streaming;
  })()`,
  awaitPromise: true,
  returnByValue: true,
})

const r2 = await Runtime.evaluate({
  expression: `window.__mhcFlush()`,
  awaitPromise: true,
  returnByValue: true,
})
console.log("flush() returned:", JSON.stringify(r2.result.value))

const r3 = await Runtime.evaluate({
  expression: `(() => {
    const app = document.querySelector('#app').__vue_app__;
    const streams = app.config.globalProperties.$pinia._s.get('sessionStreams');
    const state = streams.getState('${sess.id}');
    return { streaming: state.streaming, cancelled: state.cancelled };
  })()`,
  returnByValue: true,
})
console.log("post-flush state:", JSON.stringify(r3.result.value))

await client.close()