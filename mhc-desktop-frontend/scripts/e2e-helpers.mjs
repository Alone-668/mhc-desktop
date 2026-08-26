// @ts-nocheck
// Shared helpers for the CDP-driven E2E scripts.
//
// We keep this tiny on purpose: each e2e-*.mjs is supposed to be
// readable end-to-end, and a 200-line helpers file would be a
// bigger commitment than the scripts themselves.

import { default as CDP } from "chrome-remote-interface"

export { CDP }

export async function sleep(ms) {
  await new Promise((r) => setTimeout(r, ms))
}

export async function eval_(client, expression) {
  const { Runtime } = client
  const r = await Runtime.evaluate({ expression, returnByValue: true })
  if (r.exceptionDetails) {
    throw new Error(
      `eval failed: ${r.exceptionDetails.exception?.description || JSON.stringify(r.exceptionDetails)}`,
    )
  }
  return r.result.value
}

export async function gotoRoute(client, hash) {
  return eval_(
    client,
    `(async () => {
      window.location.hash = ${JSON.stringify(hash)};
      await new Promise((r) => setTimeout(r, 50));
      return { ok: true, hash: window.location.hash };
    })()`,
  )
}