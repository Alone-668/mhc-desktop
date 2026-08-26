<script setup lang="ts">
// Usage-metrics dashboard view.
//
// The data flows from three backend endpoints:
//   - GET /api/v1/metrics/summary  (top cards, single number each)
//   - GET /api/v1/metrics/trend    (one point per day for the chart)
//   - GET /api/v1/metrics/ranking  (server-paginated per-kind ranking)
//
// Today vs historical: today's numbers come from a separate
// ``date_from=today&date_to=today`` query so the user sees the
// delta between "now" and "all-time". One network roundtrip per
// query — concurrent via Promise.all.
//
// The trend chart is hand-rolled SVG (was Frappe Charts in a
// previous revision) — Frappe silently dropped the last data
// point, generated auto-ticks that overrode our date labels, and
// truncated every label to ``"20.."`` when the parent layout
// settled after chart creation. Doing it ourselves keeps the
// labels, tooltips and rendering under our control with ~60
// lines of plain SVG.
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from "vue"
import {
  api,
  type MetricsRankingKind,
  type MetricsRankingPage,
  type MetricsSummary,
  type MetricsTrend,
  type MetricsTrendPoint,
} from "../api/client"
import { t } from "../i18n"

// ── Range selector ──────────────────────────────────────────────────────────

type Range = "7" | "30" | "all"

function todayStr(): string {
  const d = new Date()
  return (
    d.getFullYear() +
    "-" +
    String(d.getMonth() + 1).padStart(2, "0") +
    "-" +
    String(d.getDate()).padStart(2, "0")
  )
}

function daysAgo(n: number): string {
  const d = new Date()
  d.setDate(d.getDate() - n)
  return (
    d.getFullYear() +
    "-" +
    String(d.getMonth() + 1).padStart(2, "0") +
    "-" +
    String(d.getDate()).padStart(2, "0")
  )
}

const range = ref<Range>("30")

const rangeDates = computed<{ from: string | undefined; to: string | undefined }>(
  () => {
    if (range.value === "7") return { from: daysAgo(6), to: todayStr() }
    if (range.value === "30") return { from: daysAgo(29), to: todayStr() }
    return { from: undefined, to: undefined }
  },
)

const today = todayStr()

// ── Data fetch ───────────────────────────────────────────────────────────────

const summaryAll = ref<MetricsSummary | null>(null)
const summaryToday = ref<MetricsSummary | null>(null)
const trend = ref<MetricsTrend | null>(null)
const rankings = ref<
  Record<MetricsRankingKind, MetricsRankingPage | null>
>({
  tools: null,
  skills: null,
  mcps: null,
  models: null,
})
const loading = ref(false)
const error = ref<string | null>(null)
const lastUpdated = ref<string | null>(null)

async function loadAll() {
  loading.value = true
  error.value = null
  try {
    const [sAll, sToday, tr, rt, rs, rm, rmc] = await Promise.all([
      api.metrics.summary({}),
      api.metrics.summary({ date_from: today, date_to: today }),
      api.metrics.trend({
        date_from: rangeDates.value.from,
        date_to: rangeDates.value.to,
      }),
      api.metrics.ranking({
        kind: "tools",
        page: 1,
        page_size: 10,
        date_from: rangeDates.value.from,
        date_to: rangeDates.value.to,
      }),
      api.metrics.ranking({
        kind: "skills",
        page: 1,
        page_size: 10,
        date_from: rangeDates.value.from,
        date_to: rangeDates.value.to,
      }),
      api.metrics.ranking({
        kind: "models",
        page: 1,
        page_size: 10,
        date_from: rangeDates.value.from,
        date_to: rangeDates.value.to,
      }),
      api.metrics.ranking({
        kind: "mcps",
        page: 1,
        page_size: 10,
        date_from: rangeDates.value.from,
        date_to: rangeDates.value.to,
      }),
    ])
    summaryAll.value = sAll
    summaryToday.value = sToday
    trend.value = tr
    rankings.value.tools = rt
    rankings.value.skills = rs
    rankings.value.models = rm
    rankings.value.mcps = rmc
    lastUpdated.value = new Date().toLocaleTimeString()
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e)
  } finally {
    loading.value = false
    // First paint: hand-rolled SVG chart is fully reactive — no
    // explicit create call needed. ``chartGeom`` re-computes when
    // ``trendPoints`` changes, and the template re-renders the
    // <path> / <circle> elements. Nothing else to do.
    void nextTick()
  }
}

