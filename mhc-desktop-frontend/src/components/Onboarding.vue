<!--
  First-run onboarding overlay.

  This is a full-window modal that blocks the chat surface until
  the user clicks "知道了" / "Got it". The component owns the
  per-card layout (three variants) and the GSAP entrance; the
  store owns the card list, the current index, and the persistence
  flag.

  Card layouts
  ────────────
  * ``centered``   — text only, big display type, no media.
  * ``media-text`` — left/right split. Media ~60%, text ~40%.
                     GSAP slides both halves in from the sides.
  * ``media-top``  — top/bottom split. Media ~65%, text ~35%.
                     Lighter entrance (single fade-up) since the
                     spec only asks for GSAP on the first two.

  The media slot is a self-contained colored block labeled with
  ``media_label``. No external assets — see
  ``api/onboarding.py`` for the rationale.
-->

<script setup lang="ts">
import { computed, nextTick, onMounted, ref, watch } from "vue"
import { gsap } from "gsap"
import { storeToRefs } from "pinia"
import { useOnboardingStore } from "../stores/onboarding"
import { locale, t } from "../i18n"

const store = useOnboardingStore()
const { visible, current, isLast, total, index } = storeToRefs(store)

// Pick the localised copy from the i18n dicts on every render.
// Falls back to the resolved ``title``/``body`` (which the
// backend computed for the requester's Accept-Language) when a
// locale is missing, then to the key itself so we never crash on
// a typo in a dict.
function pickLocalized(card: { title_i18n: Record<string, string>; body_i18n: Record<string, string> }, kind: "title" | "body"): string {
  const dict = kind === "title" ? card.title_i18n : card.body_i18n
  if (dict && dict[locale.value]) return dict[locale.value]
  return dict?.en ?? (kind === "title" ? "" : "")
}

// Refs used as GSAP targets. We re-target them whenever the card
// index changes so each transition animates the freshly-mounted
// nodes rather than mutating an already-stabilised tree.
const backdrop = ref<HTMLElement | null>(null)
const centeredTitle = ref<HTMLElement | null>(null)
const centeredBody = ref<HTMLElement | null>(null)
const mediaLeftMedia = ref<HTMLElement | null>(null)
const mediaLeftText = ref<HTMLElement | null>(null)
const mediaTopMedia = ref<HTMLElement | null>(null)
const mediaTopText = ref<HTMLElement | null>(null)
const dotRow = ref<HTMLElement | null>(null)

const primaryLabel = computed(() =>
  isLast.value ? t("onboarding.gotIt") : t("onboarding.next"),
)

// Title / body displayed in the current locale. Reactive on both
// the active card (index) and the locale switcher in Settings.
const displayTitle = computed(() => (current.value ? pickLocalized(current.value, "title") : ""))
const displayBody = computed(() => (current.value ? pickLocalized(current.value, "body") : ""))

function dismiss() {
  store.dismiss()
}

