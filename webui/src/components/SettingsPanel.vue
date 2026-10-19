<script setup lang="ts">
import { computed, getCurrentInstance } from 'vue'

type GuidanceMode = 'nearest' | 'largest' | 'edge-first'
const props = defineProps<{
  guidanceMode: GuidanceMode
  onGuidanceModeChange?: (mode: GuidanceMode) => void
  gridSectionInterval: number
  onGridSectionIntervalChange?: (interval: number) => void
  showSectionLines: boolean
  onShowSectionLinesChange?: (show: boolean) => void
  sectionLineColor: string
  onSectionLineColorChange?: (color: string) => void
  enableCelebration: boolean
  onEnableCelebrationChange?: (enable: boolean) => void
  onClose?: () => void
  onDownload?: () => void
}>()
// 可保留原回调 prop，或改监听相应的 *-changed、closed、download-requested 事件；不要双重接入。
const emit = defineEmits<{
  'guidance-mode-changed': [mode: GuidanceMode]
  'grid-section-interval-changed': [interval: number]
  'show-section-lines-changed': [show: boolean]
  'section-line-color-changed': [color: string]
  'enable-celebration-changed': [enable: boolean]
  closed: []
  'download-requested': []
}>()
const instance = getCurrentInstance()
const canDownload = computed(() => !!props.onDownload || !!instance?.vnode.props?.onDownloadRequested)
const guidanceOptions: { value: GuidanceMode; title: string; detail: string }[] = [
  { value: 'nearest', title: '最近优先', detail: '推荐距离最近的格子' },
  { value: 'largest', title: '大块优先', detail: '优先推荐大色块区域' },
  { value: 'edge-first', title: '边缘优先', detail: '先完成边缘，再填充内部' },
]
const sectionLineColors = [
  { color: '#007acc', name: '蓝色' }, { color: '#28a745', name: '绿色' },
  { color: '#dc3545', name: '红色' }, { color: '#6f42c1', name: '紫色' },
  { color: '#fd7e14', name: '橙色' }, { color: '#6c757d', name: '灰色' },
]
function guidance(mode: GuidanceMode) { props.onGuidanceModeChange?.(mode); emit('guidance-mode-changed', mode) }
function interval(event: Event) { const value = parseInt((event.target as HTMLInputElement).value); props.onGridSectionIntervalChange?.(value); emit('grid-section-interval-changed', value) }
function sectionLines(event: Event) { const value = (event.target as HTMLInputElement).checked; props.onShowSectionLinesChange?.(value); emit('show-section-lines-changed', value) }
function lineColor(color: string) { props.onSectionLineColorChange?.(color); emit('section-line-color-changed', color) }
function celebration(event: Event) { const value = (event.target as HTMLInputElement).checked; props.onEnableCelebrationChange?.(value); emit('enable-celebration-changed', value) }
function close() { props.onClose?.(); emit('closed') }
function download() { props.onDownload?.(); emit('download-requested') }
</script>

<template>
  <div class="fixed inset-0 bg-black bg-opacity-50 z-50 flex items-start justify-end">
    <div class="w-80 max-w-[90vw] h-full bg-white shadow-lg flex flex-col">
      <div class="flex items-center justify-between p-4 border-b border-gray-200">
        <h2 class="text-lg font-medium text-gray-800">设置</h2>
        <button @click="close" class="text-gray-500 hover:text-gray-700"><svg class="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" :stroke-width="2" d="M6 18L18 6M6 6l12 12" /></svg></button>
      </div>
      <div class="flex-1 overflow-y-auto p-4 space-y-6">
        <div><h3 class="text-base font-medium text-gray-800 mb-3">智能引导</h3><div class="space-y-3">
          <label v-for="option in guidanceOptions" :key="option.value" class="flex items-center">
            <input type="radio" name="guidanceMode" :value="option.value" :checked="guidanceMode === option.value" @change="guidance(option.value)" class="mr-3 text-blue-600" />
            <div><div class="text-sm font-medium text-gray-700">{{ option.title }}</div><div class="text-xs text-gray-500">{{ option.detail }}</div></div>
          </label>
        </div></div>
        <div><h3 class="text-base font-medium text-gray-800 mb-3">显示设置</h3><div class="space-y-4">
          <label class="flex items-center justify-between"><div><div class="text-sm font-medium text-gray-700">显示分割线</div><div class="text-xs text-gray-500">将画布分割成区块帮助定位</div></div>
            <input type="checkbox" :checked="showSectionLines" @change="sectionLines" class="h-4 w-4 text-blue-600 rounded" /></label>
          <template v-if="showSectionLines">
            <div><label class="text-sm font-medium text-gray-700 block mb-2">分割间隔</label><div class="flex items-center space-x-3">
              <input type="range" min="5" max="20" :value="gridSectionInterval" @input="interval" class="flex-1 h-2 bg-gray-200 rounded-lg appearance-none cursor-pointer" />
              <span class="text-sm font-medium text-gray-700 min-w-[3rem]">{{ gridSectionInterval }} 格</span>
            </div></div>
            <div><label class="text-sm font-medium text-gray-700 block mb-2">分割线颜色</label><div class="flex gap-2 flex-wrap">
              <button v-for="colorOption in sectionLineColors" :key="colorOption.color" @click="lineColor(colorOption.color)" class="w-6 h-6 rounded-full border-2 transition-all" :class="sectionLineColor === colorOption.color ? 'border-gray-800 scale-110' : 'border-gray-300 hover:border-gray-500'" :style="{ backgroundColor: colorOption.color }" :title="colorOption.name" />
            </div></div>
          </template>
          <label class="flex items-center justify-between"><div><div class="text-sm font-medium text-gray-700">庆祝动画</div><div class="text-xs text-gray-500">完成颜色时显示撒花效果</div></div>
            <input type="checkbox" :checked="enableCelebration" @change="celebration" class="h-4 w-4 text-blue-600 rounded" /></label>
        </div></div>
        <div><h3 class="text-base font-medium text-gray-800 mb-3">图纸与数据</h3><div class="space-y-3">
          <button v-if="canDownload" @click="download" class="w-full py-2 px-4 bg-green-100 text-green-700 rounded-lg hover:bg-green-200 transition-colors text-sm flex items-center justify-center gap-2">
            <svg xmlns="http://www.w3.org/2000/svg" class="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" :stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4" /></svg>下载拼豆图纸
          </button>
          <button class="w-full py-2 px-4 bg-orange-100 text-orange-700 rounded-lg hover:bg-orange-200 transition-colors text-sm">导出进度数据</button>
          <button class="w-full py-2 px-4 bg-red-100 text-red-700 rounded-lg hover:bg-red-200 transition-colors text-sm">重置所有进度</button>
        </div></div>
        <div><h3 class="text-base font-medium text-gray-800 mb-3">关于</h3><div class="text-sm text-gray-600 space-y-2"><p>专心拼豆模式 v1.0</p><p>专为手机设计的拼豆助手</p><div class="pt-2 text-xs text-gray-500"><p>💡 提示：长按格子可以快速标记</p><p>💡 提示：双指缩放可以查看细节</p></div></div></div>
      </div>
    </div>
  </div>
</template>
