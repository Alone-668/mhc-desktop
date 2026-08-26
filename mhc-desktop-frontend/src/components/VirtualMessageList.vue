<script setup lang="ts">
// Minimal virtualised list for chat messages.
//
// The goal needs "长达 1w 个 message 时候的渲染流畅度" — at 10k
// messages, mounting every <div class="msg"> in the DOM is what
// kills scrolling, not the data layer. This component:
//
//   * Keeps every message in `messages[]`.
//   * Renders only the slice that falls inside the viewport (plus
//     a small overscan on each side so a fast scroll doesn't show
//     blank rows for a frame).
//   * Estimates each message's height up-front (so the initial
//     layout reserves space without rendering every node) and
//     refines the estimate from `offsetHeight` after each render.
//
// This is a single-file component, ~150 lines of TS, no
// dependencies on third-party virtualisers. The math is plain
// cumulative heights.
//
// # gotcha — reactivity of the height cache (READ BEFORE EDITING)
//
// `heights` is a `shallowRef` wrapping a plain `Map`, NOT a plain
// `Map`. Reason: the original code used `new Map(...)` and wrote
// into it from `measureRendered`, which silently *did not* trigger
// `indexed` to re-run. Spacer math drifted from real DOM and the
// progress bar started sticking / jumping on long conversations.
//
// `shallowRef` proxies the ref itself but not the inner Map —
// `.get`/`.set` stay native. Vue only notices the change when we
// explicitly call `triggerRef(heights)`. So the rule is:
//
//     every `heights.value.set(...)` and `heights.value.clear()`
//     MUST be paired with `triggerRef(heights)`.
//
// Forget the `triggerRef` and the spacer math goes stale again.
// Code review must grep for `heights.value.` and verify each call
// site has the matching trigger. Don't refactor this back to a
// plain Map without re-reading the long-conversation scroll bug.
//
// # scroll anchor
//
// After the reactivity fix, spacer geometry CAN change mid-session
// (code block finishing syntax highlight, an `<img>` resolving,
// an assistant message growing on each streamed chunk). Without an
// anchor, the browser clamps `scrollTop` when scrollHeight shrinks
// and the user's reading position visibly jumps each time
// measurements converge. We capture the topmost visible row in
// `onBeforeUpdate` and restore it after the next paint via
// `requestAnimationFrame`, gated on `heightsChangedInLastMeasure`
// so we only restore when spacers actually moved.

import { computed, nextTick, onBeforeUpdate, onMounted, onUpdated, ref, shallowRef, triggerRef, watch } from "vue"

interface VirtualItem {
  id: string | number
  /** Estimated height used before we measure the rendered node. */
  estimatedHeight: number
  /** Refined height once we've rendered this row at least once. */
  measuredHeight?: number
}

const props = defineProps<{
  messages: ReadonlyArray<{ id: string } & Record<string, unknown>>
  /** Called when the user scrolls within ``overscanPx`` of the
   *  top/bottom so the parent can decide to fetch more history or
   *  just keep streaming. The parent passes the scroll direction
   *  so it can react differently. */
  onScrollNearEdge?: (direction: "top" | "bottom") => void
  /** Per-message DOM size guess before measurement. Markdown
   *  replies can grow tall with code blocks; tool-call rows are
   *  shorter. Override per-message with the ``data-height-hint``
   *  attribute on the rendered row, or pass a flat estimate here. */
  estimatedRowHeight?: number
  overscanPx?: number
}>()

const scrollerEl = ref<HTMLElement | null>(null)
const innerEl = ref<HTMLElement | null>(null)
const scrollTop = ref(0)
const viewportHeight = ref(0)

defineExpose({ scrollerEl, innerEl })

const DEFAULT_ROW = props.estimatedRowHeight ?? 120
const OVERSCAN = props.overscanPx ?? 400

// `heights` is the per-row measured-height cache. See the header
// "gotcha" comment for why this is a `shallowRef<Map>` and not a
// plain `Map` — every mutation must be paired with `triggerRef`.
const heights = shallowRef(new Map<string | number, number>())

