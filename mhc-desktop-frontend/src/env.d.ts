/// <reference types="vite/client" />

declare module "*.vue" {
  import type { DefineComponent } from "vue"
  const component: DefineComponent<Record<string, unknown>, Record<string, unknown>, unknown>
  export default component
}

declare global {
  interface Window {
    mhc?: {
      versions: { electron: string; node: string }
      platform: NodeJS.Platform
      window: {
        minimize: () => Promise<void>
        toggleMaximize: () => Promise<void>
        close: () => Promise<void>
        isMaximized: () => Promise<boolean>
        onMaximizeChange: (cb: (max: boolean) => void) => () => void
      }
      pickFolder: () => Promise<string | null>
      pickFile: (opts?: {
        filters?: { name: string; extensions: string[] }[]
      }) => Promise<{ path: string; name: string } | null>
      readFile: (p: string) => Promise<ArrayBuffer | null>
    }
  }
}

export {}
