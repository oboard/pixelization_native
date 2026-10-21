<script setup lang="ts">
import ThemeSwitcher from "../../components/ThemeSwitcher.vue";
import { computed, onMounted, onUnmounted, reactive, ref, watch } from "vue";
import type { MappedPixel, PaletteColor } from "../../utils/pixelation";
import {
  getAllConnectedRegions,
  isRegionCompleted,
  getRegionCenter,
  sortRegionsByDistance,
  sortRegionsBySize,
  getConnectedRegion,
} from "../../utils/floodFillUtils";
import FocusCanvas from "../../components/FocusCanvas.vue";
import ColorStatusBar from "../../components/ColorStatusBar.vue";
import ProgressBar from "../../components/ProgressBar.vue";
import ToolBar from "../../components/ToolBar.vue";
import ColorPanel from "../../components/ColorPanel.vue";
import SettingsPanel from "../../components/SettingsPanel.vue";
import CelebrationAnimation from "../../components/CelebrationAnimation.vue";
import CompletionCard from "../../components/CompletionCard.vue";
import DownloadSettingsModal from "../../components/DownloadSettingsModal.vue";
import { getColorKeyByHex } from "../../utils/colorSystemUtils";
import type { ColorSystem } from "../../utils/colorSystemUtils";
import { downloadImage } from "../../utils/imageDownloader";
import type { GridDownloadOptions } from "../../types/downloadTypes";

interface FocusModeState {
  currentColor: string;
  selectedCell: { row: number; col: number } | null;
  canvasScale: number;
  canvasOffset: { x: number; y: number };
  completedCells: Set<string>;
  colorProgress: Record<string, { completed: number; total: number }>;
  guidanceMode: "nearest" | "largest" | "edge-first";
  showColorPanel: boolean;
  showSettingsPanel: boolean;
  isPaused: boolean;
  startTime: number;
  totalElapsedTime: number;
  lastResumeTime: number;
  gridSectionInterval: number;
  showSectionLines: boolean;
  sectionLineColor: string;
  enableCelebration: boolean;
  showCelebration: boolean;
  showCompletionCard: boolean;
}

function loadFocusData() {
  try {
    const savedPixelData = localStorage.getItem("focusMode_pixelData");
    const savedGridDimensions = localStorage.getItem("focusMode_gridDimensions");
    const savedColorCounts = localStorage.getItem("focusMode_colorCounts");
    const savedColorSystem = localStorage.getItem("focusMode_selectedColorSystem");
    if (!savedPixelData || !savedGridDimensions || !savedColorCounts) return null;

    const mappedPixelData = JSON.parse(savedPixelData) as MappedPixel[][];
    const gridDimensions = JSON.parse(savedGridDimensions) as { N: number; M: number };
    const colorCounts = JSON.parse(savedColorCounts) as Record<string, { color: string; count: number }>;
    const selectedColorSystem = (savedColorSystem as ColorSystem) || "MARD";
    const availableColors = Object.values(colorCounts).map(({ color, count }) => ({
      color,
      name: getColorKeyByHex(color, selectedColorSystem),
      total: count,
      completed: 0,
    }));
    return { mappedPixelData, gridDimensions, colorCounts, selectedColorSystem, availableColors };
  } catch (error) {
    console.error("Failed to load focus mode data:", error);
    return null;
  }
}

const initialData = loadFocusData();
const mappedPixelData = initialData?.mappedPixelData ?? null;
const gridDimensions = initialData?.gridDimensions ?? null;
const colorCounts = initialData?.colorCounts ?? null;
const selectedColorSystem = initialData?.selectedColorSystem ?? "MARD";
const focusState = reactive<FocusModeState>({
  currentColor: initialData?.availableColors[0]?.color ?? "",
  selectedCell: null,
  canvasScale: 1,
  canvasOffset: { x: 0, y: 0 },
  completedCells: new Set<string>(),
  colorProgress: Object.fromEntries(
    (initialData?.availableColors ?? []).map(({ color, total }) => [color, { completed: 0, total }]),
  ),
  guidanceMode: "nearest",
  showColorPanel: false,
  showSettingsPanel: false,
  isPaused: false,
  startTime: Date.now(),
  totalElapsedTime: 0,
  lastResumeTime: Date.now(),
  gridSectionInterval: 10,
  showSectionLines: true,
  sectionLineColor: "#007acc",
  enableCelebration: true,
  showCelebration: false,
  showCompletionCard: false,
});
const availableColors = ref(initialData?.availableColors ?? []);
const isDownloadSettingsOpen = ref(false);
const downloadOptions = ref<GridDownloadOptions>({
  showGrid: true,
  gridInterval: 10,
  showCoordinates: true,
  showCellNumbers: true,
  gridLineColor: "#555555",
  includeStats: true,
  exportCsv: false,
});

