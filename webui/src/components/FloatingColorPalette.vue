<script setup lang="ts">
import { computed, ref, watch, onBeforeUnmount } from 'vue'
import type { MappedPixel } from '../utils/pixelation'
import { TRANSPARENT_KEY } from '../utils/pixelEditingUtils'
import { getColorKeyByHex } from '../utils/colorSystemUtils'
import type { ColorSystem } from '../utils/colorSystemUtils'

interface ColorReplaceState {
  isActive: boolean
  step: 'select-source' | 'select-target'
  sourceColor?: { key: string; color: string }
}

interface PaletteColor {
  key: string
  color: string
}

const props = defineProps<{
  colors: PaletteColor[]
  selectedColor: MappedPixel | null
  onColorSelect: (colorData: PaletteColor & { isExternal?: boolean }) => void
  selectedColorSystem: ColorSystem
  isEraseMode: boolean
  onEraseToggle: () => void
  fullPaletteColors: PaletteColor[]
  showFullPalette: boolean
  onToggleFullPalette: () => void
  colorReplaceState: ColorReplaceState
  onColorReplaceToggle: () => void
  onColorReplace: (sourceColor: PaletteColor, targetColor: PaletteColor) => void
  onHighlightColor: (colorHex: string) => void
  isOpen: boolean
  onToggleOpen: () => void
  isActive: boolean
  onActivate: () => void
}>()

function getInitialPosition() {
  if (typeof window === 'undefined') return { x: 20, y: 100 }
  return {
    x: Math.max(0, Math.min(20, window.innerWidth - 280)),
    y: Math.max(0, Math.min(100, window.innerHeight - 400)),
  }
}

const position = ref(getInitialPosition())
const isDragging = ref(false)
const dragOffset = ref({ x: 0, y: 0 })
const paletteRef = ref<HTMLDivElement | null>(null)
const displayColors = computed(() => props.showFullPalette ? props.fullPaletteColors : props.colors)

function handleMouseDown(e: MouseEvent) {
  if (!paletteRef.value) return
  props.onActivate()
  const rect = paletteRef.value.getBoundingClientRect()
  isDragging.value = true
  dragOffset.value = { x: e.clientX - rect.left, y: e.clientY - rect.top }
  e.preventDefault()
}

function handleTouchStart(e: TouchEvent) {
  if (!paletteRef.value) return
  props.onActivate()
  const rect = paletteRef.value.getBoundingClientRect()
  const touch = e.touches[0]
  isDragging.value = true
  dragOffset.value = { x: touch.clientX - rect.left, y: touch.clientY - rect.top }
  e.preventDefault()
}

function handleMove(clientX: number, clientY: number) {
  if (!isDragging.value) return
  position.value = { x: clientX - dragOffset.value.x, y: clientY - dragOffset.value.y }
}

function handleMouseMove(e: MouseEvent) {
  e.preventDefault()
  e.stopPropagation()
  handleMove(e.clientX, e.clientY)
}

function handleTouchMove(e: TouchEvent) {
  e.preventDefault()
  e.stopPropagation()
  if (e.touches.length > 0) handleMove(e.touches[0].clientX, e.touches[0].clientY)
}

function handleEnd() {
  isDragging.value = false
  document.body.style.overflow = ''
}

watch(isDragging, (dragging, _, onCleanup) => {
  if (!dragging) return
  document.body.style.overflow = 'hidden'
  document.addEventListener('mousemove', handleMouseMove)
  document.addEventListener('mouseup', handleEnd)
  document.addEventListener('touchmove', handleTouchMove, { passive: false })
  document.addEventListener('touchend', handleEnd)
  onCleanup(() => {
    document.removeEventListener('mousemove', handleMouseMove)
    document.removeEventListener('mouseup', handleEnd)
    document.removeEventListener('touchmove', handleTouchMove)
    document.removeEventListener('touchend', handleEnd)
    document.body.style.overflow = ''
  })
})

watch(() => props.isOpen, (open, wasOpen) => {
  if (!open) isDragging.value = false
  if (open && !wasOpen) position.value = getInitialPosition()
})

