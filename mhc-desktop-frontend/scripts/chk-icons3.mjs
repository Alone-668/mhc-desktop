import CDP from "chrome-remote-interface"
const sleep = (ms) => new Promise((r) => setTimeout(r, ms))
const client = await CDP({ host: "127.0.0.1", port: 9222 })
const { Runtime } = client
await Runtime.enable()
// Enter edit mode
await Runtime.evaluate({ expression: `
  (async () => {
    const btns = [...document.querySelectorAll('.sessions .ic-btn')]
    btns.find(b => /edit|编辑/i.test(b.title))?.click()
    await new Promise(r => setTimeout(r, 250))
    return true
  })()
`, awaitPromise: true })
const r = await Runtime.evaluate({ expression: `(() => {
  const head = document.querySelector('.sessions .head')
  return [...head.querySelectorAll('button')].map(b => {
    const svg = b.querySelector('svg')
    return {
      title: b.title,
      hasSvg: !!svg,
      // count child elements (paths, lines, polylines, etc.)
      children: svg ? svg.children.length : 0,
      // first 200 chars of outerHTML so we can see the shape
      svgSnippet: svg ? svg.outerHTML.slice(0, 250) : '',
    }
  })
})()`, returnByValue: true })
console.log(JSON.stringify(r.result.value, null, 2))
await client.close()
