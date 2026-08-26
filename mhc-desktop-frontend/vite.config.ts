// Vite config for mhc-desktop-frontend.
//
// Dev server runs on :5180 and proxies /api + /ready to the Python backend
// at :8765 (or wherever MHC_BACKEND points). Default backend is loopback
// only; no CORS dance needed.
//
// ``base: "./"`` makes the production bundle use relative asset URLs so
// the Electron host can load ``dist/index.html`` via ``file://`` — that's
// how the renderer paints the loading splash BEFORE the Python backend
// has finished booting. Absolute paths (``/assets/...``) would resolve
// against the wrong origin when loaded from disk.
import { defineConfig } from "vite"
import vue from "@vitejs/plugin-vue"

const BACKEND = process.env.MHC_BACKEND ?? "http://127.0.0.1:8765"
const FRONTEND_PORT = parseInt(process.env.MHC_FRONTEND_PORT ?? "5180", 10)

export default defineConfig({
  plugins: [vue()],
  // Relative asset URLs so ``dist/index.html`` can be loaded via
  // ``file://`` from the Electron host (loading screen needs to
  // render before the Python backend has bound its port).
  base: "./",
  server: {
    host: "127.0.0.1",
    port: FRONTEND_PORT,
    strictPort: true,
    proxy: {
      "/api": { target: BACKEND, changeOrigin: true },
      "/ready": { target: BACKEND, changeOrigin: true },
    },
  },
})
