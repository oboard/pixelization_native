<script setup lang="ts">
import { onBeforeUnmount } from 'vue'
import type { MappedPixel } from '../utils/pixelation'
import type { ColorSystem } from '../utils/colorSystemUtils'
import { exportCsvData } from '../utils/imageDownloader'

const props = defineProps<{
  isOpen: boolean
  onClose?: () => void
  onProceedWithoutDownload?: () => void
  mappedPixelData: MappedPixel[][] | null
  gridDimensions: { N: number; M: number } | null
  selectedColorSystem: ColorSystem
}>()
// 原回调 prop 或 @closed / @proceed-without-download 事件择一接入；下载后也触发 proceed-without-download。
const emit = defineEmits<{ closed: []; 'proceed-without-download': [] }>()
let timer: ReturnType<typeof setTimeout> | undefined
function proceed() { props.onProceedWithoutDownload?.(); emit('proceed-without-download') }
function close() { props.onClose?.(); emit('closed') }
function downloadAndProceed() {
  exportCsvData({ mappedPixelData: props.mappedPixelData, gridDimensions: props.gridDimensions, selectedColorSystem: props.selectedColorSystem })
  if (timer !== undefined) clearTimeout(timer)
  timer = setTimeout(() => { timer = undefined; proceed() }, 500)
}
onBeforeUnmount(() => { if (timer !== undefined) clearTimeout(timer) })
</script>

<template>
  <div v-if="isOpen" class="fixed inset-0 bg-black/50 flex items-center justify-center p-4 z-50">
    <div class="bg-base-100 rounded-xl shadow-2xl max-w-md w-full p-6 space-y-4">
      <div class="text-center"><div class="w-16 h-16 bg-secondary/10 rounded-full flex items-center justify-center mx-auto mb-4">
        <svg xmlns="http://www.w3.org/2000/svg" class="h-8 w-8 text-secondary" fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path stroke-linecap="round" stroke-linejoin="round" :stroke-width="2" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
          <path stroke-linecap="round" stroke-linejoin="round" :stroke-width="2" d="M2.458 12C3.732 7.943 7.523 5 12 5c4.478 0 8.268 2.943 9.542 7-1.274 4.057-5.064 7-9.542 7-4.477 0-8.268-2.943-9.542-7z" />
        </svg></div><h3 class="text-xl font-semibold text-base-content">进入专心拼豆模式</h3></div>
      <div class="text-sm text-base-content/70 space-y-3">
        <div class="bg-warning/10 border border-warning/30 rounded-lg p-3"><div class="flex items-start space-x-2">
          <svg xmlns="http://www.w3.org/2000/svg" class="h-5 w-5 text-warning shrink-0 mt-0.5" viewBox="0 0 20 20" fill="currentColor"><path fill-rule="evenodd" d="M8.257 3.099c.765-1.36 2.722-1.36 3.486 0l5.58 9.92c.75 1.334-.213 2.98-1.742 2.98H4.42c-1.53 0-2.493-1.646-1.743-2.98l5.58-9.92zM11 13a1 1 0 11-2 0 1 1 0 012 0zm-1-8a1 1 0 00-1 1v3a1 1 0 002 0V6a1 1 0 00-1-1z" clip-rule="evenodd" /></svg>
          <div><p class="font-medium text-warning">重要提醒</p><p class="text-warning">进入专心拼豆模式后，您将无法返回到当前的编辑界面。建议您先下载当前的数据文件（CSV格式）保存，以便日后重新导入使用。</p></div>
        </div></div>
        <div class="space-y-2"><p>专心拼豆模式特点：</p><ul class="text-xs space-y-1 text-base-content/70"><li>• 专为手机优化的拼豆助手</li><li>• 提供颜色引导和进度追踪</li><li>• 支持触摸操作和缩放查看</li><li>• 退出后将丢失当前编辑状态</li></ul></div>
      </div>
      <div class="flex flex-col space-y-2 pt-4">
        <button @click="downloadAndProceed" class="w-full py-2.5 px-4 bg-linear-to-br from-success to-success hover:from-success hover:to-success text-success-content rounded-lg font-medium transition-all duration-200 flex items-center justify-center space-x-2">
          <svg xmlns="http://www.w3.org/2000/svg" class="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" :stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4" /></svg><span>下载档案并进入</span>
        </button>
        <button @click="proceed" class="w-full py-2.5 px-4 bg-base-200 hover:bg-base-200 text-base-content rounded-lg font-medium transition-all duration-200">直接进入（不下载）</button>
        <button @click="close" class="w-full py-2 px-4 text-base-content/70 hover:text-base-content text-sm transition-colors">取消</button>
      </div>
    </div>
  </div>
</template>