onMounted(loadAll)
watch(range, loadAll)

// ── Formatting helpers ──────────────────────────────────────────────────────

function fmtInt(n: number): string {
  return n.toLocaleString()
}

function fmtPct(n: number): string {
  if (!Number.isFinite(n)) return "—"
  return (n * 100).toFixed(1) + "%"
}

function fmtMs(n: number): string {
  if (!Number.isFinite(n) || n <= 0) return "—"
  if (n < 1000) return Math.round(n) + " ms"
  return (n / 1000).toFixed(2) + " s"
}

/**
 * Compact token count formatter. Big numbers become ``12.3K``,
 * ``4.5M`` so the chart's tick labels and the card values stay
 * readable when a user has millions of tokens accumulated. Falls
 * back to the raw integer for anything under 1k.
 */
function fmtTokens(n: number): string {
  if (!Number.isFinite(n)) return "—"
  const abs = Math.abs(n)
  if (abs < 1000) return String(Math.round(n))
  if (abs < 1_000_000) return (n / 1000).toFixed(abs < 10_000 ? 2 : 1) + "K"
  if (abs < 1_000_000_000) return (n / 1_000_000).toFixed(abs < 10_000_000 ? 2 : 1) + "M"
  return (n / 1_000_000_000).toFixed(2) + "B"
}

// Tool error rate ranking is derived from the same records, sorted
// by error_rate desc — the backend's ``query_ranking(kind="tools")``
// returns rows sorted by count desc. We re-sort client-side: error
// rate is a tiny list (page_size=10), so this is free.
const toolErrors = computed(() => {
  const page = rankings.value.tools
  if (!page || page.items.length === 0) return []
  return [...page.items]
    .filter((it) => it.count > 0)
    .sort((a, b) => {
      if (b.error_rate !== a.error_rate) return b.error_rate - a.error_rate
      return b.count - a.count
    })
})

// ── Trend chart (hand-rolled SVG) ───────────────────────────────────────────────────────────────────────
//
// Daily token consumption is the headline metric — call counts
// are noisy (a long conversation looks like 30 calls, a short
// one looks like 1, both cost roughly the same). Tokens aggregate
// directly into money.
//
// Implementation: plain SVG path + area, mouse-position-to-index
// lookup for the tooltip. ~60 lines, no library, full control
// over labels and hover behaviour.

const trendPoints = computed<MetricsTrendPoint[]>(() => trend.value?.points ?? [])

const CHART_W = 720
const CHART_H = 200
const CHART_PAD_X = 40
const CHART_PAD_Y = 18

interface ChartGeometry {
  width: number
  height: number
  padX: number
  padY: number
  pts: MetricsTrendPoint[]
  values: number[]
  maxY: number
  xPositions: number[]
  yScale: (v: number) => number
  pathD: string
  areaD: string
  xLabels: { x: number; label: string }[]
  yLabels: { y: number; label: string }[]
}

const chartGeom = computed<ChartGeometry | null>(() => {
  const pts = trendPoints.value
  if (pts.length === 0) return null
  const values = pts.map((p) => p.total_tokens)
  // Round max up to a "nice" number so the y-axis ticks are at
  // 1 / 2 / 5 × 10^n intervals instead of arbitrary heights.
  const maxRaw = Math.max(1, ...values)
  const niceMax = niceCeil(maxRaw)
  const width = CHART_W
  const height = CHART_H
  const padX = CHART_PAD_X
  const padY = CHART_PAD_Y
  const xStep = (width - padX * 2) / Math.max(1, pts.length - 1)
  const yScale = (v: number) =>
    height - padY - (v / niceMax) * (height - padY * 2)
  const xPositions = pts.map((_, i) => padX + i * xStep)
  let pathD = ""
  let areaD = ""
  pts.forEach((_, i) => {
    const x = xPositions[i]
    const y = yScale(values[i])
    pathD += (i === 0 ? "M" : "L") + x + "," + y + " "
    if (i === 0) areaD += "M" + x + "," + (height - padY) + " "
    areaD += "L" + x + "," + y + " "
  })
  areaD +=
    "L" + xPositions[xPositions.length - 1] + "," + (height - padY) + " Z"
  // Pick ~5 evenly-spaced x-axis labels so the dates stay
  // legible without crowding the bottom edge.
  const labelEvery = Math.max(1, Math.floor(pts.length / 5))
  const xLabels = pts
    .map((p, i) => ({ p, i }))
    .filter(({ i }) => i % labelEvery === 0 || i === pts.length - 1)
    .map(({ p, i }) => ({
      x: xPositions[i],
      label: p.date.slice(5), // MM-DD
    }))
  // 4 y-axis ticks (0, 1/4, 1/2, full). Values shown in compact
  // K/M form so the side labels stay narrow.
  const yLabels = [
    { y: height - padY, label: "0" },
    { y: yScale(niceMax / 4), label: fmtTokens(niceMax / 4) },
    { y: yScale(niceMax / 2), label: fmtTokens(niceMax / 2) },
    { y: yScale(niceMax), label: fmtTokens(niceMax) },
  ]
  return {
    width,
    height,
    padX,
    padY,
    pts,
    values,
    maxY: niceMax,
    xPositions,
    yScale,
    pathD: pathD.trim(),
    areaD,
    xLabels,
    yLabels,
  }
})

