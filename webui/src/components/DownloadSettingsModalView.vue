<script setup lang="ts">
import { ref } from "vue";
import type { GridDownloadOptions } from "../types/downloadTypes";
import { gridLineColorOptions } from "./gridLineColorOptions";

const props = defineProps<{
  isOpen: boolean;
  onClose: () => void;
  options: GridDownloadOptions;
  onOptionsChange: (options: GridDownloadOptions) => void;
  onDownload: (opts?: GridDownloadOptions) => void;
}>();

const tempOptions = ref<GridDownloadOptions>({ ...props.options });

function handleOptionChange<K extends keyof GridDownloadOptions>(key: K, value: GridDownloadOptions[K]) {
  tempOptions.value = { ...tempOptions.value, [key]: value };
}

function handleSave() {
  props.onOptionsChange(tempOptions.value);
  props.onDownload(tempOptions.value);
  props.onClose();
}
</script>

<template>
  <div v-if="isOpen" class="fixed inset-0 bg-black/50 backdrop-blur-sm flex items-center justify-center z-50 p-4">
    <div class="bg-base-100 rounded-xl shadow-lg overflow-hidden w-full max-w-md">
      <div class="p-5">
        <div class="flex justify-between items-center border-b pb-3 mb-4">
          <h3 class="text-lg font-semibold text-base-content">下载图纸设置</h3>
          <button class="text-base-content/70 hover:text-base-content" @click="onClose">
            <svg xmlns="http://www.w3.org/2000/svg" class="h-5 w-5" viewBox="0 0 20 20" fill="currentColor">
              <path fill-rule="evenodd" d="M4.293 4.293a1 1 0 011.414 0L10 8.586l4.293-4.293a1 1 0 111.414 1.414L11.414 10l4.293 4.293a1 1 0 01-1.414 1.414L10 11.414l-4.293 4.293a1 1 0 01-1.414-1.414L8.586 10 4.293 5.707a1 1 0 010-1.414z" clip-rule="evenodd" />
            </svg>
          </button>
        </div>

        <div class="space-y-4">
          <div class="flex items-center justify-between">
            <label class="flex items-center text-sm font-medium text-base-content">显示网格线</label>
            <label class="relative inline-flex items-center cursor-pointer">
              <input type="checkbox" class="sr-only peer" :checked="tempOptions.showGrid" @change="handleOptionChange('showGrid', ($event.target as HTMLInputElement).checked)" />
              <div class="w-11 h-6 bg-base-200 peer-focus:outline-none rounded-full peer peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-base-100 after:border-base-300 after:border after:rounded-full after:h-5 after:w-5 after:transition-all peer-checked:bg-primary"></div>
            </label>
          </div>

          <div v-if="tempOptions.showGrid" class="space-y-4 pl-2 border-l-2 border-base-300 ml-1 pt-2 pb-1">
            <div class="flex flex-col space-y-2">
              <label class="text-sm font-medium text-base-content">网格线间隔 (每 N 格画一条线)</label>
              <div class="flex items-center justify-between space-x-3">
                <input type="range" min="5" max="20" step="1" :value="tempOptions.gridInterval" class="w-full h-2 bg-base-200 rounded-lg appearance-none cursor-pointer" @input="handleOptionChange('gridInterval', parseInt(($event.target as HTMLInputElement).value))" />
                <span class="flex items-center justify-center min-w-[40px] text-sm font-medium text-base-content">{{ tempOptions.gridInterval }}</span>
              </div>
            </div>
            <div class="flex flex-col space-y-2">
              <label class="text-sm font-medium text-base-content">网格线颜色</label>
              <div class="flex flex-wrap gap-2">
                <button v-for="colorOpt in gridLineColorOptions" :key="colorOpt.value" type="button" class="w-8 h-8 rounded-full border-2 transition-all duration-150 flex items-center justify-center" :class="tempOptions.gridLineColor === colorOpt.value ? 'border-primary ring-2 ring-primary ring-offset-1 ' : 'border-base-300  hover:border-base-300 '" :title="colorOpt.name" @click="handleOptionChange('gridLineColor', colorOpt.value)">
                  <span class="block w-6 h-6 rounded-full" :style="{ backgroundColor: colorOpt.value }"></span>
                </button>
              </div>
            </div>
          </div>

          <div class="flex items-center justify-between">
            <label class="flex items-center text-sm font-medium text-base-content">显示坐标数字</label>
            <label class="relative inline-flex items-center cursor-pointer">
              <input type="checkbox" class="sr-only peer" :checked="tempOptions.showCoordinates" @change="handleOptionChange('showCoordinates', ($event.target as HTMLInputElement).checked)" />
              <div class="w-11 h-6 bg-base-200 peer-focus:outline-none rounded-full peer peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-base-100 after:border-base-300 after:border after:rounded-full after:h-5 after:w-5 after:transition-all peer-checked:bg-primary"></div>
            </label>
          </div>
          <div class="flex items-center justify-between">
            <label class="flex items-center text-sm font-medium text-base-content">隐藏格内色号</label>
            <label class="relative inline-flex items-center cursor-pointer">
              <input type="checkbox" class="sr-only peer" :checked="!tempOptions.showCellNumbers" @change="handleOptionChange('showCellNumbers', !($event.target as HTMLInputElement).checked)" />
              <div class="w-11 h-6 bg-base-200 peer-focus:outline-none rounded-full peer peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-base-100 after:border-base-300 after:border after:rounded-full after:h-5 after:w-5 after:transition-all peer-checked:bg-primary"></div>
            </label>
          </div>
          <div class="flex items-center justify-between">
            <label class="flex items-center text-sm font-medium text-base-content">包含色号统计</label>
            <label class="relative inline-flex items-center cursor-pointer">
              <input type="checkbox" class="sr-only peer" :checked="tempOptions.includeStats" @change="handleOptionChange('includeStats', ($event.target as HTMLInputElement).checked)" />
              <div class="w-11 h-6 bg-base-200 peer-focus:outline-none rounded-full peer peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-base-100 after:border-base-300 after:border after:rounded-full after:h-5 after:w-5 after:transition-all peer-checked:bg-primary"></div>
            </label>
          </div>
          <div class="flex items-center justify-between">
            <div class="flex flex-col">
              <label class="flex items-center text-sm font-medium text-base-content">同时导出源数据</label>
              <span class="text-xs text-base-content/70 mt-1">导出hex颜色值的CSV文件，可用于重新导入</span>
            </div>
            <label class="relative inline-flex items-center cursor-pointer">
              <input type="checkbox" class="sr-only peer" :checked="tempOptions.exportCsv" @change="handleOptionChange('exportCsv', ($event.target as HTMLInputElement).checked)" />
              <div class="w-11 h-6 bg-base-200 peer-focus:outline-none rounded-full peer peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-base-100 after:border-base-300 after:border after:rounded-full after:h-5 after:w-5 after:transition-all peer-checked:bg-primary"></div>
            </label>
          </div>
        </div>

        <div class="flex justify-end mt-6 space-x-3">
          <button class="px-4 py-2 bg-base-200 hover:bg-base-300 text-base-content rounded-lg transition-colors" @click="onClose">取消</button>
          <button class="px-4 py-2 bg-primary hover:bg-primary text-primary-content rounded-lg transition-colors" @click="handleSave">下载图纸</button>
        </div>
      </div>
    </div>
  </div>
</template>
