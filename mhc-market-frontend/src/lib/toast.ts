// 全局动作 toast：底部居中、上浮淡入、自动消失。
// 由 App.vue 挂载 <AppToast /> 一次性渲染，任何视图用 showToast() 触发，
// 与桌面端行为一致。
import { ref } from "vue"

export interface ToastState {
  text: string
  kind: "success" | "error"
}

export const toast = ref<ToastState | null>(null)
let _timer: ReturnType<typeof setTimeout> | null = null

export function showToast(text: string, kind: "success" | "error" = "success") {
  toast.value = { text, kind }
  if (_timer) clearTimeout(_timer)
  _timer = setTimeout(() => {
    toast.value = null
  }, 2600)
}

// 把后端/JS 的英文报错转成用户能看懂的中文；JS 内部错误给通用文案。
const _FRIENDLY: [RegExp, string][] = [
  [/identical skill already exists.*republishing exact copies is not allowed/i,
    "已存在相同内容的技能，不能重复发布同一版本。"],
  [/only the author can delist/i, "只有作者才能下架该技能。"],
  [/not found or delisted/i, "该技能已不存在或已下架。"],
  [/invalid category|invalid slug/i, "内容无效。"],
  [/cannot read|is not a function|is not defined|undefined/i, "操作未完成，请重试。"],
]

export function friendlyError(raw: string): string {
  for (const [re, zh] of _FRIENDLY) {
    if (re.test(raw)) return zh
  }
  return raw
}
