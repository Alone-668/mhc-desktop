<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from "vue"
import { useRouter } from "vue-router"
import { useAuthStore } from "../stores/auth"
import { t } from "../i18n"

const auth = useAuthStore()
const router = useRouter()

const menuOpen = ref(false)
const cardRef = ref<HTMLElement | null>(null)

function toggleMenu() {
  menuOpen.value = !menuOpen.value
}

function closeMenu() {
  menuOpen.value = false
}

async function handleSignOut() {
  closeMenu()
  await auth.logout()
  // Bounce to login; the router guard also does this, but going
  // explicit here means the URL updates immediately so a back-button
  // press doesn't return to the chat view.
  await router.push("/login")
}

// Close the menu when the user clicks anywhere else in the document.
function onDocClick(e: MouseEvent) {
  if (!menuOpen.value) return
  if (!cardRef.value) return
  if (!cardRef.value.contains(e.target as Node)) {
    closeMenu()
  }
}
onMounted(() => document.addEventListener("click", onDocClick))
onUnmounted(() => document.removeEventListener("click", onDocClick))

// Fallback avatar: first character of the display name. We use the
// initials of the first + last word when the name has multiple parts
// so ``"Alice Liddell"`` shows ``AL`` instead of just ``A``. Falls
// back to ``?`` if everything is empty (defensive — shouldn't happen).
const initials = computed(() => {
  const name = (auth.user?.display_name || "").trim()
  if (!name) return "?"
  const parts = name.split(/\s+/)
  if (parts.length === 1) return parts[0]!.slice(0, 1).toUpperCase()
  return (parts[0]!.slice(0, 1) + parts[parts.length - 1]!.slice(0, 1)).toUpperCase()
})
</script>

<template>
  <div v-if="auth.user" ref="cardRef" class="user-card">
    <button
      class="trigger"
      type="button"
      :aria-expanded="menuOpen"
      :aria-label="t('sidebar.signedInAs', { name: auth.user.display_name })"
      @click="toggleMenu"
    >
      <span class="avatar" :data-has-image="auth.user.avatar_url ? '1' : '0'">
        <img
          v-if="auth.user.avatar_url"
          :src="auth.user.avatar_url"
          :alt="auth.user.display_name"
        />
        <span v-else class="initials">{{ initials }}</span>
      </span>
      <span class="meta">
        <span class="name">{{ auth.user.display_name }}</span>
        <span class="username">{{ auth.user.username }}</span>
      </span>
    </button>
    <div v-if="menuOpen" class="menu" role="menu">
      <button
        type="button"
        role="menuitem"
        class="menu-item"
        @click="handleSignOut"
      >
        {{ t("sidebar.signOut") }}
      </button>
    </div>
  </div>
</template>

<style scoped>
.user-card {
  position: relative;
  flex-shrink: 0;
  margin-top: auto;
  border-top: 1px solid var(--border);
  padding-top: 8px;
}
.trigger {
  display: flex;
  align-items: center;
  gap: 10px;
  width: 100%;
  padding: 8px 10px;
  border: 0;
  background: transparent;
  border-radius: 8px;
  cursor: pointer;
  font: inherit;
  color: var(--text);
  text-align: left;
  transition: background 120ms ease;
}
.trigger:hover,
.trigger:focus-visible {
  background: var(--bg-hover);
  outline: none;
}
.avatar {
  flex-shrink: 0;
  width: 30px;
  height: 30px;
  border-radius: 50%;
  background: var(--accent);
  color: white;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  overflow: hidden;
  font-weight: 600;
  font-size: 12px;
}
.avatar img {
  width: 100%;
  height: 100%;
  object-fit: cover;
  display: block;
}
.initials {
  letter-spacing: 0.02em;
}
.meta {
  display: flex;
  flex-direction: column;
  gap: 1px;
  min-width: 0;
  flex: 1;
}
.name {
  font-size: 12.5px;
  font-weight: 600;
  color: var(--text);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.username {
  font-size: 11px;
  color: var(--text-faint);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.menu {
  position: absolute;
  bottom: calc(100% + 4px);
  left: 8px;
  right: 8px;
  background: var(--bg-panel);
  border: 1px solid var(--border);
  border-radius: 8px;
  box-shadow: 0 6px 24px rgba(0, 0, 0, 0.18);
  padding: 4px;
  z-index: 100;
}
.menu-item {
  display: block;
  width: 100%;
  text-align: left;
  font: inherit;
  font-size: 12.5px;
  padding: 7px 10px;
  border: 0;
  border-radius: 6px;
  background: transparent;
  color: var(--text);
  cursor: pointer;
}
.menu-item:hover {
  background: var(--bg-hover);
}
</style>