// Page-change animation. We do this in a watch so the user sees a
// transition both going forward (Next) and jumping back (Prev /
// dot click). The animation is a function of the *new* card type
// — see the helpers below.
async function animateIn() {
  if (!visible.value || !current.value) return
  // Wait one frame so the v-if has rendered the new card's nodes.
  await nextTick()
  const c = current.value
  if (c.type === "centered") {
    if (centeredTitle.value) {
      gsap.fromTo(
        centeredTitle.value,
        { opacity: 0, y: 24, scale: 0.96 },
        { opacity: 1, y: 0, scale: 1, duration: 0.6, ease: "power3.out" },
      )
    }
    if (centeredBody.value) {
      gsap.fromTo(
        centeredBody.value,
        { opacity: 0, y: 16 },
        { opacity: 1, y: 0, duration: 0.6, delay: 0.15, ease: "power3.out" },
      )
    }
  } else if (c.type === "media-text") {
    if (mediaLeftMedia.value) {
      gsap.fromTo(
        mediaLeftMedia.value,
        { opacity: 0, x: -32 },
        { opacity: 1, x: 0, duration: 0.7, ease: "power3.out" },
      )
    }
    if (mediaLeftText.value) {
      gsap.fromTo(
        mediaLeftText.value,
        { opacity: 0, x: 32 },
        { opacity: 1, x: 0, duration: 0.7, delay: 0.1, ease: "power3.out" },
      )
    }
  } else {
    if (mediaTopMedia.value) {
      gsap.fromTo(
        mediaTopMedia.value,
        { opacity: 0, y: -20 },
        { opacity: 1, y: 0, duration: 0.5, ease: "power2.out" },
      )
    }
    if (mediaTopText.value) {
      gsap.fromTo(
        mediaTopText.value,
        { opacity: 0, y: 16 },
        { opacity: 1, y: 0, duration: 0.5, delay: 0.15, ease: "power2.out" },
      )
    }
  }
  // Subtle dot-row entrance on first show only; subsequent
  // navigation just lights up the next dot via CSS.
  if (dotRow.value && index.value === 0) {
    gsap.fromTo(
      dotRow.value,
      { opacity: 0 },
      { opacity: 1, duration: 0.4, delay: 0.3, ease: "power2.out" },
    )
  }
}

// Backdrop fade on every visible-flip. Cheap, keeps the overlay
// from popping in. On dismiss we also kill any GSAP tweens and
// drop the inline styles *synchronously*, before nextTick — by
// the time the DOM has been torn down by the v-if, the ref is
// already null and we can't reach into the leaving node.
watch(visible, (v, prev) => {
  // When transitioning from true→false the backdrop element is
  // still mounted for one tick (Vue's <Transition> keeps it
  // around for the leave animation). Capture it now.
  const el = backdrop.value
  if (el) {
    gsap.killTweensOf(el)
    el.style.opacity = ""
    el.style.transform = ""
  }
  if (v) {
    void nextTick().then(() => {
      if (backdrop.value) {
        gsap.fromTo(
          backdrop.value,
          { opacity: 0 },
          { opacity: 1, duration: 0.35, ease: "power2.out", onComplete: animateIn },
        )
      }
    })
  }
})

// Card-change animation.
watch(index, animateIn)
// Locale switch (Settings) — no animation, but a re-fetch keeps
// the backend's resolved title in sync with the new header for
// the next time the overlay opens.
watch(locale, () => {
  void store.reload()
})

// Keyboard navigation. Only active while the overlay is up so it
// doesn't fight the chat composer.
function onKey(e: KeyboardEvent) {
  if (!visible.value) return
  if (e.key === "Escape") {
    e.preventDefault()
    dismiss()
  } else if (e.key === "ArrowRight") {
    e.preventDefault()
    if (isLast.value) dismiss()
    else store.next()
  } else if (e.key === "ArrowLeft") {
    e.preventDefault()
    store.prev()
  } else if (e.key === "Enter") {
    e.preventDefault()
    if (isLast.value) dismiss()
    else store.next()
  }
}

onMounted(() => {
  window.addEventListener("keydown", onKey)
})

function nextOrDismiss() {
  if (isLast.value) dismiss()
  else store.next()
}
</script>