/**
 * Round ``v`` up to the next 1/2/5 × 10^n value. Used so the y-axis
 * ceiling is always a friendly round number rather than a raw max
 * (e.g. 28941 → 30000, 247 → 250).
 */
function niceCeil(v: number): number {
  if (v <= 0) return 1
  const exp = Math.floor(Math.log10(v))
  const base = Math.pow(10, exp)
  const m = v / base
  let nice: number
  if (m <= 1) nice = 1
  else if (m <= 2) nice = 2
  else if (m <= 5) nice = 5
  else nice = 10
  return nice * base
}

// Hover state: which data point the mouse is over.
const hoverIdx = ref<number>(-1)
const svgRef = ref<SVGSVGElement | null>(null)
// ``trendCanvas`` is the host div containing the SVG; we need
// its pixel dimensions to map SVG coords to pixel positions for
// the HTML tooltip. The SVG uses preserveAspectRatio="none" so
// the ratio SVG-units → CSS-pixels is the wrapper's width / the
// chart's viewBox width.
const trendCanvas = ref<HTMLDivElement | null>(null)
// Pixel size of the rendered SVG, kept reactive so the tooltip
// and dot-ellipse radii recompute when the window resizes.
const svgSize = ref<{ width: number; height: number }>({ width: 0, height: 0 })
let svgResizeObserver: ResizeObserver | null = null

onMounted(() => {
  // The SVG is rendered with preserveAspectRatio="none" so it
  // stretches non-uniformly to fit its container — the wrapper
  // width is 100% but the height is fixed at 220px, so the two
  // scales are rarely equal. Watch the actual rendered box so
  // we can (a) place the tooltip in pixel coords and (b) draw
  // the dots as <ellipse> with rx/ry that compensates for the
  // aspect mismatch and still appears as a true circle on screen.
  if (svgRef.value) {
    svgResizeObserver = new ResizeObserver((entries) => {
      const e = entries[0]
      if (!e) return
      svgSize.value = {
        width: e.contentRect.width,
        height: e.contentRect.height,
      }
    })
    svgResizeObserver.observe(svgRef.value)
  }
})

onBeforeUnmount(() => {
  svgResizeObserver?.disconnect()
  svgResizeObserver = null
})

function onChartMove(e: MouseEvent) {
  const g = chartGeom.value
  const svg = svgRef.value
  if (!g || !svg) return
  // Convert mouse x (client px) to SVG's internal coordinate
  // system. The viewBox makes SVG coords a 1:1 mapping of the
  // declared width.
  const rect = svg.getBoundingClientRect()
  const svgX = ((e.clientX - rect.left) / rect.width) * g.width
  // Find the nearest data point along the x-axis.
  let best = 0
  let bestDist = Infinity
  for (let i = 0; i < g.xPositions.length; i++) {
    const d = Math.abs(g.xPositions[i] - svgX)
    if (d < bestDist) {
      bestDist = d
      best = i
    }
  }
  hoverIdx.value = best
}

function onChartLeave() {
  hoverIdx.value = -1
}

const hoverPoint = computed(() => {
  const g = chartGeom.value
  if (!g || hoverIdx.value < 0 || hoverIdx.value >= g.pts.length) return null
  const p = g.pts[hoverIdx.value]
  return {
    date: p.date,
    value: p.total_tokens,
    x: g.xPositions[hoverIdx.value],
    y: g.yScale(g.values[hoverIdx.value]),
  }
})

