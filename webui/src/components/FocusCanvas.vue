<script setup lang="ts">
import { computed, ref, watchEffect } from 'vue'
import type { MappedPixel } from '../utils/pixelation'

const props = defineProps<{
  mappedPixelData: MappedPixel[][]
  gridDimensions: { N: number; M: number }
  currentColor: string
  completedCells: Set<string>
  recommendedCell: { row: number; col: number } | null
  recommendedRegion: { row: number; col: number }[] | null
  canvasScale: number
  canvasOffset: { x: number; y: number }
  gridSectionInterval: number
  showSectionLines: boolean
  sectionLineColor: string
  onCellClick?: (row: number, col: number) => void
  onScaleChange?: (scale: number) => void
  onOffsetChange?: (offset: { x: number; y: number }) => void
}>()

// 可用原回调 prop，或监听 cell-clicked(row, col)、scale-changed(scale)、offset-changed(offset)。勿同时接入同一操作。
const emit = defineEmits<{
  'cell-clicked': [row: number, col: number]
  'scale-changed': [scale: number]
  'offset-changed': [offset: { x: number; y: number }]
}>()
const canvasRef = ref<HTMLCanvasElement | null>(null)
const cellSize = computed(() => Math.max(15, Math.min(40, 300 / Math.max(props.gridDimensions.N, props.gridDimensions.M))))
const isDragging = ref(false)
let lastPanPoint: { x: number; y: number } | null = null
let lastPinchDistance: number | null = null
let touchStart: { x: number; y: number } | null = null
let touchMoved = false

function renderCanvas() {
  const canvas = canvasRef.value
  if (!canvas || !props.mappedPixelData) return
  const ctx = canvas.getContext('2d')
  if (!ctx) return
  const size = cellSize.value
  const { N, M } = props.gridDimensions
  const canvasWidth = N * size
  const canvasHeight = M * size
  canvas.width = canvasWidth
  canvas.height = canvasHeight
  canvas.style.width = `${canvasWidth}px`
  canvas.style.height = `${canvasHeight}px`
  ctx.clearRect(0, 0, canvasWidth, canvasHeight)

  for (let row = 0; row < M; row++) {
    for (let col = 0; col < N; col++) {
      const pixel = props.mappedPixelData[row][col]
      const x = col * size
      const y = row * size
      let fillColor = pixel.color
      if (pixel.color !== props.currentColor) {
        const hex = pixel.color.replace('#', '')
        const r = parseInt(hex.substring(0, 2), 16)
        const g = parseInt(hex.substring(2, 4), 16)
        const b = parseInt(hex.substring(4, 6), 16)
        const gray = Math.round(0.299 * r + 0.587 * g + 0.114 * b)
        fillColor = `rgb(${gray}, ${gray}, ${gray})`
      }
      ctx.fillStyle = fillColor
      ctx.fillRect(x, y, size, size)
      if (props.completedCells.has(`${row},${col}`) && pixel.color === props.currentColor) {
        ctx.fillStyle = 'rgba(0, 255, 0, 0.6)'
        ctx.fillRect(x, y, size, size)
        ctx.strokeStyle = '#fff'
        ctx.lineWidth = 2
        ctx.beginPath()
        ctx.moveTo(x + size * 0.2, y + size * 0.5)
        ctx.lineTo(x + size * 0.4, y + size * 0.7)
        ctx.lineTo(x + size * 0.8, y + size * 0.3)
        ctx.stroke()
      }
      const inRegion = props.recommendedRegion?.some(cell => cell.row === row && cell.col === col)
      if (inRegion) {
        ctx.strokeStyle = '#ff4444'
        ctx.lineWidth = 3
        ctx.setLineDash([5, 5])
        ctx.strokeRect(x + 1, y + 1, size - 2, size - 2)
        ctx.setLineDash([])
      }
      if (inRegion && props.recommendedCell?.row === row && props.recommendedCell.col === col) {
        ctx.fillStyle = '#ff4444'
        ctx.beginPath()
        ctx.arc(x + size / 2, y + size / 2, 4, 0, 2 * Math.PI)
        ctx.fill()
      }
    }
  }
  if (props.showSectionLines) {
    ctx.strokeStyle = props.sectionLineColor
    ctx.lineWidth = 2
    for (let col = props.gridSectionInterval; col < N; col += props.gridSectionInterval) {
      const x = col * size
      ctx.beginPath(); ctx.moveTo(x, 0); ctx.lineTo(x, canvasHeight); ctx.stroke()
    }
    for (let row = props.gridSectionInterval; row < M; row += props.gridSectionInterval) {
      const y = row * size
      ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(canvasWidth, y); ctx.stroke()
    }
  }
}
// flush:post 保证首次绘制与任何模板更新都在 canvas DOM 已挂载后执行。
watchEffect(renderCanvas, { flush: 'post' })

