<script setup lang="ts">
import { computed, ref } from 'vue'
import type { PaletteColor } from '../utils/pixelation'
import type { PaletteSelections } from '../utils/localStorageUtils'
import { getDisplayColorKey, type ColorSystem } from '../utils/colorSystemUtils'

const props = defineProps<{
  allColors: PaletteColor[]
  currentSelections: PaletteSelections
  onSelectionChange: (key: string, isSelected: boolean) => void
  onSaveCustomPalette: () => void
  onClose: () => void
  onExportCustomPalette: () => void
  onImportCustomPalette: () => void
  selectedColorSystem: ColorSystem
}>()
const expandedGroups = ref<Record<string, boolean>>({})
const searchTerm = ref('')
const selectedCount = computed(() => props.allColors.filter(color => props.currentSelections[color.hex.toUpperCase()]).length)
const filteredColors = computed(() => props.allColors.filter(color => {
  const search = searchTerm.value.toLowerCase()
  return !search || color.key.toLowerCase().includes(search) || getDisplayColorKey(color.hex, props.selectedColorSystem).toLowerCase().includes(search)
}))
const colorGroups = computed(() => {
  const groups: Record<string, PaletteColor[]> = {}
  for (const color of filteredColors.value) {
    const displayKey = getDisplayColorKey(color.hex, props.selectedColorSystem)
    let prefix: string
    if (props.selectedColorSystem === '盼盼' || props.selectedColorSystem === '咪小窝') {
      if (/^\d+$/.test(displayKey)) {
        const num = parseInt(displayKey, 10)
        prefix = num <= 20 ? '1-20' : num <= 50 ? '21-50' : num <= 100 ? '51-100' : num <= 200 ? '101-200' : '200+'
      } else prefix = '其他'
    } else prefix = displayKey.match(/^[A-Z]+/)?.[0] || '其他'
    ;(groups[prefix] ||= []).push(color)
  }
  for (const group of Object.values(groups)) {
    group.sort((a, b) => {
      const keyA = getDisplayColorKey(a.hex, props.selectedColorSystem)
      const keyB = getDisplayColorKey(b.hex, props.selectedColorSystem)
      return (parseInt(keyA.replace(/^[A-Z]+/, ''), 10) || 0) - (parseInt(keyB.replace(/^[A-Z]+/, ''), 10) || 0)
    })
  }
  return groups
})
const sortedPrefixes = computed(() => Object.keys(colorGroups.value).sort())
function toggleGroupColors(prefix: string, selected: boolean) {
  for (const color of colorGroups.value[prefix]) props.onSelectionChange(color.hex.toUpperCase(), selected)
}
function toggleAllColors(selected: boolean) {
  for (const color of props.allColors) props.onSelectionChange(color.hex.toUpperCase(), selected)
}
function checkboxChange(event: Event, color: PaletteColor) {
  props.onSelectionChange(color.hex.toUpperCase(), (event.target as HTMLInputElement).checked)
}
</script>

