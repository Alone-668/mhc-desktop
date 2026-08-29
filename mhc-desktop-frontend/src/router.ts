import { createRouter, createWebHashHistory } from "vue-router"
import ChatView from "./views/ChatView.vue"
import LoginView from "./views/LoginView.vue"
import MetricsView from "./views/MetricsView.vue"
import ModelsView from "./views/ModelsView.vue"
import SettingsView from "./views/SettingsView.vue"
import SkillsView from "./views/SkillsView.vue"
import MarketView from "./views/MarketView.vue"
import MCPView from "./views/MCPView.vue"
import ToolsView from "./views/ToolsView.vue"
import { useAuthStore } from "./stores/auth"

export const router = createRouter({
  history: createWebHashHistory(),
  routes: [
    { path: "/", redirect: "/chat" },
    { path: "/login", name: "login", component: LoginView },
    { path: "/chat", name: "chat", component: ChatView },
    { path: "/models", name: "models", component: ModelsView },
    { path: "/skills", redirect: "/market" },
    { path: "/market", name: "market", component: MarketView },
    { path: "/mcp", name: "mcp", component: MCPView },
    { path: "/tools", name: "tools", component: ToolsView },
    { path: "/metrics", name: "metrics", component: MetricsView },
    { path: "/settings", name: "settings", component: SettingsView },
  ],
})

// Auth guard: every route except ``/login`` requires an authenticated
// principal. The bootstrap step in ``main.ts`` has already restored
// the token + user state from localStorage and /me before this guard
// ever runs, so ``auth.isAuthenticated`` is the live answer.
//
// ``/login`` is also the redirect target for an authenticated user
// who typed the URL directly — sending them back to /chat keeps the
// post-logout UX consistent.
router.beforeEach((to) => {
  const auth = useAuthStore()
  if (to.path === "/login") {
    if (auth.isAuthenticated) return { path: "/chat" }
    return true
  }
  if (!auth.isAuthenticated) return { path: "/login" }
  return true
})