import CDP from "chrome-remote-interface"
import fs from "fs/promises"
const sleep = (ms) => new Promise((r) => setTimeout(r, ms))
const client = await CDP({ host: "127.0.0.1", port: 9222 })
const { Runtime, Page, Emulation } = client
await Runtime.enable()
await Page.enable()
await Emulation.setDeviceMetricsOverride({ width: 1280, height: 900, deviceScaleFactor: 2, mobile: false })
await Runtime.evaluate({ expression: `localStorage.setItem('mhc.onboarding.done','1')` })
await Runtime.evaluate({ expression: "location.reload()" })
await sleep(3500)

const sess = await fetch("http://127.0.0.1:31001/api/v1/sessions", {
  method: "POST", headers: { "content-type": "application/json" },
  body: JSON.stringify({
    title: "Demo chat",
    messages: [
      { role: "user", content: "Use the add tool to compute 17 + 25" },
      {
        role: "assistant",
        content: "Calling the **add** tool now.",
        tool_calls: [
          { call_id: "c1", name: "dummy-mcp::add", args: { a: 17, b: 25 }, status: "success", ok: true, result: "42" },
        ],
      },
    ],
    system_prompt: "",
  }),
}).then(r => r.json())

await Runtime.evaluate({
  expression: `(() => {
    const app = document.querySelector('#app').__vue_app__;
    const sessions = app.config.globalProperties.$pinia._s.get('sessions');
    const streams = app.config.globalProperties.$pinia._s.get('sessionStreams');
    sessions.select('${sess.id}');
    const s = streams.getState('${sess.id}');
    s.usage = { prompt_tokens: 128, completion_tokens: 32, total_tokens: 160 };
    return s.usage;
  })()`,
  awaitPromise: true,
})

await sleep(2000)
const shot = await Page.captureScreenshot({ format: "png" })
await fs.writeFile("C:/Users/Administrator/Documents/repo/mh-incubator/.logs/chat-final.png", Buffer.from(shot.data, "base64"))
console.log("saved")
await client.close()
