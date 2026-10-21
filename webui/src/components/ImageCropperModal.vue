<script setup lang="ts">
import { nextTick, onBeforeUnmount, ref, watch } from 'vue'
import Cropper from 'cropperjs'
import 'cropperjs/dist/cropper.css'

const props = defineProps<{
  imageSrc: string
  isOpen: boolean
  onClose: () => void
  onConfirm: (croppedImageSrc: string) => void
}>()

const imageRef = ref<HTMLImageElement | null>(null)
const isProcessing = ref(false)
let cropper: Cropper | null = null

function destroyCropper() {
  cropper?.destroy()
  cropper = null
}

watch(
  [() => props.imageSrc, () => props.isOpen],
  async ([, open], _, onCleanup) => {
    let cancelled = false
    onCleanup(() => { cancelled = true })
    destroyCropper()
    if (!open) return
    await nextTick()
    if (cancelled || !imageRef.value) return
    cropper = new Cropper(imageRef.value, {
      aspectRatio: NaN,
      viewMode: 1,
      dragMode: 'move',
      autoCropArea: 0.8,
      restore: false,
      guides: true,
      center: true,
      highlight: true,
      cropBoxMovable: true,
      cropBoxResizable: true,
      toggleDragModeOnDblclick: false,
      responsive: true,
      checkOrientation: false,
    })
  },
  { immediate: true, flush: 'post' },
)

onBeforeUnmount(destroyCropper)

function handleConfirm() {
  if (!cropper) {
    console.error('Cropper instance not found')
    return
  }

  isProcessing.value = true
  try {
    const croppedCanvas = cropper.getCroppedCanvas({
      fillColor: '#fff',
      imageSmoothingEnabled: true,
      imageSmoothingQuality: 'high',
    })
    if (!croppedCanvas) throw new Error('Failed to get cropped canvas')
    props.onConfirm(croppedCanvas.toDataURL('image/png'))
  } catch (error) {
    console.error('裁剪图片失败:', error)
    alert('裁剪图片失败，请重试')
  } finally {
    isProcessing.value = false
  }
}

function handleRotateLeft() { cropper?.rotate(-90) }
function handleRotateRight() { cropper?.rotate(90) }
function handleFlipHorizontal() {
  if (!cropper) return
  const scaleX = cropper.getData().scaleX || 1
  cropper.scaleX(-scaleX)
}
function handleFlipVertical() {
  if (!cropper) return
  const scaleY = cropper.getData().scaleY || 1
  cropper.scaleY(-scaleY)
}
function handleReset() { cropper?.reset() }
</script>

<template>
  <div v-if="isOpen" class="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-sm p-4">
    <div class="bg-base-100 rounded-xl shadow-2xl max-w-5xl w-full max-h-[90vh] flex flex-col">
      <!-- 标题栏 -->
      <div class="flex items-center justify-between px-6 py-4 border-b border-base-300">
        <h2 class="text-lg font-semibold text-base-content">裁剪图片</h2>
        <button @click="onClose" class="text-base-content/70 hover:text-base-content transition-colors">
          <svg class="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" :stroke-width="2" d="M6 18L18 6M6 6l12 12" />
          </svg>
        </button>
      </div>

      <!-- 裁剪区域 -->
      <div class="flex-1 overflow-auto p-4 bg-base-200">
        <div class="relative w-full h-[50vh] min-h-75">
          <img ref="imageRef" :src="imageSrc" alt="" :style="{ height: '100%', width: '100%' }" />
        </div>
      </div>

      <!-- 工具栏 -->
      <div class="px-6 py-3 border-t border-base-300 bg-base-200">
        <div class="flex flex-wrap items-center justify-center gap-2">
          <button @click="handleRotateLeft" class="p-2 rounded-lg bg-base-100 border border-base-300 text-base-content hover:bg-base-200 transition-colors" title="向左旋转">
            <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" :stroke-width="2" d="M3 10h10a8 8 0 018 8v2M3 10l6 6m-6-6l6-6" />
            </svg>
          </button>
          <button @click="handleRotateRight" class="p-2 rounded-lg bg-base-100 border border-base-300 text-base-content hover:bg-base-200 transition-colors" title="向右旋转">
            <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" :stroke-width="2" d="M21 10h-10a8 8 0 00-8 8v2M21 10l-6 6m6-6l-6-6" />
            </svg>
          </button>
          <div class="w-px h-6 bg-base-300 mx-1"></div>
          <button @click="handleFlipHorizontal" class="p-2 rounded-lg bg-base-100 border border-base-300 text-base-content hover:bg-base-200 transition-colors" title="水平翻转">
            <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" :stroke-width="2" d="M8 7h12m0 0l-4-4m4 4l-4 4m0 6H4m0 0l4 4m-4-4l4-4" />
            </svg>
          </button>
          <button @click="handleFlipVertical" class="p-2 rounded-lg bg-base-100 border border-base-300 text-base-content hover:bg-base-200 transition-colors" title="垂直翻转">
            <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24" style="transform: rotate(90deg)">
              <path stroke-linecap="round" stroke-linejoin="round" :stroke-width="2" d="M8 7h12m0 0l-4-4m4 4l-4 4m0 6H4m0 0l4 4m-4-4l4-4" />
            </svg>
          </button>
          <div class="w-px h-6 bg-base-300 mx-1"></div>
          <button @click="handleReset" class="p-2 rounded-lg bg-base-100 border border-base-300 text-base-content hover:bg-base-200 transition-colors" title="重置">
            <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" :stroke-width="2" d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
            </svg>
          </button>
        </div>
      </div>

      <!-- 底部按钮 -->
      <div class="flex items-center justify-end gap-3 px-6 py-4 border-t border-base-300">
        <button @click="onClose" class="px-4 py-2 rounded-lg text-base-content hover:bg-base-200 transition-colors">取消</button>
        <button @click="handleConfirm" :disabled="isProcessing" class="px-6 py-2 rounded-lg bg-primary text-primary-content hover:bg-primary disabled:opacity-50 disabled:cursor-not-allowed transition-colors flex items-center gap-2">
          <template v-if="isProcessing">
            <svg class="animate-spin w-4 h-4" fill="none" viewBox="0 0 24 24">
              <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4" />
              <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z" />
            </svg>
            处理中...
          </template>
          <template v-else>确认裁剪</template>
        </button>
      </div>
    </div>
  </div>
</template>