/**
 * Position the HTML tooltip relative to the chart-wrap. The SVG
 * has ``preserveAspectRatio="none"`` so the SVG's internal
 * coordinate system stretches uniformly to the wrapper's box.
 * The tooltip hovers above the dot; when the dot is close to
 * the right edge we flip the box to the left so it doesn't
 * overflow.
 */
const tipStyle = computed(() => {
  const g = chartGeom.value
  const hp = hoverPoint.value
  if (!g || !hp) return {}
  // ``svgSize`` is updated by a ResizeObserver on the SVG, so
  // this re-runs whenever the wrapper size changes (window
  // resize, sidebar collapse, etc.).
  const widthPx = svgSize.value.width || g.width
  const heightPx = svgSize.value.height || g.height
  const xRatio = widthPx / g.width
  const yRatio = heightPx / g.height
  const dotXPx = hp.x * xRatio
  const dotYPx = hp.y * yRatio
  // Tooltip box: 160px wide, 40px tall. Place above the dot; if
  // the dot is in the rightmost 170px, flip left.
  const TW = 160
  const TH = 40
  const left = dotXPx + TW + 12 > widthPx ? dotXPx - TW - 8 : dotXPx + 8
  const top = Math.max(0, dotYPx - TH - 8)
  return {
    position: "absolute" as const,
    left: `${left}px`,
    top: `${top}px`,
    width: `${TW}px`,
  }
})

/**
 * Per-axis pixel scale derived from the SVG's actual rendered
 * size vs. its viewBox. Used to draw dots as <ellipse> so they
 * appear as perfect circles on screen despite the SVG's
 * non-uniform stretching (preserveAspectRatio="none").
 *
 * Falls back to a uniform 1.0 scale when svgSize hasn't been
 * observed yet (first paint) — the dots will be slightly
 * off-shape for one frame, then snap into place on the next
 * tick once ResizeObserver fires.
 */
const dotRadii = computed(() => {
  const g = chartGeom.value
  if (!g) return { normal: { rx: 3, ry: 3 }, hover: { rx: 6, ry: 6 } }
  const widthPx = svgSize.value.width || g.width
  const heightPx = svgSize.value.height || g.height
  const sx = widthPx / g.width || 1
  const sy = heightPx / g.height || 1
  return {
    normal: { rx: 3 / sx, ry: 3 / sy },
    hover: { rx: 6 / sx, ry: 6 / sy },
  }
})

// ── Templates ───────────────────────────────────────────────────────────────

const anyData = computed(() => {
  const s = summaryAll.value
  return !!s && s.llm_call_count > 0
})
</script>