<template>
  <div class="flex flex-col h-full max-h-[calc(90vh-80px)]">
    <div class="flex justify-between items-center border-b dark:border-gray-700 pb-3 mb-3">
      <h2 class="text-lg font-semibold text-gray-800 dark:text-gray-100 flex items-center">
        <svg xmlns="http://www.w3.org/2000/svg" class="h-5 w-5 mr-2 text-blue-500" viewBox="0 0 20 20" fill="currentColor"><path fill-rule="evenodd" d="M4 2a2 2 0 00-2 2v11a3 3 0 106 0V4a2 2 0 00-2-2H4zm1 14a1 1 0 100-2 1 1 0 000 2zm5-1.757l4.9-4.9a2 2 0 000-2.828L13.485 5.1a2 2 0 00-2.828 0L10 5.757v8.486zM16 18H9.071l6-6H16a2 2 0 012 2v2a2 2 0 01-2 2z" clip-rule="evenodd" /></svg>
        色板管理中心 <span class="ml-2 text-sm text-blue-500 dark:text-blue-400">({{ selectedCount }} 色)</span>
      </h2>
      <button class="text-gray-500 dark:text-gray-400 hover:text-gray-700 dark:hover:text-gray-200" @click="onClose">
        <svg xmlns="http://www.w3.org/2000/svg" class="h-6 w-6" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" :stroke-width="2" d="M6 18L18 6M6 6l12 12" /></svg>
      </button>
    </div>
    <div class="mb-4"><div class="relative">
      <input v-model="searchTerm" type="text" placeholder="搜索色号..." class="w-full px-3 py-2 pl-9 border border-gray-300 dark:border-gray-600 rounded-md text-sm bg-white dark:bg-gray-700 text-gray-900 dark:text-gray-200 focus:ring-blue-500 focus:border-blue-500" />
      <div class="absolute inset-y-0 left-0 pl-3 flex items-center pointer-events-none"><svg xmlns="http://www.w3.org/2000/svg" class="h-4 w-4 text-gray-500 dark:text-gray-400" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" :stroke-width="2" d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" /></svg></div>
    </div></div>
    <div class="mb-4 text-xs text-gray-600 dark:text-gray-400 bg-blue-50 dark:bg-blue-900/20 p-2 rounded-md border border-blue-100 dark:border-blue-800/30">
      <p class="flex items-start"><svg xmlns="http://www.w3.org/2000/svg" class="h-4 w-4 mr-1 text-blue-500 shrink-0 mt-0.5" viewBox="0 0 20 20" fill="currentColor"><path fill-rule="evenodd" d="M18 10a8 8 0 11-16 0 8 8 0 0116 0zm-7-4a1 1 0 11-2 0 1 1 0 012 0zM9 9a1 1 0 000 2v3a1 1 0 001 1h1a1 1 0 100-2v-3a1 1 0 00-1-1H9z" clip-rule="evenodd" /></svg>在此选择要使用的拼豆色系。您可以选择预设色板，然后根据需要手动添加或删除特定色号。完成后点击底部的&quot;保存并应用&quot;按钮。</p>
    </div>
    <div class="flex flex-wrap gap-2 mb-4 items-center">
      <button class="px-3 py-1.5 text-xs bg-green-100 text-green-800 dark:bg-green-900/30 dark:text-green-300 rounded-md hover:bg-green-200 dark:hover:bg-green-900/50" @click="toggleAllColors(true)">全选</button>
      <button class="px-3 py-1.5 text-xs bg-red-100 text-red-800 dark:bg-red-900/30 dark:text-red-300 rounded-md hover:bg-red-200 dark:hover:bg-red-900/50" @click="toggleAllColors(false)">全不选</button>
      <button class="px-3 py-1.5 text-xs bg-blue-100 text-blue-800 dark:bg-blue-900/30 dark:text-blue-300 rounded-md hover:bg-blue-200 dark:hover:bg-blue-900/50 flex items-center gap-1" @click="onImportCustomPalette">
        <svg xmlns="http://www.w3.org/2000/svg" class="h-3.5 w-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" :stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-8l-4-4m0 0L8 8m4-4v12" /></svg>导入配置
      </button>
      <button class="px-3 py-1.5 text-xs bg-purple-100 text-purple-800 dark:bg-purple-900/30 dark:text-purple-300 rounded-md hover:bg-purple-200 dark:hover:bg-purple-900/50 flex items-center gap-1" @click="onExportCustomPalette">
        <svg xmlns="http://www.w3.org/2000/svg" class="h-3.5 w-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" :stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4" /></svg>导出配置
      </button>
    </div>
    <div class="flex-1 overflow-y-auto pr-1">
      <div v-for="prefix in sortedPrefixes" :key="prefix" class="mb-3 border border-gray-200 dark:border-gray-700 rounded-lg overflow-hidden">
        <div class="flex justify-between items-center px-3 py-2 bg-gray-50 dark:bg-gray-800 cursor-pointer hover:bg-gray-100 dark:hover:bg-gray-750" @click="expandedGroups[prefix] = !expandedGroups[prefix]">
          <div class="flex items-center"><span class="font-medium text-gray-800 dark:text-gray-200">{{ prefix }} 系列</span><span class="ml-2 text-xs text-gray-500 dark:text-gray-400">({{ colorGroups[prefix].length }} 色)</span></div>
          <div class="flex items-center">
            <button class="text-xs text-green-600 dark:text-green-400 hover:text-green-800 dark:hover:text-green-300 mr-2" @click.stop="toggleGroupColors(prefix, true)">全选</button>
            <button class="text-xs text-red-600 dark:text-red-400 hover:text-red-800 dark:hover:text-red-300 mr-2" @click.stop="toggleGroupColors(prefix, false)">全不选</button>
            <svg xmlns="http://www.w3.org/2000/svg" class="h-4 w-4 text-gray-500 dark:text-gray-400 transform transition-transform" :class="expandedGroups[prefix] ? 'rotate-180' : ''" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" :stroke-width="2" d="M19 9l-7 7-7-7" /></svg>
          </div>
        </div>
        <div v-if="expandedGroups[prefix]" class="p-3 grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 gap-2">
          <label v-for="color in colorGroups[prefix]" :key="color.key" class="flex items-center space-x-2 p-1.5 hover:bg-gray-50 dark:hover:bg-gray-750 rounded cursor-pointer">
            <input type="checkbox" :checked="!!currentSelections[color.hex.toUpperCase()]" class="h-4 w-4 rounded border-gray-300 text-blue-600 focus:ring-blue-500 dark:border-gray-600 dark:bg-gray-700 dark:ring-offset-gray-800" @change="checkboxChange($event, color)" />
            <div class="w-6 h-6 rounded-sm border border-gray-300 dark:border-gray-600 shrink-0" :style="{ backgroundColor: color.hex }" />
            <span class="text-sm text-gray-800 dark:text-gray-200">{{ getDisplayColorKey(color.hex, selectedColorSystem) }}</span>
          </label>
        </div>
      </div>
    </div>
    <div class="mt-4 pt-3 border-t dark:border-gray-700 flex justify-between">
      <button class="px-4 py-2 bg-gray-200 dark:bg-gray-700 text-gray-800 dark:text-gray-200 rounded-md hover:bg-gray-300 dark:hover:bg-gray-600" @click="onClose">取消</button>
      <button class="px-4 py-2 bg-blue-600 text-white rounded-md hover:bg-blue-700" @click="onSaveCustomPalette">保存并应用</button>
    </div>
  </div>
</template>
