<script setup lang="ts">
// 全局动作 toast —— App.vue 挂载一次，全应用统一反馈样式。
import { toast } from "../lib/toast"
</script>

<template>
  <Transition name="toast">
    <div v-if="toast" :class="['app-toast', toast.kind]">
      {{ toast.text }}
    </div>
  </Transition>
</template>

<style scoped>
.app-toast {
  position: fixed;
  bottom: 36px;
  left: 50%;
  transform: translateX(-50%);
  z-index: 300;
  max-width: min(92vw, 480px);
  padding: 10px 18px;
  border-radius: 10px;
  font-size: 13.5px;
  font-weight: 600;
  box-shadow: 0 6px 24px rgba(0, 0, 0, 0.18);
  border: 1px solid transparent;
  text-align: center;
  pointer-events: none;
}
.app-toast.success {
  background: var(--success-soft, rgba(22, 163, 74, 0.14));
  color: var(--success, #16a34a);
  border-color: rgba(22, 163, 74, 0.4);
}
.app-toast.error {
  background: var(--danger-soft, rgba(220, 38, 38, 0.12));
  color: var(--danger, #dc2626);
  border-color: rgba(220, 38, 38, 0.4);
}
.toast-enter-active,
.toast-leave-active {
  transition: opacity 0.2s ease, transform 0.2s ease;
}
.toast-enter-from,
.toast-leave-to {
  opacity: 0;
  transform: translate(-50%, 8px);
}
</style>