let timer: ReturnType<typeof setInterval> | null = null;
watch(
  () => focusState.isPaused,
  (isPaused) => {
    if (timer !== null) clearInterval(timer);
    timer = null;
    if (!isPaused) {
      timer = setInterval(() => {
        const now = Date.now();
        const elapsed = Math.floor((now - focusState.lastResumeTime) / 1000);
        focusState.totalElapsedTime += elapsed;
        focusState.lastResumeTime = now;
      }, 1000);
    }
  },
  { immediate: true, flush: "sync" },
);
onUnmounted(() => {
  if (timer !== null) clearInterval(timer);
});
onMounted(() => {
  if (!initialData) window.location.href = "/";
});

function hexToRgb(hex: string): { r: number; g: number; b: number } | null {
  const shorthandRegex = /^#?([a-f\d])([a-f\d])([a-f\d])$/i;
  const formattedHex = hex.replace(shorthandRegex, (m, r, g, b) => r + r + g + g + b + b);
  const result = /^#?([a-f\d]{2})([a-f\d]{2})([a-f\d]{2})$/i.exec(formattedHex);
  return result
    ? { r: parseInt(result[1], 16), g: parseInt(result[2], 16), b: parseInt(result[3], 16) }
    : null;
}

const activeBeadPalette: PaletteColor[] = colorCounts
  ? Object.entries(colorCounts).map(([key, data]) => ({
      key,
      hex: data.color,
      rgb: hexToRgb(data.color) || { r: 0, g: 0, b: 0 },
    }))
  : [];
const totalBeadCount = colorCounts
  ? Object.values(colorCounts).reduce((sum, color) => sum + color.count, 0)
  : 0;

function handleDownloadRequest(options?: GridDownloadOptions) {
  void downloadImage({
    mappedPixelData,
    gridDimensions,
    colorCounts,
    totalBeadCount,
    options: options || downloadOptions.value,
    activeBeadPalette,
    selectedColorSystem,
  });
}

const recommended = computed(() => {
  if (!mappedPixelData || !focusState.currentColor) return { region: null, cell: null };
  const allRegions = getAllConnectedRegions(mappedPixelData, focusState.currentColor);
  const incompleteRegions = allRegions.filter(
    (region) => !isRegionCompleted(region, focusState.completedCells),
  );
  if (incompleteRegions.length === 0) return { region: null, cell: null };

  let selectedRegion: { row: number; col: number }[];
  switch (focusState.guidanceMode) {
    case "nearest": {
      const referencePoint = focusState.selectedCell ?? {
        row: Math.floor(mappedPixelData.length / 2),
        col: Math.floor(mappedPixelData[0].length / 2),
      };
      selectedRegion = sortRegionsByDistance(incompleteRegions, referencePoint)[0];
      break;
    }
    case "largest":
      selectedRegion = sortRegionsBySize(incompleteRegions)[0];
      break;
    case "edge-first": {
      const M = mappedPixelData.length;
      const N = mappedPixelData[0].length;
      const edgeRegions = incompleteRegions.filter((region) =>
        region.some(
          (cell) => cell.row === 0 || cell.row === M - 1 || cell.col === 0 || cell.col === N - 1,
        ),
      );
      selectedRegion = edgeRegions.length > 0 ? edgeRegions[0] : incompleteRegions[0];
      break;
    }
    default:
      selectedRegion = incompleteRegions[0];
  }
  return { region: selectedRegion, cell: getRegionCenter(selectedRegion) };
});

