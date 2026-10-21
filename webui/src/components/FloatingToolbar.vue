<script setup lang="ts">
defineProps<{
  isManualColoringMode: boolean
  isPaletteOpen: boolean
  onTogglePalette: () => void
  onExitManualMode: () => void
  onToggleMagnifier: () => void
  isMagnifierActive: boolean
}>()
</script>

<template>
  <div v-if="isManualColoringMode" class="fixed top-4 right-4 z-[100] flex flex-col gap-2">
    <button
      :class="['w-12 h-12 rounded-full shadow-lg transition-all duration-200 flex items-center justify-center', isPaletteOpen ? 'bg-primary text-primary-content hover:bg-primary' : 'bg-base-100  text-base-content  hover:bg-base-200  border border-base-300 ']"
      :title="isPaletteOpen ? '关闭调色盘' : '打开调色盘'"
      @click="onTogglePalette"
    >
      <svg xmlns="http://www.w3.org/2000/svg" class="h-6 w-6" viewBox="0 0 20 20" fill="currentColor"><path fill-rule="evenodd" d="M4 2a2 2 0 00-2 2v11a3 3 0 106 0V4a2 2 0 00-2-2H4zm1 14a1 1 0 100-2 1 1 0 000 2zm5-1.757l4.9-4.9a2 2 0 000-2.828L13.485 5.1a2 2 0 00-2.828 0L10 5.757v8.486zM16 18H9.071l6-6H16a2 2 0 012 2v2a2 2 0 01-2 2z" clip-rule="evenodd" /></svg>
    </button>
    <button
      :class="['w-12 h-12 rounded-full shadow-lg transition-all duration-200 flex items-center justify-center', isMagnifierActive ? 'bg-success text-success-content hover:bg-success' : 'bg-base-100  text-base-content  hover:bg-base-200  border border-base-300 ']"
      :title="isMagnifierActive ? '关闭放大镜' : '打开放大镜'"
      @click="onToggleMagnifier"
    >
      <svg xmlns="http://www.w3.org/2000/svg" class="h-6 w-6" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" :stroke-width="2" d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" /></svg>
    </button>
    <button class="w-12 h-12 rounded-full bg-error text-error-content shadow-lg hover:bg-error transition-all duration-200 flex items-center justify-center" title="退出手动编辑模式" @click="onExitManualMode">
      <svg xmlns="http://www.w3.org/2000/svg" class="h-6 w-6" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" :stroke-width="2" d="M6 18L18 6M6 6l12 12" /></svg>
    </button>
  </div>
</template>