function clickAt(clientX: number, clientY: number) {
  const rect = canvasRef.value?.getBoundingClientRect()
  if (!rect) return
  const col = Math.floor((clientX - rect.left) / props.canvasScale / cellSize.value)
  const row = Math.floor((clientY - rect.top) / props.canvasScale / cellSize.value)
  if (row >= 0 && row < props.gridDimensions.M && col >= 0 && col < props.gridDimensions.N) {
    props.onCellClick?.(row, col)
    emit('cell-clicked', row, col)
  }
}
function handleClick(event: MouseEvent) {
  event.preventDefault()
  clickAt(event.clientX, event.clientY)
}
function changeScale(scale: number) {
  props.onScaleChange?.(scale)
  emit('scale-changed', scale)
}
function changeOffset(offset: { x: number; y: number }) {
  props.onOffsetChange?.(offset)
  emit('offset-changed', offset)
}
function handleWheel(event: WheelEvent) {
  event.preventDefault()
  changeScale(Math.max(0.3, Math.min(3, props.canvasScale * (event.deltaY > 0 ? 0.9 : 1.1))))
}
function touchDistance(touches: TouchList) {
  const dx = touches[0].clientX - touches[1].clientX
  const dy = touches[0].clientY - touches[1].clientY
  return Math.sqrt(dx * dx + dy * dy)
}
function handleTouchStart(event: TouchEvent) {
  if (event.touches.length === 1) {
    isDragging.value = true
    lastPanPoint = { x: event.touches[0].clientX, y: event.touches[0].clientY }
    touchStart = { ...lastPanPoint }
    touchMoved = false
    lastPinchDistance = null
  } else if (event.touches.length === 2) {
    event.preventDefault()
    isDragging.value = false
    lastPanPoint = null
    touchMoved = true
    lastPinchDistance = touchDistance(event.touches)
  }
}
function handleTouchMove(event: TouchEvent) {
  event.preventDefault()
  if (event.touches.length === 1 && isDragging.value && lastPanPoint) {
    const point = { x: event.touches[0].clientX, y: event.touches[0].clientY }
    if (touchStart && Math.hypot(point.x - touchStart.x, point.y - touchStart.y) > 5) touchMoved = true
    const deltaX = point.x - lastPanPoint.x
    const deltaY = point.y - lastPanPoint.y
    if (deltaX || deltaY) changeOffset({ x: props.canvasOffset.x + deltaX, y: props.canvasOffset.y + deltaY })
    lastPanPoint = point
  } else if (event.touches.length === 2 && lastPinchDistance !== null) {
    const distance = touchDistance(event.touches)
    changeScale(Math.max(0.3, Math.min(3, props.canvasScale * distance / lastPinchDistance)))
    lastPinchDistance = distance
  }
}
function handleTouchEnd(event: TouchEvent) {
  if (event.touches.length === 0) {
    if (!touchMoved && touchStart) {
      event.preventDefault()
      clickAt(touchStart.x, touchStart.y)
    }
    isDragging.value = false
    lastPanPoint = null
    lastPinchDistance = null
    touchStart = null
  } else if (event.touches.length === 1) {
    lastPinchDistance = null
    isDragging.value = true
    lastPanPoint = { x: event.touches[0].clientX, y: event.touches[0].clientY }
  }
}
function handleMouseDown(event: MouseEvent) {
  isDragging.value = true
  lastPanPoint = { x: event.clientX, y: event.clientY }
}
function handleMouseMove(event: MouseEvent) {
  if (!isDragging.value || !lastPanPoint) return
  const deltaX = event.clientX - lastPanPoint.x
  const deltaY = event.clientY - lastPanPoint.y
  changeOffset({ x: props.canvasOffset.x + deltaX, y: props.canvasOffset.y + deltaY })
  lastPanPoint = { x: event.clientX, y: event.clientY }
}
function handleMouseUp() { isDragging.value = false; lastPanPoint = null }
</script>

<template>
  <div class="w-full h-full flex items-center justify-center overflow-hidden bg-gray-100" style="touch-action: none">
    <div :style="{ transform: `scale(${canvasScale}) translate(${canvasOffset.x}px, ${canvasOffset.y}px)`, transformOrigin: 'center center' }">
      <canvas ref="canvasRef" class="cursor-crosshair border border-gray-300"
        @click="handleClick" @wheel="handleWheel" @touchstart="handleTouchStart"
        @touchmove="handleTouchMove" @touchend="handleTouchEnd"
        @mousedown="handleMouseDown" @mousemove="handleMouseMove"
        @mouseup="handleMouseUp" @mouseleave="handleMouseUp" />
    </div>
  </div>
</template>
