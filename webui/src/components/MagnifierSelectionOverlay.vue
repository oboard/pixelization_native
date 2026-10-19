<script setup lang="ts">
import { isRef, onUnmounted, ref, watch, type CSSProperties, type Ref } from 'vue'

interface SelectionArea {
  startRow: number
  startCol: number
  endRow: number
  endCol: number
}

const props = defineProps<{
  isActive: boolean
  canvasRef: Ref<HTMLCanvasElement | null> | { current: HTMLCanvasElement | null } | HTMLCanvasElement | null
  gridDimensions: { N: number; M: number } | null
  cellSize: number
  onSelectionComplete: (area: SelectionArea) => void
}>()

const isSelecting = ref(false)
const selectionStart = ref<{ x: number; y: number } | null>(null)
const selectionEnd = ref<{ x: number; y: number } | null>(null)
const selectionStyle = ref<CSSProperties | null>(null)
const scrollDisabled = ref(false)

function preventScrolling(event: Event) {
  event.preventDefault()
  event.stopPropagation()
}

function disableScroll() {
  if (scrollDisabled.value) return
  document.body.style.overflow = 'hidden'
  document.documentElement.style.overflow = 'hidden'
  document.addEventListener('wheel', preventScrolling, { passive: false })
  document.addEventListener('touchmove', preventScrolling, { passive: false })
  scrollDisabled.value = true
}

function enableScroll() {
  if (!scrollDisabled.value) return
  document.body.style.overflow = ''
  document.documentElement.style.overflow = ''
  document.removeEventListener('wheel', preventScrolling)
  document.removeEventListener('touchmove', preventScrolling)
  scrollDisabled.value = false
}

function getCanvas() {
  const canvasRef = props.canvasRef
  if (isRef(canvasRef)) return canvasRef.value
  if (canvasRef && 'current' in canvasRef) return canvasRef.current
  return canvasRef
}

function getCanvasCoordinates(clientX: number, clientY: number) {
  const canvas = getCanvas()
  if (!canvas) return null
  const rect = canvas.getBoundingClientRect()
  const scaleX = canvas.width / rect.width
  const scaleY = canvas.height / rect.height
  const x = (clientX - rect.left) * scaleX
  const y = (clientY - rect.top) * scaleY
  return {
    x: Math.max(0, Math.min(canvas.width, x)),
    y: Math.max(0, Math.min(canvas.height, y)),
  }
}

function pixelToGrid(x: number, y: number) {
  const canvas = getCanvas()
  const dimensions = props.gridDimensions
  if (!dimensions || !canvas) return null
  const cellWidth = canvas.width / dimensions.N
  const cellHeight = canvas.height / dimensions.M
  const col = Math.floor(x / cellWidth)
  const row = Math.floor(y / cellHeight)
  return {
    row: Math.max(0, Math.min(dimensions.M - 1, row)),
    col: Math.max(0, Math.min(dimensions.N - 1, col)),
  }
}

function getSelectionStyle(start: { x: number; y: number }, end: { x: number; y: number }): CSSProperties | null {
  const canvas = getCanvas()
  if (!canvas) return null
  const rect = canvas.getBoundingClientRect()
  const scaleX = rect.width / canvas.width
  const scaleY = rect.height / canvas.height
  const minX = Math.min(start.x, end.x) * scaleX
  const minY = Math.min(start.y, end.y) * scaleY
  return {
    left: `${rect.left + minX}px`,
    top: `${rect.top + minY}px`,
    width: `${Math.abs(start.x - end.x) * scaleX}px`,
    height: `${Math.abs(start.y - end.y) * scaleY}px`,
    position: 'fixed',
    border: '2px solid #10b981',
    backgroundColor: 'rgba(16, 185, 129, 0.1)',
    pointerEvents: 'none',
    zIndex: 1000,
  }
}

function beginSelection(coords: { x: number; y: number }) {
  isSelecting.value = true
  selectionStart.value = coords
  selectionEnd.value = coords
  selectionStyle.value = getSelectionStyle(coords, coords)
  disableScroll()
}

function handleMouseDown(event: MouseEvent) {
  const coords = getCanvasCoordinates(event.clientX, event.clientY)
  if (!coords) return
  beginSelection(coords)
  event.preventDefault()
}

function handleMouseMove(event: MouseEvent) {
  if (!isSelecting.value || !selectionStart.value) return
  const coords = getCanvasCoordinates(event.clientX, event.clientY)
  if (!coords) return
  selectionEnd.value = coords
  selectionStyle.value = getSelectionStyle(selectionStart.value, coords)
}

function handleMouseUp() {
  if (!isSelecting.value || !selectionStart.value || !selectionEnd.value) {
    enableScroll()
    return
  }
  const startGrid = pixelToGrid(selectionStart.value.x, selectionStart.value.y)
  const endGrid = pixelToGrid(selectionEnd.value.x, selectionEnd.value.y)
  if (startGrid && endGrid) {
    const area: SelectionArea = {
      startRow: Math.min(startGrid.row, endGrid.row),
      startCol: Math.min(startGrid.col, endGrid.col),
      endRow: Math.max(startGrid.row, endGrid.row),
      endCol: Math.max(startGrid.col, endGrid.col),
    }
    props.onSelectionComplete(area)
  }
  isSelecting.value = false
  selectionStart.value = null
  selectionEnd.value = null
  selectionStyle.value = null
  enableScroll()
}

function handleTouchStart(event: TouchEvent) {
  event.preventDefault()
  event.stopPropagation()
  const touch = event.touches[0]
  if (!touch) return
  const coords = getCanvasCoordinates(touch.clientX, touch.clientY)
  if (!coords) return
  beginSelection(coords)
}

function handleTouchMove(event: TouchEvent) {
  if (!isSelecting.value || !selectionStart.value) return
  event.preventDefault()
  event.stopPropagation()
  const touch = event.touches[0]
  if (!touch) return
  const coords = getCanvasCoordinates(touch.clientX, touch.clientY)
  if (!coords) return
  selectionEnd.value = coords
  selectionStyle.value = getSelectionStyle(selectionStart.value, coords)
}

watch(isSelecting, (selecting, _, onCleanup) => {
  if (!selecting) return
  document.addEventListener('mousemove', handleMouseMove)
  document.addEventListener('mouseup', handleMouseUp)
  document.addEventListener('touchmove', handleTouchMove, { passive: false })
  document.addEventListener('touchend', handleMouseUp)
  onCleanup(() => {
    document.removeEventListener('mousemove', handleMouseMove)
    document.removeEventListener('mouseup', handleMouseUp)
    document.removeEventListener('touchmove', handleTouchMove)
    document.removeEventListener('touchend', handleMouseUp)
    enableScroll()
  })
}, { flush: 'sync' })

watch(() => props.isActive, (active) => {
  if (!active) {
    isSelecting.value = false
    selectionStart.value = null
    selectionEnd.value = null
    selectionStyle.value = null
    enableScroll()
  }
})
onUnmounted(enableScroll)
</script>

<template>
  <template v-if="isActive">
    <div
      class="fixed inset-0 z-50"
      :style="{ cursor: 'crosshair', pointerEvents: 'auto' }"
      @mousedown="handleMouseDown"
      @touchstart="handleTouchStart"
      @wheel.prevent
      @touchmove.prevent
      @scroll.prevent
    />
    <div v-if="isSelecting && selectionStyle" :style="selectionStyle" />
  </template>
</template>
