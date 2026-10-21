<script setup lang="ts">
import { onMounted, onUnmounted, ref, watch } from 'vue'
import type { MappedPixel } from '../utils/pixelation'
import { getColorKeyByHex, type ColorSystem } from '../utils/colorSystemUtils'

interface SelectionArea {
  startRow: number
  startCol: number
  endRow: number
  endCol: number
}

const props = defineProps<{
  isActive: boolean
  onToggle: () => void
  mappedPixelData: MappedPixel[][] | null
  gridDimensions: { N: number; M: number } | null
  selectedColor: MappedPixel | null
  selectedColorSystem: ColorSystem
  onPixelEdit: (row: number, col: number, colorData: { key: string; color: string }) => void
  cellSize: number
  selectionArea: SelectionArea | null
  onClearSelection: () => void
  isFloatingActive: boolean
  onActivateFloating: () => void
  highlightColorKey?: string | null
}>()

const magnifierPosition = ref({
  x: Math.max(50, (window.innerWidth - 400) / 2),
  y: Math.max(50, (window.innerHeight - 400) / 2),
})
const isDragging = ref(false)
const dragOffset = ref({ x: 0, y: 0 })
const magnifierRef = ref<HTMLDivElement | null>(null)
const canvasRef = ref<HTMLCanvasElement | null>(null)

function getSelectionDimensions() {
  const area = props.selectionArea
  if (!area) return { width: 0, height: 0 }
  return {
    width: Math.abs(area.endCol - area.startCol) + 1,
    height: Math.abs(area.endRow - area.startRow) + 1,
  }
}

function renderMagnifiedView() {
  const area = props.selectionArea
  const data = props.mappedPixelData
  const canvas = canvasRef.value
  if (!props.isActive || !area || !data || !canvas) return

  const ctx = canvas.getContext('2d')
  if (!ctx) return

  const { width, height } = getSelectionDimensions()
  const magnifiedCellSize = 20
  canvas.width = width * magnifiedCellSize
  canvas.height = height * magnifiedCellSize
  canvas.style.width = `${canvas.width}px`
  canvas.style.height = `${canvas.height}px`
  ctx.clearRect(0, 0, canvas.width, canvas.height)

  const startRow = Math.min(area.startRow, area.endRow)
  const endRow = Math.max(area.startRow, area.endRow)
  const startCol = Math.min(area.startCol, area.endCol)
  const endCol = Math.max(area.startCol, area.endCol)
  for (let row = startRow; row <= endRow; row++) {
    for (let col = startCol; col <= endCol; col++) {
      if (row >= 0 && row < data.length && col >= 0 && col < data[0].length) {
        const pixel = data[row][col]
        const canvasRow = row - startRow
        const canvasCol = col - startCol
        ctx.fillStyle = pixel.color
        ctx.fillRect(canvasCol * magnifiedCellSize, canvasRow * magnifiedCellSize, magnifiedCellSize, magnifiedCellSize)
        if (props.highlightColorKey && pixel.color.toUpperCase() !== props.highlightColorKey.toUpperCase()) {
          ctx.fillStyle = 'rgba(0, 0, 0, 0.6)'
          ctx.fillRect(canvasCol * magnifiedCellSize, canvasRow * magnifiedCellSize, magnifiedCellSize, magnifiedCellSize)
        }
        ctx.strokeStyle = '#e0e0e0'
        ctx.lineWidth = 1
        ctx.strokeRect(canvasCol * magnifiedCellSize, canvasRow * magnifiedCellSize, magnifiedCellSize, magnifiedCellSize)
      }
    }
  }
}

function handleMagnifiedClick(event: MouseEvent) {
  const area = props.selectionArea
  const data = props.mappedPixelData
  const canvas = canvasRef.value
  if (!area || !data || !props.selectedColor || !canvas) return

  const rect = canvas.getBoundingClientRect()
  const scaleX = canvas.width / rect.width
  const scaleY = canvas.height / rect.height
  const x = (event.clientX - rect.left) * scaleX
  const y = (event.clientY - rect.top) * scaleY
  const clickedCol = Math.floor(x / 20)
  const clickedRow = Math.floor(y / 20)
  const actualRow = Math.min(area.startRow, area.endRow) + clickedRow
  const actualCol = Math.min(area.startCol, area.endCol) + clickedCol
  if (actualRow >= 0 && actualRow < data.length && actualCol >= 0 && actualCol < data[0].length) {
    props.onPixelEdit(actualRow, actualCol, props.selectedColor)
  }
}

function handleTitleBarMouseDown(event: MouseEvent) {
  const target = event.target as HTMLElement
  if (target.tagName === 'BUTTON' || target.closest('button')) return
  if (magnifierRef.value) {
    const rect = magnifierRef.value.getBoundingClientRect()
    dragOffset.value = { x: event.clientX - rect.left, y: event.clientY - rect.top }
  }
  props.onActivateFloating()
  isDragging.value = true
  document.body.style.overflow = 'hidden'
  event.preventDefault()
}