function handleCellClick(row: number, col: number) {
  if (!mappedPixelData) return;
  const cellColor = mappedPixelData[row][col].color;
  if (cellColor !== focusState.currentColor) return;

  const region = getConnectedRegion(mappedPixelData, row, col, focusState.currentColor);
  if (region.length === 0) return;
  const newCompletedCells = new Set(focusState.completedCells);
  const isCurrentlyCompleted = isRegionCompleted(region, focusState.completedCells);
  region.forEach(({ row: r, col: c }) => {
    if (isCurrentlyCompleted) newCompletedCells.delete(`${r},${c}`);
    else newCompletedCells.add(`${r},${c}`);
  });

  const newColorProgress = { ...focusState.colorProgress };
  let colorJustCompleted = false;
  const progress = newColorProgress[focusState.currentColor];
  if (progress) {
    const oldCompleted = progress.completed;
    const newCompleted = Array.from(newCompletedCells).filter((key) => {
      const [r, c] = key.split(",").map(Number);
      return mappedPixelData[r]?.[c]?.color === focusState.currentColor;
    }).length;
    newColorProgress[focusState.currentColor] = { ...progress, completed: newCompleted };
    if (oldCompleted < progress.total && newCompleted === progress.total && focusState.enableCelebration) {
      colorJustCompleted = true;
    }
  }
  const allColorsCompleted = Object.values(newColorProgress).every(
    (value) => value.completed >= value.total,
  );
  const now = Date.now();
  focusState.completedCells = newCompletedCells;
  focusState.selectedCell = { row, col };
  focusState.colorProgress = newColorProgress;
  focusState.showCelebration = colorJustCompleted;
  if (allColorsCompleted && !focusState.isPaused) {
    focusState.totalElapsedTime += Math.floor((now - focusState.lastResumeTime) / 1000);
    focusState.isPaused = true;
  }
  availableColors.value = availableColors.value.map((color) =>
    color.color === focusState.currentColor
      ? { ...color, completed: newColorProgress[focusState.currentColor]?.completed || 0 }
      : color,
  );
}

function handleBack() {
  window.history.back();
}

function handleColorChange(color: string) {
  focusState.currentColor = color;
  focusState.showColorPanel = false;
}

function handleLocateRecommended() {
  if (!recommended.value.cell || !gridDimensions) return;
  const { row, col } = recommended.value.cell;
  const cellSize = Math.max(15, Math.min(40, 300 / Math.max(gridDimensions.N, gridDimensions.M)));
  const targetX = (col + 0.5) * cellSize;
  const targetY = (row + 0.5) * cellSize;
  const canvasCenterX = (gridDimensions.N * cellSize) / 2;
  const canvasCenterY = (gridDimensions.M * cellSize) / 2;
  focusState.canvasOffset = { x: canvasCenterX - targetX, y: canvasCenterY - targetY };
}

function formatTime(seconds: number): string {
  const hours = Math.floor(seconds / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);
  const secs = seconds % 60;
  if (hours > 0) {
    return `${hours}:${minutes.toString().padStart(2, "0")}:${secs.toString().padStart(2, "0")}`;
  }
  return `${minutes}:${secs.toString().padStart(2, "0")}`;
}

function handlePauseToggle() {
  const now = Date.now();
  if (focusState.isPaused) {
    focusState.lastResumeTime = now;
    focusState.isPaused = false;
  } else {
    focusState.totalElapsedTime += Math.floor((now - focusState.lastResumeTime) / 1000);
    focusState.isPaused = true;
  }
}

function handleCelebrationComplete() {
  focusState.showCelebration = false;
  if (availableColors.value.every((color) => color.completed >= color.total)) {
    focusState.showCompletionCard = true;
  } else {
    const currentIndex = availableColors.value.findIndex(
      (color) => color.color === focusState.currentColor,
    );
    if (currentIndex !== -1) {
      for (let i = 1; i < availableColors.value.length; i++) {
        const nextColor = availableColors.value[(currentIndex + i) % availableColors.value.length];
        if (nextColor.completed < nextColor.total) {
          focusState.currentColor = nextColor.color;
          break;
        }
      }
    }
  }
}

function handleDownloadOptionsChange(options: GridDownloadOptions) {
  downloadOptions.value = options;
}

const currentColorInfo = computed(() =>
  availableColors.value.find((color) => color.color === focusState.currentColor),
);
const progressPercentage = computed(() =>
  currentColorInfo.value
    ? Math.round((currentColorInfo.value.completed / currentColorInfo.value.total) * 100)
    : 0,
);
</script>

