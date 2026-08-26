<script setup lang="ts">
import { computed, onMounted, ref, watch } from "vue"
import { RouterLink } from "vue-router"
import Icon from "./Icon.vue"
import UserCard from "./UserCard.vue"
import { useSkillsStore } from "../stores/skills"
import { useMCPsStore } from "../stores/mcps"
import { useToolsStore } from "../stores/tools"
import { useAppMetaStore } from "../stores/appMeta"
import { t } from "../i18n"

const skills = useSkillsStore()
const mcps = useMCPsStore()
const tools = useToolsStore()
const appMeta = useAppMetaStore()

// Each foldable container can be collapsed/expanded independently. We
// persist the open/closed state in localStorage so the user's
// preference survives a reload.
const LS_SKILLS_OPEN = "mhc.layout.skillsOpen"
const LS_MCP_OPEN = "mhc.layout.mcpOpen"
const LS_TOOLS_OPEN = "mhc.layout.toolsOpen"
const skillsOpen = ref(true)
const mcpOpen = ref(true)
const toolsOpen = ref(true)

function safeRead(key: string, fallback: boolean): boolean {
  try {
    const v = localStorage.getItem(key)
    if (v === "1") return true
    if (v === "0") return false
  } catch {
    /* ignore */
  }
  return fallback
}

function safeWrite(key: string, v: boolean) {
  try {
    localStorage.setItem(key, v ? "1" : "0")
  } catch {
    /* ignore */
  }
}

onMounted(() => {
  skillsOpen.value = safeRead(LS_SKILLS_OPEN, true)
  mcpOpen.value = safeRead(LS_MCP_OPEN, true)
  toolsOpen.value = safeRead(LS_TOOLS_OPEN, true)
  skills.refresh()
  mcps.refresh()
  tools.refresh()
})

watch(skillsOpen, (v) => safeWrite(LS_SKILLS_OPEN, v))
watch(mcpOpen, (v) => safeWrite(LS_MCP_OPEN, v))
watch(toolsOpen, (v) => safeWrite(LS_TOOLS_OPEN, v))

const enabledSkills = computed(() => skills.enabled)
const enabledMCPs = computed(() => mcps.enabled)
const enabledTools = computed(() => tools.enabledTools)
</script>