function handleTitleBarTouchStart(event: TouchEvent) {
  const target = event.target as HTMLElement
  if (target.tagName === 'BUTTON' || target.closest('button')) return
  const touch = event.touches[0]
  if (!touch) return
  if (magnifierRef.value) {
    const rect = magnifierRef.value.getBoundingClientRect()
    dragOffset.value = { x: touch.clientX - rect.left, y: touch.clientY - rect.top }
  }
  props.onActivateFloating()
  isDragging.value = true
  document.body.style.overflow = 'hidden'
  event.preventDefault()
}

function handleMouseMove(event: MouseEvent) {
  if (!isDragging.value) return
  event.preventDefault()
  event.stopPropagation()
  magnifierPosition.value = { x: event.clientX - dragOffset.value.x, y: event.clientY - dragOffset.value.y }
}

function handleTouchMove(event: TouchEvent) {
  if (!isDragging.value) return
  event.preventDefault()
  event.stopPropagation()
  const touch = event.touches[0]
  if (!touch) return
  magnifierPosition.value = { x: touch.clientX - dragOffset.value.x, y: touch.clientY - dragOffset.value.y }
}

function stopDragging() {
  isDragging.value = false
  document.body.style.overflow = ''
}

watch(isDragging, (dragging, _, onCleanup) => {
  if (!dragging) return
  document.addEventListener('mousemove', handleMouseMove)
  document.addEventListener('mouseup', stopDragging)
  document.addEventListener('touchmove', handleTouchMove, { passive: false })
  document.addEventListener('touchend', stopDragging)
  onCleanup(() => {
    document.removeEventListener('mousemove', handleMouseMove)
    document.removeEventListener('mouseup', stopDragging)
    document.removeEventListener('touchmove', handleTouchMove)
    document.removeEventListener('touchend', stopDragging)
    document.body.style.overflow = ''
  })
}, { flush: 'sync' })

watch(() => props.isActive, (active) => {
  if (!active && isDragging.value) stopDragging()
  if (active) {
    magnifierPosition.value = {
      x: Math.max(50, (window.innerWidth - 400) / 2),
      y: Math.max(50, (window.innerHeight - 400) / 2),
    }
  }
})
watch(() => [props.isActive, props.selectionArea, props.mappedPixelData, props.highlightColorKey], renderMagnifiedView, { flush: 'post' })
onMounted(renderMagnifiedView)
onUnmounted(() => {
  if (isDragging.value) stopDragging()
})
</script>

<template>
  <template v-if="isActive">
    <div v-if="!selectionArea" class="fixed top-4 left-1/2 transform -translate-x-1/2 bg-primary text-primary-content px-4 py-2 rounded-lg shadow-lg z-70">
      <div class="flex items-center gap-2">
        <svg xmlns="http://www.w3.org/2000/svg" class="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path stroke-linecap="round" stroke-linejoin="round" :stroke-width="2" d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
        </svg>
        <span>在画布上拖拽选择要放大的区域</span>
      </div>
    </div>

    <div
      v-else
      ref="magnifierRef"
      class="fixed bg-base-100 rounded-xl shadow-2xl border border-base-300 select-none"
      :class="isFloatingActive ? 'z-60' : 'z-50'"
      :style="{ left: `${magnifierPosition.x}px`, top: `${magnifierPosition.y}px` }"
      @click="onActivateFloating"
    >
      <div
        class="flex items-center justify-between p-3 bg-linear-to-br from-success to-primary text-success-content rounded-t-xl cursor-move"
        @mousedown="handleTitleBarMouseDown"
        @touchstart="handleTitleBarTouchStart"
      >
        <div class="flex items-center gap-2">
          <svg xmlns="http://www.w3.org/2000/svg" class="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path stroke-linecap="round" stroke-linejoin="round" :stroke-width="2" d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
          </svg>
          <span class="text-sm font-medium">放大镜 ({{ getSelectionDimensions().width }}×{{ getSelectionDimensions().height }})</span>
        </div>
        <div class="flex items-center gap-2">
          <button @click="onClearSelection" class="p-1 hover:bg-white/20 rounded transition-colors" title="重新选择区域">
            <svg xmlns="http://www.w3.org/2000/svg" class="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path stroke-linecap="round" stroke-linejoin="round" :stroke-width="2" d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
            </svg>
          </button>
          <button @click="onToggle" class="p-1 hover:bg-white/20 rounded transition-colors" title="关闭放大镜">
            <svg xmlns="http://www.w3.org/2000/svg" class="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path stroke-linecap="round" stroke-linejoin="round" :stroke-width="2" d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </div>
      </div>
      <div class="p-3">
        <div class="border border-base-300 rounded-lg overflow-auto max-h-96">
          <canvas ref="canvasRef" @click="handleMagnifiedClick" class="cursor-crosshair block" />
        </div>
        <div v-if="selectedColor" class="mt-2 p-2 bg-base-200 rounded-lg">
          <div class="flex items-center gap-2 text-xs">
            <div class="w-4 h-4 rounded border border-base-300" :style="{ backgroundColor: selectedColor.color }" />
            <span class="text-base-content">当前: {{ getColorKeyByHex(selectedColor.color, selectedColorSystem) }}</span>
          </div>
        </div>
      </div>
    </div>
  </template>
</template>