<template>
  <div v-if="!mappedPixelData || !gridDimensions" class="min-h-screen bg-base-200 flex items-center justify-center">
    <div class="text-center">
      <div class="animate-spin rounded-full h-12 w-12 border-b-2 border-primary mx-auto mb-4"></div>
      <p class="text-base-content/70">加载中...</p>
    </div>
  </div>
  <div v-else class="h-screen flex flex-col bg-base-200">
    <!-- 顶部导航栏 -->
    <header class="min-h-15 bg-base-100 shadow-sm border-b border-base-300 px-4 py-3 flex flex-wrap gap-3 items-center justify-between">
      <button
        class="flex items-center text-base-content/70 hover:text-base-content"
        @click="handleBack"
      >
        <svg class="w-6 h-6 mr-1" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path stroke-linecap="round" stroke-linejoin="round" :stroke-width="2" d="M15 19l-7-7 7-7" />
        </svg>
        返回
      </button>
      <ThemeSwitcher />
      <h1 class="text-lg font-medium text-base-content">专心拼豆（AlphaTest）</h1>
      <button
        class="text-base-content/70 hover:text-base-content"
        aria-label="打开设置"
        @click="focusState.showSettingsPanel = true"
      >
        <svg class="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path
            stroke-linecap="round"
            stroke-linejoin="round"
            :stroke-width="2"
            d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.065 2.572c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.572 1.065c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.065-2.572c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z"
          />
          <path stroke-linecap="round" stroke-linejoin="round" :stroke-width="2" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
        </svg>
      </button>
    </header>

    <!-- 当前颜色状态栏 -->
    <ColorStatusBar
      :currentColor="focusState.currentColor"
      :colorInfo="currentColorInfo"
      :progressPercentage="progressPercentage"
    />

    <!-- 主画布区域 -->
    <div class="flex-1 relative overflow-hidden">
      <FocusCanvas
        :mappedPixelData="mappedPixelData"
        :gridDimensions="gridDimensions"
        :currentColor="focusState.currentColor"
        :completedCells="focusState.completedCells"
        :recommendedCell="recommended.cell"
        :recommendedRegion="recommended.region"
        :canvasScale="focusState.canvasScale"
        :canvasOffset="focusState.canvasOffset"
        :gridSectionInterval="focusState.gridSectionInterval"
        :showSectionLines="focusState.showSectionLines"
        :sectionLineColor="focusState.sectionLineColor"
        :onCellClick="handleCellClick"
        :onScaleChange="(scale: number) => (focusState.canvasScale = scale)"
        :onOffsetChange="(offset: { x: number; y: number }) => (focusState.canvasOffset = offset)"
      />
    </div>

    <!-- 快速进度条 -->
    <ProgressBar
      :progressPercentage="progressPercentage"
      :recommendedCell="recommended.cell"
      :colorInfo="currentColorInfo"
    />

    <!-- 底部工具栏 -->
    <ToolBar
      :onColorSelect="() => (focusState.showColorPanel = true)"
      :onLocate="handleLocateRecommended"
      :onPause="handlePauseToggle"
      :isPaused="focusState.isPaused"
      :elapsedTime="formatTime(focusState.totalElapsedTime)"
    />

    <!-- 颜色选择面板 -->
    <ColorPanel
      v-if="focusState.showColorPanel"
      :colors="availableColors"
      :currentColor="focusState.currentColor"
      :onColorSelect="handleColorChange"
      :onClose="() => (focusState.showColorPanel = false)"
    />

    <!-- 设置面板 -->
    <SettingsPanel
      v-if="focusState.showSettingsPanel"
      :guidanceMode="focusState.guidanceMode"
      :onGuidanceModeChange="(mode: FocusModeState['guidanceMode']) => (focusState.guidanceMode = mode)"
      :gridSectionInterval="focusState.gridSectionInterval"
      :onGridSectionIntervalChange="(interval: number) => (focusState.gridSectionInterval = interval)"
      :showSectionLines="focusState.showSectionLines"
      :onShowSectionLinesChange="(show: boolean) => (focusState.showSectionLines = show)"
      :sectionLineColor="focusState.sectionLineColor"
      :onSectionLineColorChange="(color: string) => (focusState.sectionLineColor = color)"
      :enableCelebration="focusState.enableCelebration"
      :onEnableCelebrationChange="(enable: boolean) => (focusState.enableCelebration = enable)"
      :onClose="() => (focusState.showSettingsPanel = false)"
      :onDownload="() => (isDownloadSettingsOpen = true)"
    />

    <!-- 下载设置弹窗 -->
    <DownloadSettingsModal
      v-if="isDownloadSettingsOpen"
      :isOpen="isDownloadSettingsOpen"
      :onClose="() => (isDownloadSettingsOpen = false)"
      :options="downloadOptions"
      :onOptionsChange="handleDownloadOptionsChange"
      :onDownload="handleDownloadRequest"
    />

    <!-- 庆祝动画 -->
    <CelebrationAnimation
      :isVisible="focusState.showCelebration"
      :onComplete="handleCelebrationComplete"
    />

    <!-- 完成打卡图 -->
    <CompletionCard
      :isVisible="focusState.showCompletionCard"
      :mappedPixelData="mappedPixelData"
      :gridDimensions="gridDimensions"
      :totalElapsedTime="focusState.totalElapsedTime"
      :onClose="() => (focusState.showCompletionCard = false)"
    />
  </div>
</template>
