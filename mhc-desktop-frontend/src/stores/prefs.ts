import { defineStore } from "pinia"
import { ref } from "vue"
import { api, type Prefs } from "../api/client"

/** Global user preferences: the user's own addition to the system
 *  prompt is the only field today. The base system prompt is owned
 *  by the backend (server-side constant); this store just carries
 *  the user-authored half so the chat request layer can hand it to
 *  the router and the settings page can edit it.
 */
export const usePrefsStore = defineStore("prefs", () => {
  const systemPromptAddition = ref<string>("")
  const loading = ref(false)
  const error = ref<string | null>(null)

  /** Pull the current prefs from the backend. Called once on app
   *  boot; chat requests read ``systemPromptAddition`` synchronously
   *  after that — no per-request fetch.
   */
  async function load() {
    loading.value = true
    error.value = null
    try {
      const p: Prefs = await api.getPrefs()
      systemPromptAddition.value = p.system_prompt_addition ?? ""
    } catch (e) {
      error.value = e instanceof Error ? e.message : String(e)
    } finally {
      loading.value = false
    }
  }

  /** Save the user's current draft. The server strips whitespace
   *  and stores the trimmed value; we mirror that here so the UI
   *  shows what's actually on disk.
   */
  async function save(next: string) {
    const trimmed = (next ?? "").trim()
    const p: Prefs = await api.updatePrefs({
      system_prompt_addition: trimmed,
    })
    systemPromptAddition.value = p.system_prompt_addition
    return p
  }

  return {
    systemPromptAddition,
    loading,
    error,
    load,
    save,
  }
})