<template>
  <section class="page">
    <header class="head">
      <div>
        <h1>{{ t("metrics.title") }}</h1>
        <p class="muted">{{ t("metrics.subtitle") }}</p>
      </div>
      <div class="head-controls">
        <div class="range" role="radiogroup" :aria-label="t('metrics.title')">
          <button
            type="button"
            class="range-btn"
            :class="{ active: range === '7' }"
            @click="range = '7'"
          >
            {{ t("metrics.range7") }}
          </button>
          <button
            type="button"
            class="range-btn"
            :class="{ active: range === '30' }"
            @click="range = '30'"
          >
            {{ t("metrics.range30") }}
          </button>
          <button
            type="button"
            class="range-btn"
            :class="{ active: range === 'all' }"
            @click="range = 'all'"
          >
            {{ t("metrics.rangeAll") }}
          </button>
        </div>
        <button
          type="button"
          class="refresh"
          :disabled="loading"
          @click="loadAll"
        >
          {{ t("metrics.refresh") }}
        </button>
      </div>
    </header>

    <p v-if="error" class="status error">
      {{ t("metrics.error", { message: error }) }}
    </p>
    <p v-if="lastUpdated && !error" class="status">
      {{ t("metrics.refreshed", { time: lastUpdated }) }}
    </p>

    <div v-if="loading && !summaryAll" class="loading">
      {{ t("common.loading") }}
    </div>

    <template v-else-if="!anyData">
      <div class="empty">{{ t("metrics.empty") }}</div>
    </template>

    <template v-else>
      <!-- Cards -->
      <div class="cards-grid">
          <article class="card">
            <div class="card-label">
              {{ t("metrics.cards.todayConversations") }}
            </div>
            <div class="card-value">{{
              fmtInt(summaryToday?.conversation_count ?? 0)
            }}</div>
            <div class="card-sub">
              {{ t("metrics.cards.totalConversations") }} ·
              {{ fmtInt(summaryAll?.conversation_count ?? 0) }}
            </div>
          </article>
          <article class="card">
            <div class="card-label">
              {{ t("metrics.cards.todayTokens") }}
            </div>
            <div class="card-value">{{
              fmtTokens(summaryToday?.total_tokens ?? 0)
            }}</div>
            <div class="card-sub">
              {{ t("metrics.cards.totalTokens") }} ·
              {{ fmtTokens(summaryAll?.total_tokens ?? 0) }}
            </div>
          </article>
          <article class="card">
            <div class="card-label">
              {{ t("metrics.cards.todayToolCalls") }}
            </div>
            <div class="card-value">
              {{
                fmtInt(
                  (summaryToday?.tool_call_count ?? 0) +
                    (summaryToday?.skill_call_count ?? 0) +
                    (summaryToday?.mcp_call_count ?? 0),
                )
              }}
            </div>
            <div class="card-sub">
              {{ t("metrics.cards.totalToolCalls") }} ·
              {{
                fmtInt(
                  (summaryAll?.tool_call_count ?? 0) +
                    (summaryAll?.skill_call_count ?? 0) +
                    (summaryAll?.mcp_call_count ?? 0),
                )
              }}
            </div>
          </article>
          <article class="card">
            <div class="card-label">
              {{ t("metrics.cards.avgTokensPerCall") }}
            </div>
            <div class="card-value">
              {{ fmtTokens(Math.round(summaryAll?.avg_tokens_per_call ?? 0)) }}
            </div>
            <div class="card-sub">
              {{ t("metrics.cards.errorRate") }} ·
              {{ fmtPct(summaryAll?.error_rate ?? 0) }}
            </div>
          </article>
          <article class="card">
            <div class="card-label">
              {{ t("metrics.cards.avgDuration") }}
            </div>
            <div class="card-value">
              {{ fmtMs(summaryAll?.avg_duration_ms ?? 0) }}
            </div>
            <div class="card-sub">
              {{ t("metrics.cards.totalTokensTotal") }} ·
              {{ fmtTokens(summaryAll?.total_tokens ?? 0) }}
            </div>
          </article>
        </div>

      <!-- Trend -->
      <section class="panel">
        <h2>{{ t("metrics.trend.title") }}</h2>
        <div v-if="!chartGeom" class="muted">
          {{ t("metrics.rankings.empty") }}
        </div>
        <div v-else ref="trendCanvas" class="chart-wrap">
          <svg
            ref="svgRef"
            :viewBox="`0 0 ${chartGeom.width} ${chartGeom.height}`"
            preserveAspectRatio="none"
            class="chart"
            role="img"
            :aria-label="t('metrics.trend.title')"
            @mousemove="onChartMove"
            @mouseleave="onChartLeave"
          >
            <!-- Area fill under the line -->
            <path
              :d="chartGeom.areaD"
              fill="var(--accent-soft)"
              stroke="none"
            />
            <!-- The line itself -->
            <path
              :d="chartGeom.pathD"
              fill="none"
              stroke="var(--accent)"
              stroke-width="2"
              stroke-linejoin="round"
              stroke-linecap="round"
            />
            <!-- Per-day dots, drawn as <ellipse> with rx/ry
                 compensating for the SVG's non-uniform stretch
                 (preserveAspectRatio="none") so each one looks
                 like a true circle on screen. -->
            <g class="dots">
              <ellipse
                v-for="(x, i) in chartGeom.xPositions"
                :key="i"
                :cx="x"
                :cy="chartGeom.yScale(chartGeom.values[i])"
                :rx="hoverIdx === i ? dotRadii.hover.rx : dotRadii.normal.rx"
                :ry="hoverIdx === i ? dotRadii.hover.ry : dotRadii.normal.ry"
                :fill="hoverIdx === i ? 'var(--accent)' : 'var(--bg)'"
                stroke="var(--accent)"
                stroke-width="2"
              />
            </g>
            <!-- X-axis baseline + sparse date labels (MM-DD) -->
            <line
              :x1="chartGeom.padX"
              :y1="chartGeom.height - chartGeom.padY"
              :x2="chartGeom.width - chartGeom.padX"
              :y2="chartGeom.height - chartGeom.padY"
              stroke="var(--border)"
            />
            <g class="x-labels">
              <text
                v-for="(l, i) in chartGeom.xLabels"
                :key="'xl'+i"
                :x="l.x"
                :y="chartGeom.height - 4"
                text-anchor="middle"
                fill="var(--text-faint)"
                font-size="10"
              >
                {{ l.label }}
              </text>
            </g>
            <!-- Y-axis tick labels (compact K/M) -->
            <g class="y-labels">
              <text
                v-for="(l, i) in chartGeom.yLabels"
                :key="'yl'+i"
                :x="chartGeom.padX - 6"
                :y="l.y + 4"
                text-anchor="end"
                fill="var(--text-faint)"
                font-size="10"
              >
                {{ l.label }}
              </text>
            </g>
            <!-- Vertical crosshair at the hovered x position.
                 The hover-marker circle is drawn here too so it
                 scales with the SVG. The actual tooltip BOX is
                 rendered as a sibling <div> in HTML (below) for
                 two reasons: (a) Vue scoped CSS reliably reaches
                 it there — foreignObject content lives in a
                 separate namespace and the data-v attribute
                 doesn't always propagate; (b) a plain <div>
                 stacks cleanly with z-index instead of fighting
                 SVG paint order. -->
            <g v-if="hoverPoint" class="hover-marker">
              <line
                :x1="hoverPoint.x"
                :y1="chartGeom.padY"
                :x2="hoverPoint.x"
                :y2="chartGeom.height - chartGeom.padY"
                stroke="var(--accent)"
                stroke-dasharray="3 3"
                stroke-width="1"
                opacity="0.5"
              />
              <ellipse
                :cx="hoverPoint.x"
                :cy="hoverPoint.y"
                :rx="dotRadii.hover.rx"
                :ry="dotRadii.hover.ry"
                fill="var(--accent)"
                stroke="var(--bg)"
                stroke-width="2"
              />
            </g>
          </svg>
          <!-- HTML tooltip — positioned in chart-wrap coords. We
               map hoverPoint.x (SVG units, 0..CHART_W) to the
               actual pixel position by ratio, since the SVG uses
               preserveAspectRatio="none" and stretches to fill
               the wrapper. -->
          <div
            v-if="hoverPoint"
            class="chart-tip"
            :style="tipStyle"
          >
            <div class="chart-tip-date">{{ hoverPoint.date }}</div>
            <div class="chart-tip-value">
              {{ fmtTokens(hoverPoint.value) }} {{ t("metrics.trend.tokens") }}
            </div>
          </div>
        </div>
      </section>

      <!-- Rankings -->
      <section class="rankings-grid">
        <article class="panel ranking">
          <header class="rank-head">
            <h2>{{ t("metrics.rankings.tools") }}</h2>
            <span class="rank-count">
              {{ t("metrics.col.total", { total: rankings.tools?.total ?? 0 }) }}
            </span>
          </header>
          <table v-if="rankings.tools && rankings.tools.items.length > 0">
            <thead>
              <tr>
                <th>{{ t("metrics.col.name") }}</th>
                <th class="num">{{ t("metrics.col.count") }}</th>
                <th class="num">{{ t("metrics.col.errors") }}</th>
                <th class="num">{{ t("metrics.col.errorRate") }}</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="it in rankings.tools.items" :key="it.name">
                <td class="ellipsis">{{ it.name }}</td>
                <td class="num">{{ it.count }}</td>
                <td class="num">{{ it.error_count }}</td>
                <td class="num">{{ fmtPct(it.error_rate) }}</td>
              </tr>
            </tbody>
          </table>
          <div v-else class="muted">{{ t("metrics.rankings.empty") }}</div>
        </article>

        <article class="panel ranking">
          <header class="rank-head">
            <h2>{{ t("metrics.rankings.toolErrors") }}</h2>
          </header>
          <table v-if="toolErrors.length > 0">
            <thead>
              <tr>
                <th>{{ t("metrics.col.name") }}</th>
                <th class="num">{{ t("metrics.col.errorRate") }}</th>
                <th class="num">{{ t("metrics.col.count") }}</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="it in toolErrors" :key="it.name">
                <td class="ellipsis">{{ it.name }}</td>
                <td class="num">{{ fmtPct(it.error_rate) }}</td>
                <td class="num">{{ it.count }}</td>
              </tr>
            </tbody>
          </table>
          <div v-else class="muted">{{ t("metrics.rankings.empty") }}</div>
        </article>

        <article class="panel ranking">
          <header class="rank-head">
            <h2>{{ t("metrics.rankings.skills") }}</h2>
            <span class="rank-count">
              {{ t("metrics.col.total", { total: rankings.skills?.total ?? 0 }) }}
            </span>
          </header>
          <table v-if="rankings.skills && rankings.skills.items.length > 0">
            <thead>
              <tr>
                <th>{{ t("metrics.col.name") }}</th>
                <th class="num">{{ t("metrics.col.count") }}</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="it in rankings.skills.items" :key="it.name">
                <td class="ellipsis">{{ it.name }}</td>
                <td class="num">{{ it.count }}</td>
              </tr>
            </tbody>
          </table>
          <div v-else class="muted">{{ t("metrics.rankings.empty") }}</div>
        </article>

        <article class="panel ranking">
          <header class="rank-head">
            <h2>{{ t("metrics.rankings.mcps") }}</h2>
            <span class="rank-count">
              {{ t("metrics.col.total", { total: rankings.mcps?.total ?? 0 }) }}
            </span>
          </header>
          <table v-if="rankings.mcps && rankings.mcps.items.length > 0">
            <thead>
              <tr>
                <th>{{ t("metrics.col.name") }}</th>
                <th class="num">{{ t("metrics.col.count") }}</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="it in rankings.mcps.items" :key="it.name">
                <td class="ellipsis">{{ it.name }}</td>
                <td class="num">{{ it.count }}</td>
              </tr>
            </tbody>
          </table>
          <div v-else class="muted">{{ t("metrics.rankings.empty") }}</div>
        </article>
      </section>

      <!-- Models (full-width table) -->
      <section class="panel">
        <header class="rank-head">
          <h2>{{ t("metrics.rankings.models") }}</h2>
          <span class="rank-count">
            {{ t("metrics.col.total", { total: rankings.models?.total ?? 0 }) }}
          </span>
        </header>
        <table
          v-if="rankings.models && rankings.models.items.length > 0"
          class="models-table"
        >
          <thead>
            <tr>
              <th>{{ t("metrics.col.name") }}</th>
              <th class="num">{{ t("metrics.col.calls") }}</th>
              <th class="num">{{ t("metrics.col.avg") }}</th>
              <th class="num">{{ t("metrics.col.avgTokens") }}</th>
              <th class="num">{{ t("metrics.col.p50") }}</th>
              <th class="num">{{ t("metrics.col.p95") }}</th>
              <th class="num">{{ t("metrics.col.p99") }}</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="it in rankings.models.items" :key="it.name">
              <td class="ellipsis">{{ it.name }}</td>
              <td class="num">{{ it.count }}</td>
              <td class="num">{{ fmtMs(it.avg_duration_ms) }}</td>
              <td class="num">{{ fmtInt(it.avg_tokens) }}</td>
              <td class="num">{{ fmtMs(it.p50_ms) }}</td>
              <td class="num">{{ fmtMs(it.p95_ms) }}</td>
              <td class="num">{{ fmtMs(it.p99_ms) }}</td>
            </tr>
          </tbody>
        </table>
        <div v-else class="muted">{{ t("metrics.models.empty") }}</div>
      </section>
    </template>
  </section>