<template>
  <nav class="leftnav">
    <div class="brand">
      <img class="brand-logo" src="/brand.svg" alt="" />
      <span class="t">{{ appMeta.title }}</span>
    </div>

    <RouterLink to="/chat" class="item" active-class="active">
      <Icon name="message" />
      <span>{{ t("nav.chat") }}</span>
    </RouterLink>
    <RouterLink to="/models" class="item" active-class="active">
      <Icon name="plug" />
      <span>{{ t("nav.models") }}</span>
    </RouterLink>
    <RouterLink to="/metrics" class="item" active-class="active">
      <Icon name="chart" />
      <span>{{ t("nav.metrics") }}</span>
    </RouterLink>
    <RouterLink to="/skills" class="item" active-class="active">
      <Icon name="package" />
      <span>{{ t("nav.skills") }}</span>
    </RouterLink>
    <RouterLink to="/mcp" class="item" active-class="active">
      <Icon name="server" />
      <span>{{ t("nav.mcp") }}</span>
    </RouterLink>
    <RouterLink to="/tools" class="item" active-class="active">
      <Icon name="hammer" />
      <span>{{ t("nav.tools") }}</span>
    </RouterLink>
    <RouterLink to="/settings" class="item" active-class="active">
      <Icon name="settings" />
      <span>{{ t("nav.settings") }}</span>
    </RouterLink>

    <!-- The whole workspace region is one scroll container. Each
         child container is foldable but itself doesn't scroll. -->
    <div class="workspace-scroller">
      <!-- Skills -->
      <section class="fold">
        <button
          class="fold-head"
          :aria-expanded="skillsOpen"
          @click="skillsOpen = !skillsOpen"
        >
          <Icon :name="skillsOpen ? 'chevron-down' : 'chevron-up'" />
          <span class="fold-title">{{ t("nav.skills") }}</span>
          <span class="fold-help" :title="t('nav.skillsHint')">
            <Icon name="help" />
          </span>
          <span class="fold-count">{{ enabledSkills.length }}</span>
        </button>
        <ul v-show="skillsOpen" class="wlist">
          <li
            v-for="s in enabledSkills"
            :key="s.slug"
            class="wskill"
            :class="{ active: skills.isActive(s.slug) }"
          >
            <label class="wskill-toggle" :title="s.name">
              <input
                type="checkbox"
                :checked="skills.isActive(s.slug)"
                @change="skills.toggleActive(s.slug)"
              />
              <span class="wskill-switch" />
            </label>
            <div class="wskill-info">
              <div class="wskill-name">{{ s.name }}</div>
              <div class="wskill-desc">{{ s.description }}</div>
            </div>
          </li>
          <li v-if="enabledSkills.length === 0" class="empty">
            {{ t("nav.workspaceSkillsHint") }}
          </li>
        </ul>
      </section>

      <!-- MCP -->
      <section class="fold">
        <button
          class="fold-head"
          :aria-expanded="mcpOpen"
          @click="mcpOpen = !mcpOpen"
        >
          <Icon :name="mcpOpen ? 'chevron-down' : 'chevron-up'" />
          <span class="fold-title">{{ t("nav.mcp") }}</span>
          <span class="fold-help" :title="t('nav.mcpHint')">
            <Icon name="help" />
          </span>
          <span class="fold-count">{{ enabledMCPs.length }}</span>
        </button>
        <ul v-show="mcpOpen" class="wlist">
          <li
            v-for="s in enabledMCPs"
            :key="s.slug"
            class="wskill"
            :class="{ active: mcps.isActive(s.slug) }"
          >
            <label class="wskill-toggle" :title="s.name">
              <input
                type="checkbox"
                :checked="mcps.isActive(s.slug)"
                @change="mcps.toggleActive(s.slug)"
              />
              <span class="wskill-switch" />
            </label>
            <div class="wskill-info">
              <div class="wskill-name">{{ s.name }}</div>
              <div class="wskill-desc">
                {{ s.description || `${s.tools.length} tools` }}
              </div>
            </div>
          </li>
          <li v-if="enabledMCPs.length === 0" class="empty">
            {{ t("nav.workspaceMCPsHint") }}
          </li>
        </ul>
      </section>

      <!-- Tools (third concept, below the Skills + MCP folds).
           The user said "上半部分放 Skills + MCP, 下半部分放 Tools"
           so this fold lives at the bottom of the scroller with a
           hairline divider above it. -->
      <div class="fold-divider" aria-hidden="true" />
      <section class="fold fold-tools">
        <button
          class="fold-head"
          :aria-expanded="toolsOpen"
          @click="toolsOpen = !toolsOpen"
        >
          <Icon :name="toolsOpen ? 'chevron-down' : 'chevron-up'" />
          <span class="fold-title">{{ t("nav.tools") }}</span>
          <span class="fold-help" :title="t('nav.toolsHint')">
            <Icon name="help" />
          </span>
          <span class="fold-count">{{ enabledTools.length }}</span>
        </button>
        <ul v-show="toolsOpen" class="wlist">
          <li
            v-for="s in enabledTools"
            :key="s.slug"
            class="wskill tool-row"
            :class="{ active: tools.active.has(s.slug) }"
          >
            <label class="wskill-toggle" :title="s.name">
              <input
                type="checkbox"
                :checked="tools.active.has(s.slug)"
                @change="tools.toggleActive(s.slug)"
              />
              <span class="wskill-switch" />
            </label>
            <div class="wskill-info">
              <div class="wskill-name">{{ s.name }}</div>
              <div class="wskill-desc">
                {{ s.description || `(${s.kind})` }}
              </div>
            </div>
          </li>
          <li v-if="enabledTools.length === 0" class="empty">
            {{ t("nav.workspaceToolsHint") }}
          </li>
        </ul>
      </section>
    </div>
    <UserCard />
  </nav>
</template>

<style scoped>
.leftnav {
  display: flex;
  flex-direction: column;
  height: 100%;
  background: var(--bg-panel);
  border-right: 1px solid var(--border);
  padding: 16px 12px 12px;
  gap: 2px;
}
.brand {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 6px 8px 14px;
  font-weight: 600;
  font-size: 14px;
  color: var(--text);
}
.brand-logo {
  width: 22px;
  height: 22px;
  display: block;
  /* The mark is drawn on a transparent canvas; dark themes need a
     subtle light glow so the highlights don't disappear into the
     background. Use a small box-shadow rather than a filter to
     keep the asset crisp at small sizes. */
  border-radius: 5px;
}
.item {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 7px 10px;
  border-radius: 6px;
  color: var(--text-mid);
  text-decoration: none;
  font-size: var(--app-font-size, 14px);
  border: 1px solid transparent;
  transition: background 120ms ease, color 120ms ease, border-color 120ms ease;
}
.item:hover {
  background: var(--bg-hover);
  color: var(--text);
}
.item.active {
  background: var(--bg);
  color: var(--text);
  border-color: var(--border);
  font-weight: 500;
}

