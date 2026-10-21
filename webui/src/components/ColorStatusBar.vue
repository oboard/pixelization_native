<script setup lang="ts">
import { computed } from 'vue'

const props = defineProps<{
  currentColor: string
  colorInfo?: { color: string; name: string; total: number; completed: number }
  progressPercentage: number
}>()

const estimatedTime = computed(() => Math.ceil(((props.colorInfo?.total ?? 0) - (props.colorInfo?.completed ?? 0)) * 0.1))
</script>

<template>
  <div v-if="!colorInfo" class="h-12 bg-base-100 border-b border-base-300 px-4 py-2 flex items-center">
    <div class="text-base-content/70">请选择颜色</div>
  </div>
  <div v-else class="h-12 bg-base-100 border-b border-base-300 px-4 py-2 flex items-center justify-between">
    <div class="flex items-center space-x-3">
      <div class="w-8 h-8 rounded-full border-2 border-base-300" :style="{ backgroundColor: currentColor }" />
      <div class="text-sm font-mono font-bold text-base-content px-2">{{ colorInfo.name }}</div>
      <div class="flex flex-col">
        <div class="text-sm font-medium text-base-content">{{ colorInfo.completed }}/{{ colorInfo.total }}</div>
        <div class="text-xs text-base-content/70">预计还需 {{ estimatedTime }}分钟</div>
      </div>
    </div>
    <div class="text-right"><div class="text-lg font-bold text-primary">{{ progressPercentage }}%</div></div>
  </div>
</template>
