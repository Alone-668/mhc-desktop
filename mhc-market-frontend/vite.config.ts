import { defineConfig } from "vite"
import vue from "@vitejs/plugin-vue"

// Dev: :5181, /api proxied to the market backend on :8766 (no CORS).
// Build: outputs dist/, which `npm run build:to-backend` copies into
// the market backend's package dir for same-origin hosting.
export default defineConfig({
  plugins: [vue()],
  server: {
    port: 5181,
    proxy: {
      "/api": "http://127.0.0.1:8766",
    },
  },
})
