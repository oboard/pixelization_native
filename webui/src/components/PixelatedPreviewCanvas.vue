<script setup lang="ts">
import { onMounted, onUnmounted, ref, watch } from 'vue'
import type { MappedPixel } from '../utils/pixelation'

const props = defineProps<{
  mappedPixelData: MappedPixel[][] | null
  gridDimensions: { N: number; M: number } | null
  isManualColoringMode: boolean
  canvasRef: { current?: HTMLCanvasElement | null; value?: HTMLCanvasElement | null } | null
  onInteraction: (clientX: number, clientY: number, pageX: number, pageY: number, isClick: boolean, isTouchEnd?: boolean) => void
  highlightColorKey?: string | null
  onHighlightComplete?: () => void
}>()

const canvas = ref<HTMLCanvasElement | null>(null)
defineExpose({ canvas })
const darkMode = ref(false)
let observer: MutationObserver | null = null
let highlightTimer: ReturnType<typeof setTimeout> | null = null
let touchStart: { x: number; y: number; pageX: number; pageY: number } | null = null
let touchMoved = false

function draw(highlight: string | null = null) {
  const el = canvas.value
  const data = props.mappedPixelData
  const dims = props.gridDimensions
  if (!el || !data || !dims) return
  const ctx = el.getContext('2d')
  if (!ctx) return
  const cellWidth = el.width / dims.N
  const cellHeight = el.height / dims.M
  ctx.clearRect(0, 0, el.width, el.height)
  ctx.lineWidth = 0.5
  for (let row = 0; row < dims.M; row++) {
    for (let col = 0; col < dims.N; col++) {
      const pixel = data[row]?.[col]
      if (!pixel) continue
      const x = col * cellWidth
      const y = row * cellHeight
      ctx.fillStyle = pixel.isExternal ? (darkMode.value ? '#374151' : '#F3F4F6') : pixel.color
      ctx.fillRect(x, y, cellWidth, cellHeight)
      if (highlight && (pixel.isExternal || pixel.color.toUpperCase() !== highlight.toUpperCase())) {
        ctx.fillStyle = 'rgba(0, 0, 0, 0.6)'
        ctx.fillRect(x, y, cellWidth, cellHeight)
      }
      ctx.strokeStyle = darkMode.value ? '#4B5563' : '#DDDDDD'
      ctx.strokeRect(x + 0.5, y + 0.5, cellWidth, cellHeight)
    }
  }
}

watch(canvas, el => {
  if (props.canvasRef && typeof props.canvasRef === 'object') {
    if ('current' in props.canvasRef) props.canvasRef.current = el
    if ('value' in props.canvasRef) props.canvasRef.value = el
  }
}, { flush: 'post' })
watch(() => [props.mappedPixelData, props.gridDimensions, props.highlightColorKey, darkMode.value, canvas.value], () => draw(props.highlightColorKey), { flush: 'post' })
watch(() => [props.highlightColorKey, props.mappedPixelData, props.gridDimensions], () => {
  if (highlightTimer) clearTimeout(highlightTimer)
  if (props.highlightColorKey && props.mappedPixelData && props.gridDimensions) {
    highlightTimer = setTimeout(() => {
      draw()
      props.onHighlightComplete?.()
      highlightTimer = null
    }, 300)
  }
}, { immediate: true })
onMounted(() => {
  const checkDarkMode = () => { darkMode.value = document.documentElement.classList.contains('dark') }
  checkDarkMode()
  observer = new MutationObserver(checkDarkMode)
  observer.observe(document.documentElement, { attributes: true, attributeFilter: ['class'] })
})
onUnmounted(() => {
  observer?.disconnect()
  if (highlightTimer) clearTimeout(highlightTimer)
  if (props.canvasRef && typeof props.canvasRef === 'object') {
    if ('current' in props.canvasRef) props.canvasRef.current = null
    if ('value' in props.canvasRef) props.canvasRef.value = null
  }
})
function mouseMove(event: MouseEvent) {
  if (!props.isManualColoringMode) props.onInteraction(event.clientX, event.clientY, event.pageX, event.pageY, false)
}
function click(event: MouseEvent) {
  props.onInteraction(event.clientX, event.clientY, event.pageX, event.pageY, props.isManualColoringMode)
}
function touchBegin(event: TouchEvent) {
  const touch = event.touches[0]
  if (!touch) return
  touchStart = { x: touch.clientX, y: touch.clientY, pageX: touch.pageX, pageY: touch.pageY }
  touchMoved = false
  if (!props.isManualColoringMode) props.onInteraction(touch.clientX, touch.clientY, touch.pageX, touch.pageY, false)
}
function touchMove(event: TouchEvent) {
  const touch = event.touches[0]
  if (!touch || !touchStart) return
  if (!touchMoved && (Math.abs(touch.clientX - touchStart.x) > 10 || Math.abs(touch.clientY - touchStart.y) > 10)) {
    touchMoved = true
    props.onInteraction(0, 0, 0, 0, false, true)
  }
}
function touchEnd() {
  if (props.isManualColoringMode && !touchMoved && touchStart) {
    props.onInteraction(touchStart.x, touchStart.y, touchStart.pageX, touchStart.pageY, true)
  }
  touchStart = null
  touchMoved = false
}
</script>

<template>
  <canvas
    ref="canvas"
    class="border border-gray-300 dark:border-gray-600 max-w-full h-auto rounded block"
    :class="isManualColoringMode ? 'cursor-pointer' : 'cursor-grab'"
    :style="{ imageRendering: 'pixelated' }"
    @mousemove="mouseMove"
    @mouseleave="onInteraction(0, 0, 0, 0, false, true)"
    @click="click"
    @touchstart="touchBegin"
    @touchmove="touchMove"
    @touchend="touchEnd"
    @touchcancel="touchEnd"
  />
</template>
