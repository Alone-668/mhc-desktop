<script setup lang="ts">
import { RouterLink } from "vue-router"
import Icon from "./Icon.vue"
import UserCard from "./UserCard.vue"
import { useAppMetaStore } from "../stores/appMeta"
import { t } from "../i18n"

// Skills, tools and MCPs all follow the same rule: no foldable
// sidebar lists, no per-session toggles. Enable/disable lives
// in the /skills, /tools and /mcp configuration pages, and every
// enabled item is injected into every user message (skills via
// the backend system prompt, tools+MCPs via the chat payload).
// The sidebar is pure navigation.
const appMeta = useAppMetaStore()
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
      <Icon name="wrench" />
      <span>{{ t("nav.tools") }}</span>
    </RouterLink>
    <RouterLink to="/settings" class="item" active-class="active">
      <Icon name="settings" />
      <span>{{ t("nav.settings") }}</span>
    </RouterLink>

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
</style>