</template>

<style scoped>
.page {
  display: flex;
  flex-direction: column;
  gap: 20px;
  padding: 28px 32px 64px;
  max-width: 1200px;
  margin: 0 auto;
  width: 100%;
  /* Match SkillsView et al. — the .center container in App.vue is
     ``overflow: hidden``, so without our own scroll container here
     any content past the viewport is silently clipped. ``height:
     100%`` claims the whole pane; ``overflow-y: auto`` gives the
     user a scrollbar when the dashboard grows tall (it does —
     cards + chart + 4 ranking panels + the wide model table). */
  height: 100%;
  overflow-y: auto;
  box-sizing: border-box;
}
.head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  flex-wrap: wrap;
}
.head h1 {
  margin: 0;
  font-size: 22px;
  font-weight: 600;
  color: var(--text);
}
.muted {
  color: var(--text-mid);
  margin: 4px 0 0;
  font-size: 13px;
}
.head-controls {
  display: flex;
  align-items: center;
  gap: 12px;
}
.range {
  display: inline-flex;
  background: var(--bg-panel);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 2px;
}
.range-btn {
  border: 0;
  background: transparent;
  color: var(--text-mid);
  font: inherit;
  font-size: 12.5px;
  padding: 5px 12px;
  border-radius: 6px;
  cursor: pointer;
  transition: background 120ms ease, color 120ms ease;
}
.range-btn:hover {
  background: var(--bg-hover);
  color: var(--text);
}
.range-btn.active {
  background: var(--accent);
  color: var(--accent-fg, white);
}
.refresh {
  border: 1px solid var(--border);
  background: var(--bg-panel);
  color: var(--text);
  font: inherit;
  font-size: 12.5px;
  padding: 6px 14px;
  border-radius: 8px;
  cursor: pointer;
  transition: background 120ms ease;
}
.refresh:hover:not(:disabled) {
  background: var(--bg-hover);
}
.refresh:disabled {
  opacity: 0.55;
  cursor: not-allowed;
}
.status {
  margin: 0;
  font-size: 12.5px;
  color: var(--text-mid);
}
.status.error {
  color: var(--danger, #c0392b);
}
.loading,
.empty {
  padding: 40px;
  text-align: center;
  color: var(--text-mid);
  background: var(--bg-panel);
  border: 1px solid var(--border);
  border-radius: 12px;
}
.cards-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
  gap: 12px;
}
.card {
  background: var(--bg-panel);
  border: 1px solid var(--border);
  border-radius: 12px;
  padding: 14px 16px;
}
.card-label {
  font-size: 11.5px;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.04em;
  color: var(--text-mid);
}
.card-value {
  font-size: 26px;
  font-weight: 700;
  margin-top: 6px;
  color: var(--text);
  font-variant-numeric: tabular-nums;
}
.card-sub {
  font-size: 12px;
  color: var(--text-faint);
  margin-top: 4px;
  font-variant-numeric: tabular-nums;
}
.panel {
  background: var(--bg-panel);
  border: 1px solid var(--border);
  border-radius: 12px;
  padding: 18px 18px 14px;
}
.panel h2 {
  margin: 0;
  font-size: 14px;
  font-weight: 600;
  color: var(--text);
}
.rank-head {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  margin-bottom: 10px;
  gap: 8px;
}
.rank-count {
  font-size: 11.5px;
  color: var(--text-faint);
  font-variant-numeric: tabular-nums;
}
.chart-wrap {
  width: 100%;
  /* preserveAspectRatio="none" on the SVG makes it stretch to
     its container; the viewBox keeps the line geometry stable
     regardless of width. */
  min-height: 220px;
  /* Anchoring context for the absolutely-positioned tooltip:
     without this it would float up to the nearest positioned
     ancestor (the .panel above, or further) and land far from
     the dot. */
  position: relative;
}
.chart-wrap .chart {
  display: block;
  width: 100%;
  height: 220px;
  cursor: crosshair;
}
/*
 * Tooltip is a plain <div> in the chart-wrap subtree (not inside
 * the SVG), so Vue's scoped CSS reaches it normally — no
 * :deep() needed. The div is positioned in CSS pixels via the
 * ``:style`` binding (tipStyle computed).
 */
