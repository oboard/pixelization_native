<script setup lang="ts">
import { computed } from "vue";
import { getDisplayColorKey } from "../utils/colorSystemUtils";
import type { ColorSystem } from "../utils/colorSystemUtils";

interface ColorData {
  key: string;
  color: string;
  isExternal?: boolean;
}

interface ColorReplaceState {
  isActive: boolean;
  step: "select-source" | "select-target";
  sourceColor?: ColorData;
}

const props = defineProps<{
  colors: ColorData[];
  selectedColor: ColorData | null;
  onColorSelect: (colorData: ColorData) => void;
  transparentKey?: string;
  selectedColorSystem?: ColorSystem;
  isEraseMode?: boolean;
  onEraseToggle?: () => void;
  onHighlightColor?: (colorHex: string) => void;
  fullPaletteColors?: ColorData[];
  showFullPalette?: boolean;
  onToggleFullPalette?: () => void;
  colorReplaceState?: ColorReplaceState;
  onColorReplaceToggle?: () => void;
  onColorReplace?: (sourceColor: ColorData, targetColor: ColorData) => void;
}>();

const colorsToShow = computed(() =>
  props.showFullPalette && props.fullPaletteColors
    ? [
        props.colors.find((color) => props.transparentKey && color.key === props.transparentKey),
        ...props.fullPaletteColors,
      ].filter((color): color is ColorData => Boolean(color))
    : props.colors,
);

function isTransparent(color: ColorData) {
  return !!props.transparentKey && color.key === props.transparentKey;
}

function displayColorKey(color: ColorData) {
  return isTransparent(color)
    ? ""
    : props.selectedColorSystem
      ? getDisplayColorKey(color.color, props.selectedColorSystem)
      : color.key;
}

function contrastColor(hex: string) {
  const rgb = {
    r: parseInt(hex.slice(1, 3), 16),
    g: parseInt(hex.slice(3, 5), 16),
    b: parseInt(hex.slice(5, 7), 16),
  };
  const luma = (0.2126 * rgb.r + 0.7152 * rgb.g + 0.0722 * rgb.b) / 255;
  return luma > 0.5 ? "#000000" : "#FFFFFF";
}

function selectColor(color: ColorData) {
  if (
    props.colorReplaceState?.isActive &&
    props.colorReplaceState.step === "select-target" &&
    !isTransparent(color) &&
    props.onColorReplace &&
    props.colorReplaceState.sourceColor
  ) {
    props.onColorReplace(props.colorReplaceState.sourceColor, color);
    return;
  }

  props.onColorSelect(color);
  if (!isTransparent(color)) props.onHighlightColor?.(color.color);
}
</script>

