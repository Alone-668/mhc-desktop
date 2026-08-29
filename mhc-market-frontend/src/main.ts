import { createApp } from "vue"
import { createRouter, createWebHashHistory } from "vue-router"
import App from "./App.vue"
import MarketView from "./views/MarketView.vue"
import MineView from "./views/MineView.vue"
import LoginView from "./views/LoginView.vue"
import { isAuthed } from "./api/auth"

const router = createRouter({
  history: createWebHashHistory(),
  routes: [
    { path: "/", name: "market", component: MarketView },
    { path: "/mine", name: "mine", component: MineView },
    { path: "/login", name: "login", component: LoginView },
  ],
})

router.beforeEach((to) => {
  if (to.name !== "login" && !isAuthed()) return { name: "login" }
  if (to.name === "login" && isAuthed()) return { name: "market" }
})

createApp(App).use(router).mount("#app")