<template>
  <div
    v-if="visible && current"
    ref="backdrop"
    class="onboarding"
    role="dialog"
    aria-modal="true"
    aria-labelledby="onb-title"
  >
      <!-- The card itself. One of three layouts is rendered
           per card type; the rest are v-if'd away so DOM stays
           small. -->
      <div class="card" :data-type="current.type">
        <!-- Card 1: centered text, no media ──────────── -->
        <template v-if="current.type === 'centered'">
          <h1 ref="centeredTitle" id="onb-title" class="c-title">
            {{ displayTitle }}
          </h1>
          <p ref="centeredBody" class="c-body">{{ displayBody }}</p>
        </template>

        <!-- Card 2: media (left, big) + text (right, narrow) ── -->
        <template v-else-if="current.type === 'media-text'">
          <div
            ref="mediaLeftMedia"
            class="media-block"
            :style="{
              background: current.media_color || 'var(--accent)',
            }"
            aria-hidden="true"
          >
            <img
              v-if="current.media_image"
              :src="current.media_image"
              class="media-image"
              alt=""
            />
            <span v-if="!current.media_image" class="media-label">
              {{ current.media_label }}
            </span>
          </div>
          <div ref="mediaLeftText" class="text-block">
            <h2 id="onb-title" class="mt-title">{{ displayTitle }}</h2>
            <p class="mt-body">{{ displayBody }}</p>
          </div>
        </template>

        <!-- Card 3: media (top, tall) + text (bottom, short) ── -->
        <template v-else>
          <div
            ref="mediaTopMedia"
            class="media-block top"
            :style="{
              background: current.media_color || 'var(--accent)',
            }"
            aria-hidden="true"
          >
            <img
              v-if="current.media_image"
              :src="current.media_image"
              class="media-image"
              alt=""
            />
            <span v-if="!current.media_image" class="media-label big">
              {{ current.media_label }}
            </span>
          </div>
          <div ref="mediaTopText" class="text-block top">
            <h2 id="onb-title" class="mt-title">{{ displayTitle }}</h2>
            <p class="mt-body">{{ displayBody }}</p>
          </div>
        </template>
      </div>

      <!-- Controls ─────────────────────────────────── -->
      <div class="controls">
        <button
          v-if="index > 0"
          class="ghost"
          type="button"
          @click="store.prev()"
        >
          {{ index > 0 ? "‹" : "" }}
        </button>
        <div
          ref="dotRow"
          class="dots"
          role="group"
          :aria-label="t('onboarding.progressAria')"
        >
          <button
            v-for="(c, i) in store.cards"
            :key="c.id"
            type="button"
            class="dot"
            :class="{ active: i === index }"
            :aria-current="i === index ? 'step' : undefined"
            :aria-label="t('onboarding.stepOf', {
              current: i + 1,
              total: total,
            })"
            @click="store.goTo(i)"
          ></button>
        </div>
        <button class="primary" type="button" @click="nextOrDismiss">
          {{ primaryLabel }}
        </button>
      </div>
    </div>
</template>

<style scoped>
.onboarding {
  position: fixed;
  inset: 0;
  z-index: 1000;
  background: rgba(15, 16, 20, 0.78);
  backdrop-filter: blur(8px);
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 32px;
  color: #f5f5f7;
  /* The overlay is a passive walkthrough — users shouldn't be
     able to drag-select card text or images into the clipboard. */
  user-select: none;
  -webkit-user-select: none;
}

/* Card container. Aspect ratio varies per layout — see data-type
   selectors below. The width clamps so it doesn't fill absurd
   ultrawide monitors; on small screens it falls back to nearly
   full-bleed with sensible margins. */
.card {
  width: clamp(480px, 70vw, 960px);
  max-height: calc(100vh - 200px);
  background: rgba(20, 21, 26, 0.92);
  border: 1px solid rgba(255, 255, 255, 0.08);
  border-radius: 16px;
  padding: 48px;
  display: flex;
  box-shadow: 0 30px 60px rgba(0, 0, 0, 0.5);
  overflow: hidden;
}
.card[data-type="centered"] {
  flex-direction: column;
  align-items: center;
  justify-content: center;
  text-align: center;
  min-height: 360px;
}
.card[data-type="media-text"] {
  flex-direction: row;
  gap: 32px;
}
.card[data-type="media-top"] {
  flex-direction: column;
  gap: 24px;
  padding: 0;
}

/* Centered text styles. clamp() so the title scales with viewport
   without snapping on big screens. */
