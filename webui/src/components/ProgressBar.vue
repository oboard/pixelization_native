<script setup lang="ts">
defineProps<{
  progressPercentage: number
  recommendedCell?: { row: number; col: number } | null
  colorInfo?: { color: string; name: string; total: number; completed: number }
}>()
</script>

<template>
  <div class="h-10 bg-base-100 border-b border-base-300 px-4 py-2 flex items-center justify-between">
    <div class="flex items-center space-x-2">
      <div
        v-for="index in 7"
        :key="index"
        class="w-3 h-3 rounded-full"
        :class="progressPercentage >= index * (100 / 7) ? 'bg-primary' : 'bg-base-300'"
      />
      <span class="ml-2 text-sm font-medium text-base-content">{{ progressPercentage }}%</span>
    </div>
    <div class="text-xs text-base-content/70">
      <span v-if="recommendedCell">下一块 → {{ recommendedCell.row + 1 }},{{ recommendedCell.col + 1 }}</span>
      <span v-else>已完成当前颜色</span>
    </div>
  </div>
</template>