<template>
  <p v-if="!colors || colors.length === 0" class="text-xs text-center text-gray-500 dark:text-gray-400 py-2">当前图纸无可用颜色。</p>
  <div v-else class="bg-white dark:bg-gray-900 rounded border border-blue-200 dark:border-gray-700">
    <div v-if="fullPaletteColors && fullPaletteColors.length > 0 && onToggleFullPalette" class="flex justify-center p-2 border-b border-blue-100 dark:border-gray-700">
      <button class="px-3 py-1.5 text-xs rounded-md transition-all duration-200 flex items-center gap-1.5" :class="showFullPalette ? 'bg-blue-100 dark:bg-blue-900/30 text-blue-700 dark:text-blue-300 border border-blue-300 dark:border-blue-600' : 'bg-gray-100 dark:bg-gray-700 text-gray-700 dark:text-gray-300 border border-gray-300 dark:border-gray-600 hover:bg-gray-200 dark:hover:bg-gray-600'" @click="onToggleFullPalette">
        <template v-if="showFullPalette">
          <svg xmlns="http://www.w3.org/2000/svg" class="h-3.5 w-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" :stroke-width="2">
            <path stroke-linecap="round" stroke-linejoin="round" d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
          </svg>
          只显示图中颜色
        </template>
        <template v-else>
          <svg xmlns="http://www.w3.org/2000/svg" class="h-3.5 w-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" :stroke-width="2">
            <path stroke-linecap="round" stroke-linejoin="round" d="M7 21a4 4 0 01-4-4V5a2 2 0 012-2h4a2 2 0 012 2v12a4 4 0 01-4 4zM21 5a2 2 0 00-2-2h-4a2 2 0 00-2 2v12a4 4 0 004 4h4a2 2 0 002-2V5z" />
          </svg>
          展开完整色板 ({{ fullPaletteColors.length }} 色)
        </template>
      </button>
    </div>

    <div v-if="colorReplaceState?.isActive" class="p-3 border-b border-purple-100 dark:border-purple-800 bg-purple-50 dark:bg-purple-900/20">
      <div class="text-center">
        <div class="flex items-center justify-center gap-2 mb-2">
          <svg xmlns="http://www.w3.org/2000/svg" class="h-4 w-4 text-purple-600 dark:text-purple-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" :stroke-width="2">
            <path stroke-linecap="round" stroke-linejoin="round" d="M8 7h12m0 0l-4-4m4 4l-4 4m0 6H4m0 0l4 4m-4-4l4-4" />
          </svg>
          <span class="text-sm font-medium text-purple-700 dark:text-purple-300">颜色替换模式</span>
        </div>
        <div v-if="colorReplaceState.step === 'select-source'" class="text-xs text-purple-600 dark:text-purple-400">
          <p class="mb-1">步骤 1/2：点击图中要被替换的颜色</p>
          <p class="text-gray-500 dark:text-gray-400">选择后将高亮显示该颜色的所有位置</p>
        </div>
        <div v-else class="text-xs text-purple-600 dark:text-purple-400">
          <p class="mb-1">步骤 2/2：从下方色板选择替换成的颜色</p>
          <div class="flex items-center justify-center gap-2 mt-2">
            <span class="text-gray-500 dark:text-gray-400">被替换的颜色：</span>
            <div class="flex items-center gap-1">
              <span class="inline-block w-4 h-4 rounded border border-gray-400 dark:border-gray-500" :style="{ backgroundColor: colorReplaceState.sourceColor?.color }"></span>
              <span class="font-mono text-xs">{{ selectedColorSystem ? getDisplayColorKey(colorReplaceState.sourceColor?.color || '', selectedColorSystem) : colorReplaceState.sourceColor?.key }}</span>
            </div>
          </div>
        </div>
      </div>
    </div>

    <div v-if="isEraseMode" class="p-3 border-b border-orange-100 dark:border-orange-800 bg-orange-50 dark:bg-orange-900/20">
      <div class="text-center">
        <div class="flex items-center justify-center gap-2 mb-2">
          <svg xmlns="http://www.w3.org/2000/svg" class="h-4 w-4 text-orange-600 dark:text-orange-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" :stroke-width="2">
            <path stroke-linecap="round" stroke-linejoin="round" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
          </svg>
          <span class="text-sm font-medium text-orange-700 dark:text-orange-300">背景擦除模式</span>
        </div>
        <div class="text-xs text-orange-600 dark:text-orange-400">
          <p class="mb-1">点击图中任意颜色，删除整个颜色块</p>
          <p class="text-gray-500 dark:text-gray-400">使用洪水填充算法，一次性擦除连通的相同颜色区域</p>
        </div>
      </div>
    </div>

    <div v-if="selectedColor?.key === transparentKey && !isEraseMode && !colorReplaceState?.isActive" class="p-3 border-b border-gray-100 dark:border-gray-700 bg-gray-50 dark:bg-gray-800/50">
      <div class="text-center">
        <div class="flex items-center justify-center gap-2 mb-2">
          <svg xmlns="http://www.w3.org/2000/svg" class="h-4 w-4 text-gray-600 dark:text-gray-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" :stroke-width="2">
            <path stroke-linecap="round" stroke-linejoin="round" d="M6 18L18 6M6 6l12 12" />
          </svg>
          <span class="text-sm font-medium text-gray-700 dark:text-gray-300">橡皮擦模式</span>
        </div>
        <div class="text-xs text-gray-600 dark:text-gray-400">
          <p class="mb-1">点击图中任意位置清除单个格子</p>
          <p class="text-gray-500 dark:text-gray-400">逐个删除不需要的颜色，不会影响其他格子</p>
        </div>
      </div>
    </div>

    <div class="flex flex-wrap justify-center gap-2 p-2">
      <button v-if="onEraseToggle" class="w-12 h-12 rounded border-2 shrink-0 transition-transform transform hover:scale-110 focus:outline-none focus:ring-2 focus:ring-offset-1 focus:ring-blue-400 dark:focus:ring-blue-500 flex items-center justify-center" :class="isEraseMode ? 'border-red-500 bg-red-100 dark:bg-red-900 ring-2 ring-offset-1 ring-red-400 dark:ring-red-500 scale-110 shadow-md' : 'border-orange-300 dark:border-orange-600 bg-orange-100 dark:bg-orange-800 hover:border-orange-500 dark:hover:border-orange-400'" :title="isEraseMode ? '退出一键擦除模式' : '一键擦除 (洪水填充删除相同颜色)'" :aria-label="isEraseMode ? '退出一键擦除模式' : '开启一键擦除模式'" @click="onEraseToggle">
        <svg xmlns="http://www.w3.org/2000/svg" class="h-5 w-5" :class="isEraseMode ? 'text-red-600 dark:text-red-400' : 'text-orange-600 dark:text-orange-400'" fill="none" viewBox="0 0 24 24" stroke="currentColor" :stroke-width="2">
          <path stroke-linecap="round" stroke-linejoin="round" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
        </svg>
      </button>

      <button v-if="onColorReplaceToggle" class="w-12 h-12 rounded border-2 shrink-0 transition-transform transform hover:scale-110 focus:outline-none focus:ring-2 focus:ring-offset-1 focus:ring-blue-400 dark:focus:ring-blue-500 flex items-center justify-center" :class="colorReplaceState?.isActive ? 'border-purple-500 bg-purple-100 dark:bg-purple-900 ring-2 ring-offset-1 ring-purple-400 dark:ring-purple-500 scale-110 shadow-md' : 'border-purple-300 dark:border-purple-600 bg-purple-100 dark:bg-purple-800 hover:border-purple-500 dark:hover:border-purple-400'" :title="colorReplaceState?.isActive ? '退出颜色替换模式' : '颜色替换 (将图中A颜色全部替换为B颜色)'" :aria-label="colorReplaceState?.isActive ? '退出颜色替换模式' : '开启颜色替换模式'" @click="onColorReplaceToggle">
        <svg xmlns="http://www.w3.org/2000/svg" class="h-5 w-5 text-purple-600 dark:text-purple-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" :stroke-width="2">
          <path stroke-linecap="round" stroke-linejoin="round" d="M8 7h12m0 0l-4-4m4 4l-4 4m0 6H4m0 0l4 4m-4-4l4-4" />
        </svg>
      </button>

      <button v-for="colorData in colorsToShow" :key="colorData.key" class="relative w-12 h-12 rounded border-2 shrink-0 transition-transform transform hover:scale-110 focus:outline-none focus:ring-2 focus:ring-offset-1 focus:ring-blue-400 dark:focus:ring-blue-500 flex items-center justify-center" :class="[selectedColor?.key === colorData.key ? 'border-black dark:border-gray-100 ring-2 ring-offset-1 ring-blue-400 dark:ring-blue-500 scale-110 shadow-md' : 'border-gray-300 dark:border-gray-600 hover:border-gray-500 dark:hover:border-gray-400', isTransparent(colorData) ? 'bg-gray-100 dark:bg-gray-700' : '']" :style="isTransparent(colorData) ? {} : { backgroundColor: colorData.color }" :title="isTransparent(colorData) ? '选择橡皮擦 (清除单元格)' : `选择 ${displayColorKey(colorData)} (${colorData.color})`" :aria-label="isTransparent(colorData) ? '选择橡皮擦' : `选择颜色 ${displayColorKey(colorData)}`" @click="selectColor(colorData)">
        <svg v-if="isTransparent(colorData)" xmlns="http://www.w3.org/2000/svg" class="h-5 w-5 text-gray-500 dark:text-gray-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" :stroke-width="2">
          <path stroke-linecap="round" stroke-linejoin="round" d="M6 18L18 6M6 6l12 12" />
        </svg>
        <span v-else class="text-xs font-bold font-mono leading-none text-center px-1" :style="{ color: contrastColor(colorData.color), textShadow: '0 0 2px rgba(0,0,0,0.5)', wordBreak: 'break-all', lineHeight: '1.1' }">{{ displayColorKey(colorData) }}</span>
      </button>
    </div>
  </div>
</template>
