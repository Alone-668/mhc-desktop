import { computed, ref } from "vue"
import { defineStore } from "pinia"
import { api, type Skill } from "../api/client"


export const useSkillsStore = defineStore("skills", () => {
  const items = ref<Skill[]>([])
  const loading = ref(false)
  const error = ref<string | null>(null)

  const enabled = computed(() => items.value.filter((s) => s.enabled))


  async function refresh() {
    loading.value = true
    error.value = null
    try {
      items.value = await api.listSkills()
    } catch (e) {
      error.value = e instanceof Error ? e.message : String(e)
    } finally {
      loading.value = false
    }
  }


  async function setEnabled(slug: string, value: boolean) {
    const updated = await api.setSkillEnabled(slug, value)
    replace(updated)
  }

  async function remove(slug: string) {
    await api.deleteSkill(slug)
    items.value = items.value.filter((s) => s.slug !== slug)
  }

  async function importFolder(source: string) {
    const created = await api.importSkillFolder(source)
    upsert(created)
    return created
  }

  async function importZip(name: string, blob: Blob) {
    const created = await api.importSkillZip(name, blob)
    upsert(created)
    return created
  }

  function replace(skill: Skill) {
    const idx = items.value.findIndex((s) => s.slug === skill.slug)
    if (idx === -1) items.value.push(skill)
    else items.value[idx] = skill
  }

  function upsert(skill: Skill) {
    const idx = items.value.findIndex((s) => s.slug === skill.slug)
    if (idx === -1) items.value = [...items.value, skill]
    else items.value = items.value.map((s) => (s.slug === skill.slug ? skill : s))
  }

  return {
    items,
    enabled,
    loading,
    error,
    refresh,
    setEnabled,
    remove,
    importFolder,
    importZip,
  }
})