/* The workspace scroller takes the remaining height and scrolls. */
.workspace-scroller {
  margin-top: 16px;
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 10px;
  padding-right: 2px;
}

/* Each fold container itself does not scroll. flex-shrink: 0 is
   essential: overflow:hidden would otherwise make min-height:auto
   resolve to 0, letting flex shrink each fold down to the scroller
   height and clip its content. With it, folds expand to natural
   height and the workspace scroller handles overflow. */
.fold {
  flex-shrink: 0;
  background: var(--bg);
  border: 1px solid var(--border);
  border-radius: 8px;
  overflow: hidden;
}
.fold-head {
  width: 100%;
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 7px 10px;
  background: transparent;
  border: 0;
  cursor: pointer;
  font: inherit;
  font-size: var(--app-font-size, 12px);
  font-weight: 600;
  letter-spacing: 0.04em;
  text-transform: uppercase;
  color: var(--text-mid);
  transition: background 100ms ease, color 100ms ease;
}
.fold-head:hover {
  background: var(--bg-hover);
  color: var(--text);
}
.fold-title {
  flex: 1;
  text-align: left;
}
.fold-help {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 16px;
  height: 16px;
  border-radius: 999px;
  color: var(--text-faint);
  cursor: help;
  transition: color 120ms ease, background 120ms ease;
}
.fold-help:hover {
  color: var(--text);
  background: var(--bg-hover);
}
.fold-count {
  background: var(--bg-hover);
  color: var(--text-faint);
  font-size: var(--app-font-size, 12px);
  padding: 1px 7px;
  border-radius: 999px;
  font-weight: 700;
  letter-spacing: 0;
  text-transform: none;
}
.wlist {
  list-style: none;
  margin: 0;
  padding: 4px 6px 8px;
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.wskill {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  padding: 8px 10px;
  border-radius: 8px;
  border: 1px solid transparent;
  background: transparent;
  transition: background 120ms ease, border-color 120ms ease;
}
.wskill:hover {
  background: var(--bg-hover);
}
.wskill.active {
  background: var(--accent-soft);
  border-color: var(--accent);
}
.wskill-toggle {
  position: relative;
  display: inline-flex;
  align-items: center;
  width: 26px;
  height: 16px;
  flex-shrink: 0;
  cursor: pointer;
  margin-top: 2px;
}
.wskill-toggle input {
  position: absolute;
  opacity: 0;
  width: 0;
  height: 0;
  pointer-events: none;
}
.wskill-switch {
  display: inline-block;
  width: 26px;
  height: 16px;
  background: var(--border);
  border-radius: 999px;
  position: relative;
  transition: background 140ms ease;
}
.wskill-switch::before {
  content: "";
  position: absolute;
  width: 12px;
  height: 12px;
  left: 2px;
  top: 2px;
  background: var(--bg);
  border-radius: 50%;
  box-shadow: var(--shadow-toggle);
  transition: transform 140ms ease;
}
.wskill.active .wskill-switch {
  background: var(--accent);
}
.wskill.active .wskill-switch::before {
  transform: translateX(10px);
}
.wskill-info {
  min-width: 0;
  flex: 1;
}
.wskill-name {
  font-size: var(--app-font-size, 12px);
  font-weight: 600;
  color: var(--text);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.wskill-desc {
  font-size: var(--app-font-size, 12px);
  color: var(--text-mid);
  line-height: 1.4;
  margin-top: 2px;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}
.empty {
  list-style: none;
  padding: 8px 10px;
  font-size: var(--app-font-size, 12px);
  color: var(--text-faint);
  font-style: italic;
}

/* Tool fold sits below the Skills + MCP folds with a hairline
   divider to mark it as the third-concept area. Tool rows tint
   purple when active so the user can see which subsystem the
   chips correspond to without reading labels. */
.fold-divider {
  height: 1px;
  background: var(--border);
  margin: 4px 6px;
}
.fold-tools .fold-head {
  color: var(--text-mid);
}
.wskill.tool-row.active {
  background: rgba(124, 58, 237, 0.08);
  border-color: rgba(124, 58, 237, 0.35);
}
.wskill.tool-row.active .wskill-switch {
  background: #7c3aed;
}
</style>