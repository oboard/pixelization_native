<script setup lang="ts">
import { computed, ref } from 'vue'

interface ColorInfo { color: string; name: string; total: number; completed: number }
const props = defineProps<{
  colors: ColorInfo[]
  currentColor: string
  onColorSelect?: (color: string) => void
  onClose?: () => void
}>()
// 可用原回调 prop，或监听 color-selected(color)、closed；同一操作不要同时接入两种方式。
const emit = defineEmits<{ 'color-selected': [color: string]; closed: [] }>()
const searchTerm = ref('')
const sortBy = ref<'progress' | 'name' | 'total'>('progress')
const filteredAndSortedColors = computed(() => props.colors
  .filter(color => color.name.toLowerCase().includes(searchTerm.value.toLowerCase()) || color.color.toLowerCase().includes(searchTerm.value.toLowerCase()))
  .sort((a, b) => {
    if (sortBy.value === 'progress') return a.completed / a.total * 100 - b.completed / b.total * 100
    if (sortBy.value === 'name') return a.name.localeCompare(b.name)
    return b.total - a.total
  }))
function progress(color: ColorInfo) { return Math.round(color.completed / color.total * 100) }
function selectColor(color: string) { props.onColorSelect?.(color); emit('color-selected', color) }
function close() { props.onClose?.(); emit('closed') }
</script>

<template>
  <div class="fixed inset-0 bg-black/50 z-50 flex items-end">
    <div class="w-full bg-base-100 rounded-t-2xl max-h-[80vh] flex flex-col">
      <div class="flex justify-center py-2"><div class="w-10 h-1 bg-base-300 rounded-full" /></div>
      <div class="px-4 pb-3"><div class="relative">
        <input v-model="searchTerm" type="text" placeholder="搜索颜色..." class="w-full pl-10 pr-4 py-2 border border-base-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-primary" />
        <svg class="absolute left-3 top-2.5 h-5 w-5 text-base-content/55" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" :stroke-width="2" d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" /></svg>
      </div></div>
      <div class="px-4 pb-3"><select v-model="sortBy" class="w-full p-2 border border-base-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-primary">
        <option value="progress">按进度排序</option><option value="name">按名称排序</option><option value="total">按数量排序</option>
      </select></div>
      <div class="flex-1 overflow-y-auto px-4 pb-4">
        <button v-for="colorInfo in filteredAndSortedColors" :key="colorInfo.color" @click="selectColor(colorInfo.color)"
          class="w-full p-3 mb-2 rounded-lg border-2 transition-all"
          :class="[colorInfo.color === currentColor ? 'border-primary bg-primary/10' : 'border-base-300 bg-base-100 hover:border-base-300', progress(colorInfo) === 100 ? 'opacity-60' : '']">
          <div class="flex items-center justify-between">
            <div class="flex items-center space-x-3">
              <div class="w-10 h-10 rounded-full border-2 border-base-300 shrink-0" :style="{ backgroundColor: colorInfo.color }" />
              <div class="text-left"><div class="text-sm font-medium text-base-content font-mono">{{ colorInfo.name }}</div>
                <div class="text-xs text-base-content/70">{{ colorInfo.completed }}/{{ colorInfo.total }} ({{ progress(colorInfo) }}%)</div></div>
            </div>
            <div class="flex items-center space-x-2">
              <div v-if="progress(colorInfo) === 100" class="text-success"><svg class="w-5 h-5" fill="currentColor" viewBox="0 0 20 20"><path fill-rule="evenodd" d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z" clip-rule="evenodd" /></svg></div>
              <div v-if="colorInfo.color === currentColor" class="text-primary"><svg class="w-5 h-5" fill="currentColor" viewBox="0 0 20 20"><path fill-rule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zm3.707-9.293a1 1 0 00-1.414-1.414L9 10.586 7.707 9.293a1 1 0 00-1.414 1.414l2 2a1 1 0 001.414 0l4-4z" clip-rule="evenodd" /></svg></div>
            </div>
          </div>
          <div class="mt-2 w-full bg-base-200 rounded-full h-1.5"><div class="h-1.5 rounded-full transition-all" :class="progress(colorInfo) === 100 ? 'bg-success' : 'bg-primary'" :style="{ width: `${progress(colorInfo)}%` }" /></div>
        </button>
      </div>
      <div class="p-4 border-t border-base-300"><button @click="close" class="w-full py-3 bg-neutral text-neutral-content rounded-lg hover:bg-neutral transition-colors">关闭</button></div>
    </div>
  </div>
</template>