interface IndexedItem extends VirtualItem {
  index: number
  offsetTop: number
}

const indexed = computed<IndexedItem[]>(() => {
  const est = DEFAULT_ROW
  const cache = heights.value   // tracked via shallowRef
  const out: IndexedItem[] = []
  let offset = 0
  for (let i = 0; i < props.messages.length; i++) {
    const m = props.messages[i]
    const h = cache.get(m.id) ?? est
    out.push({ ...m, estimatedHeight: est, measuredHeight: h, index: i, offsetTop: offset })
    offset += h
  }
  return out
})

const totalHeight = computed(() => {
  const items = indexed.value
  if (items.length === 0) return 0
  const last = items[items.length - 1]
  return last.offsetTop + (last.measuredHeight ?? last.estimatedHeight)
})

const visibleRange = computed(() => {
  const items = indexed.value
  if (items.length === 0) return { start: 0, end: 0, topPad: 0, bottomPad: 0 }
  const top = scrollTop.value - OVERSCAN
  const bottom = scrollTop.value + viewportHeight.value + OVERSCAN

  let start = 0
  let end = items.length

  // Linear scan from the start; for chat lists this is plenty fast
  // (a 10k linear scan over ~10-element arrays is sub-millisecond).
  for (let i = 0; i < items.length; i++) {
    const it = items[i]
    const h = it.measuredHeight ?? it.estimatedHeight
    if (it.offsetTop + h >= top) {
      start = i
      break
    }
  }
  for (let i = start; i < items.length; i++) {
    const it = items[i]
    if (it.offsetTop > bottom) {
      end = i
      break
    }
  }

  const topPad = items[start]?.offsetTop ?? 0
  const lastVisible = items[end - 1]
  const bottomPad = Math.max(
    0,
    totalHeight.value -
      (lastVisible
        ? lastVisible.offsetTop +
          (lastVisible.measuredHeight ?? lastVisible.estimatedHeight)
        : 0),
  )

  return { start, end, topPad, bottomPad }
})

const visibleItems = computed(() => {
  const { start, end } = visibleRange.value
  return indexed.value.slice(start, end)
})

function onScroll(e: Event) {
  const el = e.currentTarget as HTMLElement
  scrollTop.value = el.scrollTop
  // Notify the parent when we're near the edges so it can decide
  // to load older history or, for the bottom edge, just track
  // "user is at the bottom" (so a new streamed message can
  // auto-scroll).
  if (props.onScrollNearEdge) {
    if (el.scrollTop < 80) props.onScrollNearEdge("top")
    else if (el.scrollTop + el.clientHeight >= el.scrollHeight - 80)
      props.onScrollNearEdge("bottom")
  }
}

function onResize() {
  const el = scrollerEl.value
  if (!el) return
  viewportHeight.value = el.clientHeight
}

let resizeObserver: ResizeObserver | null = null
onMounted(() => {
  onResize()
  if (typeof ResizeObserver !== "undefined" && scrollerEl.value) {
    resizeObserver = new ResizeObserver(onResize)
    resizeObserver.observe(scrollerEl.value)
  }
  // Measure rendered rows so subsequent range calculations are
  // accurate. ResizeObserver would also work, but a single sweep
  // after the first paint is enough for the common case.
  void nextTick(measureRendered)
})

// Set to true by `measureRendered` when at least one row's height
// changed; consumed by `onUpdated` to schedule a scroll-anchor
// restore ONLY in the spacer re-render that follows, not in the
// original content patch.
let heightsChangedInLastMeasure = false

function measureRendered() {
  const root = innerEl.value
  if (!root) return
  const rows = root.querySelectorAll<HTMLElement>("[data-vmsg]")
  const cache = heights.value
  let changed = false
  for (const row of rows) {
    const id = row.dataset.vmsg
    if (!id) continue
    const h = row.offsetHeight
    if (h > 0 && cache.get(id) !== h) {
      cache.set(id, h)            // see header "gotcha" — pair with triggerRef below
      changed = true
    }
  }
  if (changed) {
    heightsChangedInLastMeasure = true
    triggerRef(heights)
  }
}