onBeforeUnmount(() => { isDragging.value = false; document.body.style.overflow = '' })

function handleColorClick(colorData: PaletteColor) {
  if (props.colorReplaceState.isActive &&
      props.colorReplaceState.step === 'select-target' &&
      props.colorReplaceState.sourceColor) {
    props.onColorReplace(props.colorReplaceState.sourceColor, colorData)
  } else {
    props.onHighlightColor(colorData.color)
    props.onColorSelect(colorData)
  }
}
</script>

<template>
  <div
    v-if="isOpen"
    ref="paletteRef"
    class="fixed bg-white dark:bg-gray-800 rounded-xl shadow-2xl border border-gray-200 dark:border-gray-600 select-none"
    :class="isActive ? 'z-60' : 'z-50'"
    :style="{ left: `${position.x}px`, top: `${position.y}px`, width: '280px', maxHeight: '400px' }"
    @click="onActivate"
  >
    <!-- 标题栏和控制按钮 -->
    <div
      class="flex items-center justify-between p-3 bg-linear-to-br from-blue-500 to-purple-500 text-white rounded-t-xl cursor-move"
      @mousedown="handleMouseDown"
      @touchstart="handleTouchStart"
    >
      <div class="flex items-center gap-2">
        <svg xmlns="http://www.w3.org/2000/svg" class="h-4 w-4" viewBox="0 0 20 20" fill="currentColor">
          <path fill-rule="evenodd" d="M4 2a2 2 0 00-2 2v11a3 3 0 106 0V4a2 2 0 00-2-2H4zm1 14a1 1 0 100-2 1 1 0 000 2zm5-1.757l4.9-4.9a2 2 0 000-2.828L13.485 5.1a2 2 0 00-2.828 0L10 5.757v8.486zM16 18H9.071l6-6H16a2 2 0 012 2v2a2 2 0 01-2 2z" clip-rule="evenodd" />
        </svg>
        <span class="text-sm font-medium">调色盘</span>
      </div>
      <div class="flex items-center gap-1">
        <button @click="onToggleOpen" class="p-1 hover:bg-white/20 rounded transition-colors" title="关闭调色盘">
          <svg xmlns="http://www.w3.org/2000/svg" class="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path stroke-linecap="round" stroke-linejoin="round" :stroke-width="2" d="M6 18L18 6M6 6l12 12" />
          </svg>
        </button>
      </div>
    </div>

    <!-- 内容区域 -->
    <div class="p-3 max-h-80 overflow-y-auto">
      <div v-if="colorReplaceState.isActive" class="mb-3 p-2 bg-orange-100 dark:bg-orange-900/30 border border-orange-200 dark:border-orange-800 rounded-lg text-xs">
        <div class="flex items-center gap-1 text-orange-700 dark:text-orange-300">
          <svg xmlns="http://www.w3.org/2000/svg" class="h-3.5 w-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path stroke-linecap="round" stroke-linejoin="round" :stroke-width="2" d="M7 16V4m0 0L3 8m4-4l4 4m6 0v12m0 0l4-4m-4 4l-4-4" />
          </svg>
          <span>{{ colorReplaceState.step === 'select-source' ? '点击画布选择要替换的颜色' : '选择目标颜色' }}</span>
        </div>
      </div>

      <div class="flex gap-2 mb-3">
        <button
          @click="handleColorClick({ key: TRANSPARENT_KEY, color: '#FFFFFF' })"
          class="flex-1 p-2 rounded-lg border transition-all duration-200 flex items-center justify-center gap-1 text-xs"
          :class="selectedColor?.key === TRANSPARENT_KEY ? 'bg-red-500 text-white border-red-500' : 'bg-gray-100 dark:bg-gray-700 text-gray-700 dark:text-gray-300 border-gray-300 dark:border-gray-600 hover:bg-red-50 dark:hover:bg-red-900/20'"
        >
          <svg xmlns="http://www.w3.org/2000/svg" class="h-3.5 w-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path stroke-linecap="round" stroke-linejoin="round" :stroke-width="2" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
          </svg>
          橡皮擦
        </button>
        <button
          @click="onEraseToggle"
          class="flex-1 p-2 rounded-lg border transition-all duration-200 flex items-center justify-center gap-1 text-xs"
          :class="isEraseMode ? 'bg-orange-500 text-white border-orange-500' : 'bg-gray-100 dark:bg-gray-700 text-gray-700 dark:text-gray-300 border-gray-300 dark:border-gray-600 hover:bg-orange-50 dark:hover:bg-orange-900/20'"
        >
          <svg xmlns="http://www.w3.org/2000/svg" class="h-3.5 w-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path stroke-linecap="round" stroke-linejoin="round" :stroke-width="2" d="M13 10V3L4 14h7v7l9-11h-7z" />
          </svg>
          区域擦除
        </button>
        <button
          @click="onColorReplaceToggle"
          class="flex-1 p-2 rounded-lg border transition-all duration-200 flex items-center justify-center gap-1 text-xs"
          :class="colorReplaceState.isActive ? 'bg-blue-500 text-white border-blue-500' : 'bg-gray-100 dark:bg-gray-700 text-gray-700 dark:text-gray-300 border-gray-300 dark:border-gray-600 hover:bg-blue-50 dark:hover:bg-blue-900/20'"
        >
          <svg xmlns="http://www.w3.org/2000/svg" class="h-3.5 w-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path stroke-linecap="round" stroke-linejoin="round" :stroke-width="2" d="M7 16V4m0 0L3 8m4-4l4 4m6 0v12m0 0l4-4m-4 4l-4-4" />
          </svg>
          批量替换
        </button>
      </div>

      <div class="flex gap-2 mb-3">
        <button @click="onToggleFullPalette" class="w-full text-xs py-2 px-3 bg-gray-100 dark:bg-gray-700 text-gray-700 dark:text-gray-300 rounded-lg hover:bg-gray-200 dark:hover:bg-gray-600 transition-colors">
          {{ showFullPalette ? `当前色板 (${colors.length})` : `完整色板 (${fullPaletteColors.length})` }}
        </button>
      </div>

      <div class="grid grid-cols-6 gap-1.5">
        <button
          v-for="colorData in displayColors"
          :key="`${colorData.key}-${colorData.color}`"
          @click="handleColorClick(colorData)"
          class="group relative aspect-square rounded-lg border-2 transition-all duration-200 hover:scale-110"
          :class="selectedColor?.key === colorData.key && selectedColor?.color === colorData.color ? 'border-blue-500 dark:border-blue-400 ring-2 ring-blue-200 dark:ring-blue-800 scale-110' : 'border-gray-300 dark:border-gray-600 hover:border-gray-400 dark:hover:border-gray-500'"
          :style="{ backgroundColor: colorData.color }"
          :title="`${getColorKeyByHex(colorData.color, selectedColorSystem)} (${colorData.color})`"
        >
          <div v-if="selectedColor?.key === colorData.key && selectedColor?.color === colorData.color" class="absolute inset-0 flex items-center justify-center">
            <div class="w-2 h-2 bg-white rounded-full shadow-lg"></div>
          </div>
          <div class="absolute -top-8 left-1/2 transform -translate-x-1/2 bg-gray-800 dark:bg-gray-700 text-white text-xs px-2 py-1 rounded opacity-0 group-hover:opacity-100 transition-opacity pointer-events-none whitespace-nowrap z-10">
            {{ getColorKeyByHex(colorData.color, selectedColorSystem) }}
          </div>
        </button>
      </div>

      <div v-if="selectedColor && selectedColor.key !== TRANSPARENT_KEY" class="mt-3 p-2 bg-gray-100 dark:bg-gray-700 rounded-lg">
        <div class="flex items-center gap-2 text-xs">
          <div class="w-4 h-4 rounded border border-gray-300 dark:border-gray-500" :style="{ backgroundColor: selectedColor.color }"></div>
          <span class="text-gray-700 dark:text-gray-300">当前: {{ getColorKeyByHex(selectedColor.color, selectedColorSystem) }}</span>
        </div>
      </div>
    </div>
  </div>
</template>