.chart-tip {
  background: var(--bg-panel);
  color: var(--text);
  border: 1px solid var(--border);
  border-radius: 6px;
  padding: 6px 10px;
  font-size: 12px;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.2);
  pointer-events: none;
  min-width: 140px;
  z-index: 10;
}
.chart-tip-date {
  color: var(--text-mid);
  font-weight: 600;
  margin-bottom: 2px;
}
.chart-tip-value {
  color: var(--accent);
  font-weight: 600;
}
.rankings-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(320px, 1fr));
  gap: 12px;
}
.ranking {
  padding: 14px;
}
table {
  width: 100%;
  border-collapse: collapse;
  font-size: 12.5px;
}
thead th {
  text-align: left;
  font-weight: 600;
  font-size: 11px;
  color: var(--text-mid);
  text-transform: uppercase;
  letter-spacing: 0.04em;
  padding: 6px 8px;
  border-bottom: 1px solid var(--border);
}
tbody td {
  padding: 7px 8px;
  border-bottom: 1px solid var(--border);
  color: var(--text);
  font-variant-numeric: tabular-nums;
}
tbody tr:last-child td {
  border-bottom: 0;
}
.ellipsis {
  max-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.num {
  text-align: right;
}
.models-table {
  font-size: 12.5px;
}
</style>