// ── scroll anchor ─────────────────────────────────────────────
// Captured before each patch: the topmost row currently in view
// and its y position relative to the scroller. After paint we
// re-locate that row and shift `scrollTop` by however much it
// drifted, so the user's reading position stays put while spacers
// resize.
let pendingAnchor: { id: string; topInScroller: number } | null = null

function captureAnchor() {
  const el = scrollerEl.value
  const inner = innerEl.value
  if (!el || !inner) return
  const scrollerTop = el.getBoundingClientRect().top
  const scrollTopVal = el.scrollTop
  const rows = inner.querySelectorAll<HTMLElement>("[data-vmsg]")
  for (const row of rows) {
    const id = row.dataset.vmsg
    if (!id) continue
    const topInScroller = row.getBoundingClientRect().top - scrollerTop + scrollTopVal
    if (topInScroller + row.offsetHeight > scrollTopVal + 1) {
      pendingAnchor = { id, topInScroller }
      return
    }
  }
}

function restoreAnchor() {
  if (!pendingAnchor) return
  const el = scrollerEl.value
  const inner = innerEl.value
  if (!el || !inner) {
    pendingAnchor = null
    return
  }
  // If ChatView is holding the user at the bottom (streaming auto-
  // scroll), don't yank them back to the previous anchor — the
  // bottom-edge scroll already wins.
  if (el.scrollTop + el.clientHeight >= el.scrollHeight - 4) {
    pendingAnchor = null
    return
  }
  const sel = `[data-vmsg="${CSS.escape(String(pendingAnchor.id))}"]`
  const row = inner.querySelector<HTMLElement>(sel)
  if (!row) {
    pendingAnchor = null
    return
  }
  const scrollerTop = el.getBoundingClientRect().top
  const newRowTop = row.getBoundingClientRect().top - scrollerTop + el.scrollTop
  const delta = pendingAnchor.topInScroller - newRowTop
  if (Math.abs(delta) > 0.5) el.scrollTop = el.scrollTop + delta
  pendingAnchor = null
}

onBeforeUpdate(captureAnchor)

// Re-measure after every Vue patch so newly rendered rows
// contribute to the next frame's height math. `measureRendered`
// may `triggerRef` to invalidate `indexed`, which causes another
// patch (spacer resize). We schedule the anchor restore inside
// that second patch — guarded by `heightsChangedInLastMeasure` so
// we don't restore against stale spacers from the first patch.
onUpdated(() => {
  void nextTick(() => {
    measureRendered()
    if (heightsChangedInLastMeasure) {
      heightsChangedInLastMeasure = false
      requestAnimationFrame(restoreAnchor)
    }
  })
})

// When the message list shrinks (e.g. user clears chat), drop
// the height cache so the next render doesn't inherit stale
// sizes. Mutation must be paired with `triggerRef` per the header
// "gotcha" comment.
watch(
  () => props.messages.length,
  (n, old) => {
    if (n < (old ?? 0)) {
      heights.value.clear()
      triggerRef(heights)
    }
  },
)
</script>

<template>
  <div ref="scrollerEl" class="vmsg-scroller" @scroll.passive="onScroll">
    <div ref="innerEl" class="vmsg-inner">
      <div class="vmsg-spacer" :style="{ height: visibleRange.topPad + 'px' }" />
      <slot
        v-for="item in visibleItems"
        :key="item.id"
        :item="item"
        :index="item.index"
      />
      <div class="vmsg-spacer" :style="{ height: visibleRange.bottomPad + 'px' }" />
    </div>
  </div>
</template>

<style scoped>
.vmsg-scroller {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
}
.vmsg-inner {
  position: relative;
  /* The container's height is driven by the spacers + rendered
     rows. We don't set an explicit height on .vmsg-inner — its
     children stack normally. */
}
.vmsg-spacer {
  /* Just an empty block; height comes from the inline style. */
  pointer-events: none;
}
</style>