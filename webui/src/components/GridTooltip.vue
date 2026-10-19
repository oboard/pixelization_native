<script setup lang="ts">
import { getDisplayColorKey, type ColorSystem } from '../utils/colorSystemUtils'

withDefaults(defineProps<{
  tooltipData: { x: number; y: number; key: string; color: string } | null
  selectedColorSystem?: ColorSystem
}>(), { selectedColorSystem: 'MARD' })
</script>

<template>
  <div
    v-if="tooltipData"
    class="absolute bg-gray-800 text-white text-xs px-2 py-1 rounded shadow-lg pointer-events-none flex items-center space-x-1.5 z-50"
    :style="{ left: `${tooltipData.x}px`, top: `${tooltipData.y - 25}px`, transform: 'translate(-50%, -100%)', whiteSpace: 'nowrap' }"
  >
    <span class="inline-block w-3 h-3 rounded-sm border border-gray-400 dark:border-gray-500 shrink-0" :style="{ backgroundColor: tooltipData.color }" />
    <span class="font-mono font-semibold">{{ getDisplayColorKey(tooltipData.color, selectedColorSystem) }}</span>
  </div>
</template>