.c-title {
  font-size: clamp(36px, 5vw, 64px);
  font-weight: 600;
  letter-spacing: -0.02em;
  line-height: 1.1;
  margin: 0 0 20px;
}
.c-body {
  font-size: clamp(15px, 1.4vw, 18px);
  line-height: 1.65;
  max-width: 520px;
  color: rgba(255, 255, 255, 0.78);
  margin: 0;
}

/* Media-text layout: left media gets ~60% of width, right text
   column the remaining ~40%. */
.media-block {
  flex: 0 0 60%;
  border-radius: 12px;
  display: flex;
  align-items: center;
  justify-content: center;
  color: rgba(255, 255, 255, 0.92);
}
.text-block {
  flex: 1 1 40%;
  display: flex;
  flex-direction: column;
  justify-content: center;
  min-width: 0;
}
.mt-title {
  font-size: clamp(24px, 2.6vw, 36px);
  font-weight: 600;
  letter-spacing: -0.01em;
  line-height: 1.15;
  margin: 0 0 16px;
}
.mt-body {
  font-size: 15px;
  line-height: 1.65;
  color: rgba(255, 255, 255, 0.78);
  margin: 0;
}

/* Media-top variant: media takes the upper ~65% of the card,
   text the lower ~35%. Padding lives on the inner text-block so
   the media edge stays flush with the card border. */
.media-block.top {
  flex: 0 0 65%;
  border-radius: 12px 12px 0 0;
  min-height: 240px;
}
.media-label {
  font-size: 28px;
  font-weight: 600;
  letter-spacing: 0.06em;
  text-transform: uppercase;
}
.media-label.big {
  font-size: 56px;
  letter-spacing: 0.1em;
}

/* The illustration that replaces the colour block when the
   card carries ``media_image``. We size to the container so
   the layout doesn't shift between media_kind values, and let
   the SVG pick its own aspect ratio. */
.media-image {
  width: 100%;
  height: 100%;
  object-fit: contain;
  display: block;
  pointer-events: none;
}
.text-block.top {
  flex: 1 1 35%;
  padding: 0 32px 32px;
}

/* Controls bar. Three regions: optional back button (left),
   progress dots (centre), primary action (right). Centered
   horizontally with max-width matching the card so the controls
   visually belong to the card. */
.controls {
  margin-top: 24px;
  width: clamp(480px, 70vw, 960px);
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
}
.dots {
  display: flex;
  gap: 8px;
  flex: 1;
  justify-content: center;
}
.dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: rgba(255, 255, 255, 0.25);
  border: none;
  padding: 0;
  cursor: pointer;
  transition: background 0.2s ease, transform 0.2s ease;
}
.dot:hover {
  background: rgba(255, 255, 255, 0.45);
}
.dot.active {
  background: #fff;
  transform: scale(1.4);
}
.primary,
.ghost {
  font-family: inherit;
  font-size: 14px;
  border: none;
  border-radius: 999px;
  cursor: pointer;
  transition: background 0.15s ease, transform 0.1s ease;
}
.primary {
  background: #fff;
  color: #111;
  padding: 0 24px;
  height: 36px;
  font-weight: 500;
}
.primary:hover {
  background: rgba(255, 255, 255, 0.92);
}
.primary:active {
  transform: scale(0.98);
}
.ghost {
  background: transparent;
  color: rgba(255, 255, 255, 0.6);
  width: 36px;
  height: 36px;
  font-size: 18px;
}
.ghost:hover {
  color: rgba(255, 255, 255, 0.95);
  background: rgba(255, 255, 255, 0.08);
}

/* Vue's <Transition> wrapper was removed because GSAP's inline
   styles kept opacity pinned to 1 even after v-if flipped to
   false, so the leave animation never finished and the dialog
   got stuck in the DOM. The GSAP backdrop fade on enter is
   short enough (0.35s) that a hard unmount on dismiss isn't
   visually jarring. */

@media (max-width: 720px) {
  .card[data-type="media-text"] {
    flex-direction: column;
  }
  .media-block {
    flex-basis: 200px;
    flex-grow: 1;
  }
}
</style>