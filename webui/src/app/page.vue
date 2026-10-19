<script setup lang="ts">
import { ref, computed, watch, onMounted, onUnmounted } from "vue";
import mard221Palette from "../../../mard_221_palette.json";

// 导入像素化工具和类型
import {
  PixelationMode,
  calculatePixelGrid,
  RgbColor,
  PaletteColor,
  MappedPixel,
  hexToRgb,
  colorDistance,
  findClosestPaletteColor,
} from "../utils/pixelation";

// 导入新的类型和组件
import { GridDownloadOptions } from "../types/downloadTypes";
import DownloadSettingsModal from "../components/DownloadSettingsModal.vue";
import { gridLineColorOptions } from "../components/gridLineColorOptions";
import { downloadImage, importCsvData } from "../utils/imageDownloader";

import {
  colorSystemOptions,
  getColorKeyByHex,
  getMardToHexMapping,
  sortColorsByHue,
  ColorSystem,
} from "../utils/colorSystemUtils";


// Helper function for sorting color keys - 保留原有实现，因为未在utils中导出
function sortColorKeys(a: string, b: string): number {
  const regex = /^([A-Z]+)(\d+)$/;
  const matchA = a.match(regex);
  const matchB = b.match(regex);

  if (matchA && matchB) {
    const prefixA = matchA[1];
    const numA = parseInt(matchA[2], 10);
    const prefixB = matchB[1];
    const numB = parseInt(matchB[2], 10);

    if (prefixA !== prefixB) {
      return prefixA.localeCompare(prefixB); // Sort by prefix first (A, B, C...)
    }
    return numA - numB; // Then sort by number (1, 2, 10...)
  }
  // Fallback for keys that don't match the standard pattern (e.g., T1, ZG1)
  return a.localeCompare(b);
}

// --- Define available palette key sets ---
// 从colorSystemMapping.json获取所有MARD色号
const mardToHexMapping = getMardToHexMapping();

// Pre-process the FULL palette data once - 使用colorSystemMapping而不是beadPaletteData
const fullBeadPalette: PaletteColor[] = Object.entries(mardToHexMapping)
  .map(([mardKey, hex]) => {
    const rgb = hexToRgb(hex);
    if (!rgb) {
      console.warn(`Invalid hex code "${hex}" for MARD key "${mardKey}". Skipping.`);
      return null;
    }
    // 使用hex值作为key，符合新的架构设计
    return { key: hex, hex, rgb };
  })
  .filter((color): color is PaletteColor => color !== null);

const mard221HexValues = new Set(mard221Palette.colors.map((color) => color.hex.toUpperCase()));

// ++ Add definition for background color keys ++

// 1. 导入新组件
import PixelatedPreviewCanvas from "../components/PixelatedPreviewCanvas.vue";
import GridTooltip from "../components/GridTooltip.vue";
import CustomPaletteEditor from "../components/CustomPaletteEditor.vue";
import FloatingColorPalette from "../components/FloatingColorPalette.vue";
import FloatingToolbar from "../components/FloatingToolbar.vue";
import MagnifierTool from "../components/MagnifierTool.vue";
import MagnifierSelectionOverlay from "../components/MagnifierSelectionOverlay.vue";
import {
  loadPaletteSelections,
  savePaletteSelections,
  presetToSelections,
  PaletteSelections,
} from "../utils/localStorageUtils";
import { TRANSPARENT_KEY, transparentColorData } from "../utils/pixelEditingUtils";

// 1. 导入新的 DonationModal 组件
import DonationModal from "../components/DonationModal.vue";
import FocusModePreDownloadModal from "../components/FocusModePreDownloadModal.vue";
import ImageCropperModal from "../components/ImageCropperModal.vue";



  const observers: MutationObserver[] = [];
  let statisticsScript: HTMLScriptElement | null = null;
  onMounted(() => {
    const script = document.createElement("script");
    statisticsScript = script;
    script.async = true;
    script.src = "https://busuanzi.ibruce.info/busuanzi/2.3/busuanzi.pure.mini.js";
    script.onload = () => {
      const updateCount = (spanId: string, baseValue: number) => {
        const targetNode = document.getElementById(spanId);
        if (!targetNode) return;

        const applyBaseValue = () => {
          const currentValueText = targetNode.textContent?.trim() || "0";
          if (currentValueText === "...") return false;

          const currentValue = parseInt(currentValueText.replace(/,/g, ""), 10) || 0;
          targetNode.textContent = (currentValue + baseValue).toLocaleString();
          return true;
        };

        if (applyBaseValue()) return;

        const observer = new MutationObserver(() => {
          if (applyBaseValue()) observer.disconnect();
        });
        observer.observe(targetNode, {
          childList: true,
          characterData: true,
          subtree: true,
        });
        observers.push(observer);
      };

      updateCount("busuanzi_value_site_pv", 378536);
      updateCount("busuanzi_value_site_uv", 257864);
    };

    document.body.appendChild(script);
  });
  onUnmounted(() => {
    observers.forEach((observer) => observer.disconnect());
    statisticsScript?.remove();
  });

  const originalImageSrc = ref<string | null>(null);
  const granularity = ref<number>(50);
  const granularityInput = ref<string>("50");
  const similarityThreshold = ref<number>(30);
  const similarityThresholdInput = ref<string>("30");
  // 添加像素化模式状态
  const pixelationMode = ref<PixelationMode>(PixelationMode.Dominant); // 默认为卡通模式

  // 新增：色号系统选择状态
  const selectedColorSystem = ref<ColorSystem>("MARD");
  const paletteSize = ref<221 | 291>(291);
  const availableBeadPalette = computed(() =>
    paletteSize.value === 221
      ? fullBeadPalette.filter((color) => mard221HexValues.has(color.hex.toUpperCase()))
      : fullBeadPalette,
  );
  // 新增：色号系统折叠状态
  const isColorSystemCollapsed = ref<boolean>(true);

  const activeBeadPalette = ref<PaletteColor[]>((() => {
    return fullBeadPalette; // 默认使用全部颜色
  })());
  // 状态变量：存储被排除的颜色（hex值）
  const excludedColorKeys = ref<Set<string>>(new Set());
  const showExcludedColors = ref<boolean>(false);
  // 用于记录初始网格颜色（hex值），用于显示排除功能
  const initialGridColorKeys = ref<Set<string>>(new Set());
  const mappedPixelData = ref<MappedPixel[][] | null>(null);
  const gridDimensions = ref<{
    N: number;
    M: number;
  } | null>(null);
  const colorCounts = ref<{
    [key: string]: { count: number; color: string };
  } | null>(null);
  const totalBeadCount = ref<number>(0);
  const tooltipData = ref<{
    x: number;
    y: number;
    key: string;
    color: string;
  } | null>(null);
  const remapTrigger = ref<number>(0);
  const isManualColoringMode = ref<boolean>(false);
  const selectedColor = ref<MappedPixel | null>(null);
  // 新增：一键擦除模式状态
  const isEraseMode = ref<boolean>(false);
  // 新增状态变量：控制打赏弹窗
  const isDonationModalOpen = ref<boolean>(false);
  // 新增状态变量：控制教程弹窗
  const isTutorialModalOpen = ref<boolean>(false);
  const customPaletteSelections = ref<PaletteSelections>({});
  const isCustomPaletteEditorOpen = ref<boolean>(false);
  const isCustomPalette = ref<boolean>(false);

  // ++ 新增：下载设置相关状态 ++
  const isDownloadSettingsOpen = ref<boolean>(false);
  const downloadOptions = ref<GridDownloadOptions>({
    showGrid: true,
    gridInterval: 10,
    showCoordinates: true,
    showCellNumbers: true,
    gridLineColor: gridLineColorOptions[0].value,
    includeStats: true, // 默认包含统计信息
    exportCsv: false, // 默认不导出CSV
  });

  // 新增：高亮相关状态
  const highlightColorKey = ref<string | null>(null);

  // 新增：完整色板切换状态
  const showFullPalette = ref<boolean>(false);

  // 新增：颜色替换相关状态
  const colorReplaceState = ref<{
    isActive: boolean;
    step: "select-source" | "select-target";
    sourceColor?: { key: string; color: string };
  }>({
    isActive: false,
    step: "select-source",
  });

  // 新增：组件挂载状态
  const isMounted = ref<boolean>(false);

  // 新增：悬浮调色盘状态
  const isFloatingPaletteOpen = ref<boolean>(true);

  // 新增：放大镜状态
  const isMagnifierActive = ref<boolean>(false);
  const magnifierSelectionArea = ref<{
    startRow: number;
    startCol: number;
    endRow: number;
    endCol: number;
  } | null>(null);

  // 新增：活跃工具层级管理
  const activeFloatingTool = ref<"palette" | "magnifier" | null>(null);

  // 新增：专心拼豆模式进入前下载提醒弹窗
  const isFocusModePreDownloadModalOpen = ref<boolean>(false);

  // 新增：图片裁剪弹窗状态
  const isCropperOpen = ref<boolean>(false);
  const cropperImageSrc = ref<string>("");

  // 放大镜切换处理函数
  const handleToggleMagnifier = () => {
    const newActiveState = !isMagnifierActive.value;
    isMagnifierActive.value = newActiveState;

    // 如果关闭放大镜，清除选择区域，重新开始
    if (!newActiveState) {
      magnifierSelectionArea.value = null;
    }
  };

  // 激活工具处理函数
  const handleActivatePalette = () => {
    activeFloatingTool.value = "palette";
  };

  const toggleFloatingPalette = () => {
    isFloatingPaletteOpen.value = !isFloatingPaletteOpen.value;
  };

  const exitManualMode = () => {
    isManualColoringMode.value = false;
    selectedColor.value = null;
    tooltipData.value = null;
    isEraseMode.value = false;
    colorReplaceState.value = { isActive: false, step: "select-source" };
    highlightColorKey.value = null;
    isMagnifierActive.value = false;
    magnifierSelectionArea.value = null;
  };

  const updateMagnifierSelection = (area: NonNullable<typeof magnifierSelectionArea.value>) => {
    magnifierSelectionArea.value = area;
  };

  const closeMagnifierSelection = () => {
    magnifierSelectionArea.value = null;
  };

  const updateDownloadOptions = (options: GridDownloadOptions) => {
    downloadOptions.value = options;
  };

  const handleActivateMagnifier = () => {
    activeFloatingTool.value = "magnifier";
  };

  // 放大镜像素编辑处理函数
  const handleMagnifierPixelEdit = (
    row: number,
    col: number,
    colorData: { key: string; color: string },
  ) => {
    if (!mappedPixelData.value) return;
    const oldPixel = mappedPixelData.value[row]?.[col];
    if (!oldPixel) return;

    // 创建新的像素数据
    const newMappedPixelData = mappedPixelData.value.map((rowData, r) =>
      rowData.map((pixel, c) => {
        if (r === row && c === col) {
          return colorData.key === TRANSPARENT_KEY
            ? { ...transparentColorData }
            : { key: colorData.key, color: colorData.color, isExternal: false } as MappedPixel;
        }
        return pixel;
      }),
    );

    mappedPixelData.value = newMappedPixelData;

    // 更新颜色统计
    if (colorCounts.value) {
      const newColorCounts = { ...colorCounts.value };

      // 减少原颜色的计数
      const oldHex = oldPixel.color.toUpperCase();
      const newHex = colorData.color.toUpperCase();
      if (!oldPixel.isExternal && oldPixel.key !== TRANSPARENT_KEY && newColorCounts[oldHex]) {
        newColorCounts[oldHex].count--;
        if (newColorCounts[oldHex].count === 0) {
          delete newColorCounts[oldHex];
        }
      }

      // 增加新颜色的计数
      if (colorData.key !== TRANSPARENT_KEY) {
        if (newColorCounts[newHex]) {
          newColorCounts[newHex].count++;
        } else {
          newColorCounts[newHex] = {
            count: 1,
            color: colorData.color,
          };
        }
      }

      colorCounts.value = newColorCounts;

      // 更新总计数
      const newTotal = Object.values(newColorCounts).reduce((sum, item) => sum + item.count, 0);
      totalBeadCount.value = newTotal;
    }
  };

  const originalCanvasRef = ref<HTMLCanvasElement | null>(null);
  const canvasHandle = { current: null as HTMLCanvasElement | null };
  let skipCsvPreviewRemap = false;
  const fileInputRef = ref<HTMLInputElement | null>(null);
  // ++ 添加: Ref for import file input ++
  const importPaletteInputRef = ref<HTMLInputElement | null>(null);
  //const longPressTimerRef = useRef<NodeJS.Timeout | null>(null);
  // ++ Re-add touch refs needed for tooltip logic ++
  //const touchStartPosRef = useRef<{ x: number; y: number; pageX: number; pageY: number } | null>(null);
  //const touchMovedRef = useRef<boolean>(false);

  // ++ Add a ref for the main element ++
  const mainRef = ref<HTMLElement | null>(null);

  // --- Derived State ---

  // ++ 添加：当状态变化时同步更新输入框的值 ++
  watch([() => granularity.value, () => similarityThreshold.value], (_values, _previous, onCleanup) => {
    granularityInput.value = granularity.value.toString();
    similarityThresholdInput.value = similarityThreshold.value.toString();
  }, { immediate: true, flush: 'sync' });

  // ++ Calculate unique colors currently on the grid for the palette ++
  const currentGridColors = computed(() => {
    if (!mappedPixelData.value) return [];
    // 使用hex值进行去重，避免多个MARD色号对应同一个目标色号系统值时产生重复key
    const uniqueColorsMap = new Map<string, MappedPixel>();
    mappedPixelData.value.flat().forEach((cell) => {
      if (cell && cell.color && !cell.isExternal) {
        const hexKey = cell.color.toUpperCase();
        if (!uniqueColorsMap.has(hexKey)) {
          // 存储hex值作为key，保持颜色信息
          uniqueColorsMap.set(hexKey, { key: cell.key, color: cell.color });
        }
      }
    });

    // 转换为数组并为每个hex值生成对应的色号系统显示
    const originalColors = Array.from(uniqueColorsMap.values());

    const colorData = originalColors.map((color) => {
      const displayKey = getColorKeyByHex(color.color.toUpperCase(), selectedColorSystem.value);
      return {
        key: displayKey,
        color: color.color,
      };
    });

    // 使用色相排序而不是色号排序
    return sortColorsByHue(colorData);
  });

  const gridColorStats = computed(() =>
    Object.keys(colorCounts.value ?? {})
      .sort(sortColorKeys)
      .map((hexKey) => ({
        hexKey,
        displayColorKey: getColorKeyByHex(hexKey, selectedColorSystem.value),
        isExcluded: excludedColorKeys.value.has(hexKey),
        count: colorCounts.value![hexKey].count,
        colorHex: colorCounts.value![hexKey].color,
      })),
  );

  const excludedColors = computed(() =>
    Array.from(excludedColorKeys.value)
      .sort(sortColorKeys)
      .map((hexKey) => ({
        hexKey,
        colorData: fullBeadPalette.find((color) => color.hex.toUpperCase() === hexKey.toUpperCase()),
      })),
  );

  const showExcludedColorList = () => {
    showExcludedColors.value = true;
    setTimeout(() => {
      document.querySelector(".color-stats-panel")?.scrollIntoView({ behavior: "smooth" });
    }, 100);
  };

  const restoreAllExcludedColors = () => {
    excludedColorKeys.value = new Set();
    remapTrigger.value++;
    isManualColoringMode.value = false;
    selectedColor.value = null;
  };

  // 初始化时从本地存储加载自定义色板选择
  onMounted(() => {
    // 尝试从localStorage加载
    const savedSelections = loadPaletteSelections();
    if (savedSelections && Object.keys(savedSelections).length > 0) {
      console.log("从localStorage加载的数据键数量:", Object.keys(savedSelections).length);
      // 验证加载的数据是否都是有效的hex值
      const allHexValues = fullBeadPalette.map((color) => color.hex.toUpperCase());
      const validSelections: PaletteSelections = {};
      let hasValidData = false;
      let validCount = 0;
      let invalidCount = 0;

      Object.entries(savedSelections).forEach(([key, value]) => {
        // 严格验证：键必须是有效的hex格式，并且存在于调色板中
        if (/^#[0-9A-F]{6}$/i.test(key) && allHexValues.includes(key.toUpperCase())) {
          validSelections[key.toUpperCase()] = value;
          hasValidData = true;
          validCount++;
        } else {
          invalidCount++;
        }
      });

      console.log(`验证结果: 有效键 ${validCount} 个, 无效键 ${invalidCount} 个`);

      if (hasValidData) {
        customPaletteSelections.value = validSelections;
        isCustomPalette.value = true;
      } else {
        console.log("所有数据都无效，清除localStorage并重新初始化");
        // 如果本地数据无效，清除localStorage并默认选择所有颜色
        localStorage.removeItem("customPerlerPaletteSelections");
        const allHexValues = fullBeadPalette.map((color) => color.hex.toUpperCase());
        const initialSelections = presetToSelections(allHexValues, allHexValues);
        customPaletteSelections.value = initialSelections;
        isCustomPalette.value = false;
      }
    } else {
      console.log("没有localStorage数据，默认选择所有颜色");
      // 如果没有保存的选择，默认选择所有颜色
      const allHexValues = fullBeadPalette.map((color) => color.hex.toUpperCase());
      const initialSelections = presetToSelections(allHexValues, allHexValues);
      customPaletteSelections.value = initialSelections;
      isCustomPalette.value = false;
    }
  }); // 只在组件首次加载时执行

  // 色板范围、自定义选择和排除颜色共同决定参与映射的颜色
  watch([availableBeadPalette, customPaletteSelections, excludedColorKeys], () => {
    activeBeadPalette.value = availableBeadPalette.value.filter((color) => {
      const hex = color.hex.toUpperCase();
      return customPaletteSelections.value[hex] && !excludedColorKeys.value.has(hex);
    });
  }, { immediate: true, flush: 'sync' });

  // --- Event Handlers ---

  // 专心拼豆模式相关处理函数
  const handleEnterFocusMode = () => {
    isFocusModePreDownloadModalOpen.value = true;
  };

  const handleProceedToFocusMode = () => {
    // 保存数据到localStorage供专心拼豆模式使用
    localStorage.setItem("focusMode_pixelData", JSON.stringify(mappedPixelData.value));
    localStorage.setItem("focusMode_gridDimensions", JSON.stringify(gridDimensions.value));
    localStorage.setItem("focusMode_colorCounts", JSON.stringify(colorCounts.value));
    localStorage.setItem("focusMode_selectedColorSystem", selectedColorSystem.value);

    // 跳转到专心拼豆页面
    window.location.href = "/focus";
  };

  // 添加一个安全的文件输入触发函数
  const triggerFileInput = () => {
    // 检查组件是否已挂载
    if (!isMounted.value) {
      console.warn("组件尚未完全挂载，延迟触发文件选择");
      setTimeout(() => triggerFileInput(), 200);
      return;
    }

    // 检查 ref 是否存在
    if (fileInputRef.value) {
      try {
        fileInputRef.value.click();
      } catch (error) {
        console.error("触发文件选择失败:", error);
        // 如果直接点击失败，尝试延迟执行
        setTimeout(() => {
          try {
            fileInputRef.value?.click();
          } catch (retryError) {
            console.error("重试触发文件选择失败:", retryError);
          }
        }, 100);
      }
    } else {
      // 如果 ref 不存在，延迟重试
      console.warn("文件输入引用不存在，将在100ms后重试");
      setTimeout(() => {
        if (fileInputRef.value) {
          try {
            fileInputRef.value.click();
          } catch (error) {
            console.error("延迟触发文件选择失败:", error);
          }
        }
      }, 100);
    }
  };

  const handleFileChange = (event: Event) => {
    const file = (event.target as HTMLInputElement).files?.[0];
    if (file) {
      // 检查文件类型是否支持
      const fileName = file.name.toLowerCase();
      const fileType = file.type.toLowerCase();

      // 支持的图片类型
      const supportedImageTypes = ["image/jpeg", "image/jpg", "image/png"];
      // 支持的CSV MIME类型（不同浏览器可能返回不同的MIME类型）
      const supportedCsvTypes = ["text/csv", "application/csv", "text/plain"];

      const isImageFile = supportedImageTypes.includes(fileType) || fileType.startsWith("image/");
      const isCsvFile = supportedCsvTypes.includes(fileType) || fileName.endsWith(".csv");

      if (isImageFile || isCsvFile) {
        excludedColorKeys.value = new Set(); // ++ 重置排除列表 ++
        processFile(file);
      } else {
        alert(
          `不支持的文件类型: ${file.type || "未知"}。请选择 JPG、PNG 格式的图片文件，或 CSV 数据文件。\n文件名: ${file.name}`,
        );
        console.warn(`Unsupported file type: ${file.type}, file name: ${file.name}`);
      }
    }
    // 重置文件输入框的值，这样用户可以重新选择同一个文件
    if (event.target) {
      (event.target as HTMLInputElement).value = "";
    }
  };

  const handleDrop = (event: DragEvent) => {
    event.preventDefault();
    event.stopPropagation();

    try {
      const file = event.dataTransfer?.files[0];
      if (file) {

        // 使用与handleFileChange相同的文件类型检查逻辑
        const fileName = file.name.toLowerCase();
        const fileType = file.type.toLowerCase();

        // 支持的图片类型
        const supportedImageTypes = ["image/jpeg", "image/jpg", "image/png"];
        // 支持的CSV MIME类型（不同浏览器可能返回不同的MIME类型）
        const supportedCsvTypes = ["text/csv", "application/csv", "text/plain"];

        const isImageFile = supportedImageTypes.includes(fileType) || fileType.startsWith("image/");
        const isCsvFile = supportedCsvTypes.includes(fileType) || fileName.endsWith(".csv");

        if (isImageFile || isCsvFile) {
          excludedColorKeys.value = new Set(); // ++ 重置排除列表 ++
          processFile(file);
        } else {
          alert(
            `不支持的文件类型: ${file.type || "未知"}。请拖放 JPG、PNG 格式的图片文件，或 CSV 数据文件。\n文件名: ${file.name}`,
          );
          console.warn(`Unsupported file type: ${file.type}, file name: ${file.name}`);
        }
      }
    } catch (error) {
      console.error("处理拖拽文件时发生错误:", error);
      alert("处理文件时发生错误，请重试。");
    }
  };

  const handleDragOver = (event: DragEvent) => {
    event.preventDefault();
    event.stopPropagation();
  };

  // 根据mappedPixelData生成合成的originalImageSrc
  const generateSyntheticImageFromPixelData = (
    pixelData: MappedPixel[][],
    dimensions: { N: number; M: number },
  ): string => {
    const canvas = document.createElement("canvas");
    const ctx = canvas.getContext("2d");

    if (!ctx) {
      console.error("无法创建canvas上下文");
      return "";
    }

    // 设置画布尺寸，每个像素用8x8像素来表示以确保清晰度
    const pixelSize = 8;
    canvas.width = dimensions.N * pixelSize;
    canvas.height = dimensions.M * pixelSize;

    // 绘制每个像素
    pixelData.forEach((row, rowIndex) => {
      row.forEach((cell, colIndex) => {
        if (cell) {
          // 使用颜色，外部单元格用白色
          const color = cell.isExternal ? "#FFFFFF" : cell.color;
          ctx.fillStyle = color;
          ctx.fillRect(colIndex * pixelSize, rowIndex * pixelSize, pixelSize, pixelSize);
        }
      });
    });

    // 转换为dataURL
    return canvas.toDataURL("image/png");
  };

  const processFile = (file: File) => {
    // 检查文件类型
    const fileExtension = file.name.split(".").pop()?.toLowerCase();

    if (fileExtension === "csv") {
      // 处理CSV文件
      console.log("正在导入CSV文件...");
      importCsvData(file)
        .then(({ mappedPixelData: importedPixels, gridDimensions: importedDimensions }) => {
          console.log(`成功导入CSV文件: ${importedDimensions.N}x${importedDimensions.M}`);

          // 设置导入的数据
          mappedPixelData.value = importedPixels;
          gridDimensions.value = importedDimensions;
          originalImageSrc.value = null; // CSV导入时没有原始图片

          // 计算颜色统计
          const colorCountsMap: {
            [key: string]: { count: number; color: string };
          } = {};
          let totalCount = 0;

          importedPixels.forEach((row) => {
            row.forEach((cell) => {
              if (cell && !cell.isExternal) {
                const colorKey = cell.color.toUpperCase();
                if (colorCountsMap[colorKey]) {
                  colorCountsMap[colorKey].count++;
                } else {
                  colorCountsMap[colorKey] = {
                    count: 1,
                    color: cell.color,
                  };
                }
                totalCount++;
              }
            });
          });

          colorCounts.value = colorCountsMap;
          totalBeadCount.value = totalCount;
          initialGridColorKeys.value = new Set(Object.keys(colorCountsMap));

          // 根据mappedPixelData生成合成的originalImageSrc
          const syntheticImageSrc = generateSyntheticImageFromPixelData(
            importedPixels,
            importedDimensions,
          );

          skipCsvPreviewRemap = originalImageSrc.value !== syntheticImageSrc;
          originalImageSrc.value = syntheticImageSrc;

          // 重置状态
          isManualColoringMode.value = false;
          selectedColor.value = null;
          isEraseMode.value = false;

          // 设置格子数量为导入的尺寸，避免重新映射时尺寸被修改
          granularity.value = importedDimensions.N;
          granularityInput.value = importedDimensions.N.toString();

          alert(
            `成功导入CSV文件！图纸尺寸：${importedDimensions.N}x${importedDimensions.M}，共使用${Object.keys(colorCountsMap).length}种颜色。`,
          );
        })
        .catch((error) => {
          console.error("CSV导入失败:", error);
          alert(`CSV导入失败：${error.message}`);
        });
    } else {
      // 处理图片文件 - 先打开裁剪弹窗
      const reader = new FileReader();
      reader.onload = (e) => {
        const result = e.target?.result as string;
        // 打开裁剪弹窗，而不是直接设置图片
        cropperImageSrc.value = result;
        isCropperOpen.value = true;
      };
      reader.onerror = () => {
        console.error("文件读取失败");
        alert("无法读取文件。");
        initialGridColorKeys.value = new Set(); // ++ 重置初始键 ++
      };
      reader.readAsDataURL(file);
    }
  };

  // 处理裁剪确认
  const handleCropConfirm = (croppedImageSrc: string) => {
    originalImageSrc.value = croppedImageSrc;
    mappedPixelData.value = null;
    gridDimensions.value = null;
    colorCounts.value = null;
    totalBeadCount.value = 0;
    initialGridColorKeys.value = new Set(); // ++ 重置初始键 ++
    // ++ 重置横轴格子数量为默认值 ++
    const defaultGranularity = 60;
    granularity.value = defaultGranularity;
    granularityInput.value = defaultGranularity.toString();
    remapTrigger.value++; // Trigger full remap for new image

    // 关闭裁剪弹窗
    isCropperOpen.value = false;
    cropperImageSrc.value = "";

    // ++ Reset manual coloring mode when a new file is processed ++
    isManualColoringMode.value = false;
    selectedColor.value = null;
    isEraseMode.value = false;
  };

  // 处理裁剪取消
  const handleCropCancel = () => {
    isCropperOpen.value = false;
    cropperImageSrc.value = "";
  };

  // 处理一键擦除模式切换
  const handleEraseToggle = () => {
    // 确保在手动上色模式下才能使用擦除功能
    if (!isManualColoringMode.value) {
      return;
    }

    // 如果当前在颜色替换模式，先退出替换模式
    if (colorReplaceState.value.isActive) {
      colorReplaceState.value = {
        isActive: false,
        step: "select-source",
      };
      highlightColorKey.value = null;
    }

    isEraseMode.value = !isEraseMode.value;
    // 如果开启擦除模式，取消选中的颜色
    if (!isEraseMode.value) {
      selectedColor.value = null;
    }
  };

  // ++ 新增：处理输入框变化的函数 ++
  const handleGranularityInputChange = (event: Event) => {
    granularityInput.value = (event.target as HTMLInputElement).value;
  };

  // ++ 添加：处理相似度输入框变化的函数 ++
  const handleSimilarityThresholdInputChange = (event: Event) => {
    similarityThresholdInput.value = (event.target as HTMLInputElement).value;
  };

  // ++ 修改：处理确认按钮点击的函数，同时处理两个参数 ++
  const handleConfirmParameters = () => {
    // 处理格子数
    const minGranularity = 10;
    const maxGranularity = 300;
    let newGranularity = parseInt(granularityInput.value, 10);

    if (isNaN(newGranularity) || newGranularity < minGranularity) {
      newGranularity = minGranularity;
    } else if (newGranularity > maxGranularity) {
      newGranularity = maxGranularity;
    }

    // 处理相似度阈值
    const minSimilarity = 0;
    const maxSimilarity = 100;
    let newSimilarity = parseInt(similarityThresholdInput.value, 10);

    if (isNaN(newSimilarity) || newSimilarity < minSimilarity) {
      newSimilarity = minSimilarity;
    } else if (newSimilarity > maxSimilarity) {
      newSimilarity = maxSimilarity;
    }

    // 检查值是否有变化
    const granularityChanged = newGranularity !== granularity.value;
    const similarityChanged = newSimilarity !== similarityThreshold.value;

    if (granularityChanged) {
      console.log(`Confirming new granularity: ${newGranularity}`);
      granularity.value = newGranularity;
    }

    if (similarityChanged) {
      console.log(`Confirming new similarity threshold: ${newSimilarity}`);
      similarityThreshold.value = newSimilarity;
    }

    // 只有在有值变化时才触发重映射
    if (granularityChanged || similarityChanged) {
      remapTrigger.value++;
      // 退出手动上色模式
      isManualColoringMode.value = false;
      selectedColor.value = null;
    }

    // 始终同步输入框的值
    granularityInput.value = newGranularity.toString();
    similarityThresholdInput.value = newSimilarity.toString();
  };

  // 添加像素化模式切换处理函数
  const handlePixelationModeChange = (event: Event) => {
    const newMode = (event.target as HTMLInputElement).value as PixelationMode;
    if (Object.values(PixelationMode).includes(newMode)) {
      pixelationMode.value = newMode;
      remapTrigger.value++; // 触发重新映射
      isManualColoringMode.value = false; // 退出手动模式
      selectedColor.value = null;
    } else {
      console.warn(`无效的像素化模式: ${newMode}`);
    }
  };

  // 修改pixelateImage函数接收模式参数
  const pixelateImage = (
    imageSrc: string,
    detailLevel: number,
    threshold: number,
    currentPalette: PaletteColor[],
    mode: PixelationMode,
  ) => {
    console.log(
      `Attempting to pixelate with detail: ${detailLevel}, threshold: ${threshold}, mode: ${mode}`,
    );
    const originalCanvas = originalCanvasRef.value;
    const pixelatedCanvas = canvasHandle.current;

    if (!originalCanvas || !pixelatedCanvas) {
      console.error("Canvas ref(s) not available.");
      return;
    }
    const originalCtx = originalCanvas.getContext("2d", {
      willReadFrequently: true,
    });
    const pixelatedCtx = pixelatedCanvas.getContext("2d");
    if (!originalCtx || !pixelatedCtx) {
      console.error("Canvas context(s) not found.");
      return;
    }
    console.log("Canvas contexts obtained.");

    if (currentPalette.length === 0) {
      console.error(
        "Cannot pixelate: The selected color palette is empty (likely due to exclusions).",
      );
      alert(
        "错误：当前可用颜色板为空（可能所有颜色都被排除了），无法处理图像。请尝试恢复部分颜色。",
      );
      // Clear previous results visually
      pixelatedCtx.clearRect(0, 0, pixelatedCanvas.width, pixelatedCanvas.height);
      mappedPixelData.value = null;
      gridDimensions.value = null;
      // Keep colorCounts potentially showing the last valid counts? Or clear them too?
      // setColorCounts(null); // Decide if clearing counts is desired when palette is empty
      // setTotalBeadCount(0);
      return; // Stop processing
    }
    const t1FallbackColor =
      currentPalette.find((p) => p.key === "T1") ||
      currentPalette.find((p) => p.hex.toUpperCase() === "#FFFFFF") ||
      currentPalette[0]; // 使用第一个可用颜色作为备用
    console.log("Using fallback color for empty cells:", t1FallbackColor);

    const img = new window.Image();

    img.onerror = (error: Event | string) => {
      console.error("Image loading failed:", error);
      alert("无法加载图片。");
      originalImageSrc.value = null;
      mappedPixelData.value = null;
      gridDimensions.value = null;
      colorCounts.value = null;
      initialGridColorKeys.value = new Set();
    };

    img.onload = () => {
      console.log("Image loaded successfully.");
      const aspectRatio = img.height / img.width;
      const N = detailLevel;
      const M = Math.max(1, Math.round(N * aspectRatio));
      if (N <= 0 || M <= 0) {
        console.error("Invalid grid dimensions:", { N, M });
        return;
      }
      console.log(`Grid size: ${N}x${M}`);

      // 动态调整画布尺寸：当格子数量大于100时，增加画布尺寸以保持每个格子的可见性
      const baseWidth = 500;
      const minCellSize = 4; // 每个格子的最小尺寸（像素）
      const recommendedCellSize = 6; // 推荐的格子尺寸（像素）

      let outputWidth = baseWidth;

      // 如果格子数量大于100，计算需要的画布宽度
      if (N > 100) {
        const requiredWidthForMinSize = N * minCellSize;
        const requiredWidthForRecommendedSize = N * recommendedCellSize;

        // 使用推荐尺寸，但不超过屏幕宽度的90%（最大1200px）
        const maxWidth = Math.min(1200, window.innerWidth * 0.9);
        outputWidth = Math.min(maxWidth, Math.max(baseWidth, requiredWidthForRecommendedSize));

        // 确保不小于最小要求
        outputWidth = Math.max(outputWidth, requiredWidthForMinSize);

        console.log(
          `Large grid detected (${N} columns). Adjusted canvas width from ${baseWidth} to ${outputWidth}px (cell size: ${Math.round(outputWidth / N)}px)`,
        );
      }

      const outputHeight = Math.round(outputWidth * aspectRatio);

      // 在控制台提示用户画布尺寸变化
      if (N > 100) {
        console.log(
          `💡 由于格子数量较多 (${N}x${M})，画布已自动放大以保持清晰度。可以使用水平滚动查看完整图像。`,
        );
      }
      originalCanvas.width = img.width;
      originalCanvas.height = img.height;
      pixelatedCanvas.width = outputWidth;
      pixelatedCanvas.height = outputHeight;
      console.log(
        `Canvas dimensions: Original ${img.width}x${img.height}, Output ${outputWidth}x${outputHeight}`,
      );

      originalCtx.drawImage(img, 0, 0, img.width, img.height);
      console.log("Original image drawn.");

      // 1. 使用calculatePixelGrid进行初始颜色映射
      console.log("Starting initial color mapping using calculatePixelGrid...");
      const initialMappedData = calculatePixelGrid(
        originalCtx,
        img.width,
        img.height,
        N,
        M,
        currentPalette,
        mode,
        t1FallbackColor,
      );
      console.log(
        `Initial data mapping complete using mode ${mode}. Starting global color merging...`,
      );

      // --- 新的全局颜色合并逻辑 ---
      const keyToRgbMap = new Map<string, RgbColor>();
      const keyToColorDataMap = new Map<string, PaletteColor>();
      currentPalette.forEach((p) => {
        keyToRgbMap.set(p.key, p.rgb);
        keyToColorDataMap.set(p.key, p);
      });

      // 2. 统计初始颜色数量
      const initialColorCounts: { [key: string]: number } = {};
      initialMappedData.flat().forEach((cell) => {
        if (cell && cell.key && !cell.isExternal && cell.key !== TRANSPARENT_KEY) {
          initialColorCounts[cell.key] = (initialColorCounts[cell.key] || 0) + 1;
        }
      });
      console.log("Initial color counts:", initialColorCounts);

      // 3. 创建一个颜色排序列表，按出现频率从高到低排序
      const colorsByFrequency = Object.entries(initialColorCounts)
        .sort((a, b) => b[1] - a[1]) // 按频率降序排序
        .map((entry) => entry[0]); // 只保留颜色键

      if (colorsByFrequency.length === 0) {
        console.log("No non-background colors found! Skipping merging.");
      }

      console.log("Colors sorted by frequency:", colorsByFrequency);

      // 4. 复制初始数据，准备合并
      const mergedData: MappedPixel[][] = initialMappedData.map((row) =>
        row.map((cell) => ({ ...cell, isExternal: cell.isExternal ?? false })),
      );

      // 5. 处理相似颜色合并
      const similarityThresholdValue = threshold;

      // 已被合并（替换）的颜色集合
      const replacedColors = new Set<string>();

      // 对每个颜色按频率从高到低处理
      for (let i = 0; i < colorsByFrequency.length; i++) {
        const currentKey = colorsByFrequency[i];

        // 如果当前颜色已经被合并到更频繁的颜色中，跳过
        if (replacedColors.has(currentKey)) continue;

        const currentRgb = keyToRgbMap.get(currentKey);
        if (!currentRgb) {
          console.warn(`RGB not found for key ${currentKey}. Skipping.`);
          continue;
        }

        // 检查剩余的低频颜色
        for (let j = i + 1; j < colorsByFrequency.length; j++) {
          const lowerFreqKey = colorsByFrequency[j];

          // 如果低频颜色已被替换，跳过
          if (replacedColors.has(lowerFreqKey)) continue;

          const lowerFreqRgb = keyToRgbMap.get(lowerFreqKey);
          if (!lowerFreqRgb) {
            console.warn(`RGB not found for key ${lowerFreqKey}. Skipping.`);
            continue;
          }

          // 计算颜色距离
          const dist = colorDistance(currentRgb, lowerFreqRgb);

          // 如果距离小于阈值，将低频颜色替换为高频颜色
          if (dist < similarityThresholdValue) {
            console.log(
              `Merging color ${lowerFreqKey} into ${currentKey} (Distance: ${dist.toFixed(2)})`,
            );

            // 标记这个颜色已被替换
            replacedColors.add(lowerFreqKey);

            // 替换所有使用这个低频颜色的单元格
            for (let r = 0; r < M; r++) {
              for (let c = 0; c < N; c++) {
                if (mergedData[r][c].key === lowerFreqKey) {
                  const colorData = keyToColorDataMap.get(currentKey);
                  if (colorData) {
                    mergedData[r][c] = {
                      key: currentKey,
                      color: colorData.hex,
                      isExternal: false,
                    };
                  }
                }
              }
            }
          }
        }
      }

      if (replacedColors.size > 0) {
        console.log(
          `Merged ${replacedColors.size} less frequent similar colors into more frequent ones.`,
        );
      } else {
        console.log("No colors were similar enough to merge.");
      }
      // --- 结束新的全局颜色合并逻辑 ---

      // --- 绘制和状态更新 ---
      if (canvasHandle.current) {
        mappedPixelData.value = mergedData;
        gridDimensions.value = { N, M };

        const counts: { [key: string]: { count: number; color: string } } = {};
        let totalCount = 0;
        mergedData.flat().forEach((cell) => {
          if (cell && cell.key && !cell.isExternal) {
            // 使用hex值作为统计键值，而不是色号
            const hexKey = cell.color;
            if (!counts[hexKey]) {
              counts[hexKey] = { count: 0, color: cell.color };
            }
            counts[hexKey].count++;
            totalCount++;
          }
        });
        colorCounts.value = counts;
        totalBeadCount.value = totalCount;
        initialGridColorKeys.value = new Set(Object.keys(counts));
        console.log("Color counts updated based on merged data (after merging):", counts);
        console.log("Total bead count (total beads):", totalCount);
        console.log("Stored initial grid color keys:", Object.keys(counts));
      } else {
        console.error("Pixelated canvas ref is null, skipping draw call in pixelateImage.");
      }
    }; // 正确闭合 img.onload 函数

    console.log("Setting image source...");
    img.src = imageSrc;
    isManualColoringMode.value = false;
    selectedColor.value = null;
  }; // 正确闭合 pixelateImage 函数

  // 修改useEffect中的pixelateImage调用，加入模式参数
  watch([() => originalImageSrc.value, () => granularity.value, () => similarityThreshold.value, () => customPaletteSelections.value, () => paletteSize.value, () => pixelationMode.value, () => remapTrigger.value], (_values, _previous, onCleanup) => {
    if (skipCsvPreviewRemap) {
      skipCsvPreviewRemap = false;
      return;
    }
    if (originalImageSrc.value && activeBeadPalette.value.length > 0) {
      const timeoutId = setTimeout(() => {
        if (
          originalImageSrc.value &&
          originalCanvasRef.value &&
          canvasHandle.current &&
          activeBeadPalette.value.length > 0
        ) {
          console.log(
            "useEffect triggered: Processing image due to src, granularity, threshold, palette selection, mode or remap trigger.",
          );
          pixelateImage(
            originalImageSrc.value,
            granularity.value,
            similarityThreshold.value,
            activeBeadPalette.value,
            pixelationMode.value,
          );
        } else {
          console.warn(
            "useEffect check failed inside timeout: Refs or active palette not ready/empty.",
          );
        }
      }, 50);
      onCleanup(() => clearTimeout(timeoutId));
    } else if (originalImageSrc.value && activeBeadPalette.value.length === 0) {
      console.warn(
        "Image selected, but the active palette is empty after exclusions. Cannot process. Clearing preview.",
      );
      const pixelatedCanvas = canvasHandle.current;
      const pixelatedCtx = pixelatedCanvas?.getContext("2d");
      if (pixelatedCtx && pixelatedCanvas) {
        pixelatedCtx.clearRect(0, 0, pixelatedCanvas.width, pixelatedCanvas.height);
        // Draw a message on the canvas?
        pixelatedCtx.fillStyle = "#6b7280"; // gray-500
        pixelatedCtx.font = "16px sans-serif";
        pixelatedCtx.textAlign = "center";
        pixelatedCtx.fillText(
          "无可用颜色，请恢复部分排除的颜色",
          pixelatedCanvas.width / 2,
          pixelatedCanvas.height / 2,
        );
      }
      mappedPixelData.value = null;
      gridDimensions.value = null;
      // Keep colorCounts to allow user to un-exclude colors
      // setColorCounts(null);
      // setTotalBeadCount(0);
    }
  }, { immediate: true, flush: 'post' });

  // 确保文件输入框引用在组件挂载后正确设置
  let fileInputTimer: ReturnType<typeof setTimeout> | null = null;
  onMounted(() => {
    // 延迟执行，确保DOM完全渲染
    fileInputTimer = setTimeout(() => {
      if (!fileInputRef.value) {
        console.warn("文件输入框引用在组件挂载后仍为null，这可能会导致上传功能异常");
      }
    }, 100);

  });
  onUnmounted(() => {
    if (fileInputTimer) clearTimeout(fileInputTimer);
  });

  // 设置组件挂载状态
  onMounted(() => {
    isMounted.value = true;
  });

  // 添加URL重定向检查
  onMounted(() => {
    // 检查是否在浏览器环境中
    if (typeof window !== "undefined") {
      const currentUrl = window.location.href;
      const currentHostname = window.location.hostname;
      const targetDomain = import.meta.env.VITE_OFFICIAL_DOMAIN;
      if (!targetDomain) return;

      // 排除localhost和127.0.0.1等本地开发环境，以及Cloudflare Pages域名
      const isLocalhost =
        currentHostname === "localhost" ||
        currentHostname === "127.0.0.1" ||
        currentHostname.startsWith("192.168.") ||
        currentHostname.startsWith("10.") ||
        currentHostname.endsWith(".local") ||
        currentHostname.endsWith(".pages.dev");

      // 检查当前URL是否不是目标域名，且不是本地开发环境
      if (!currentUrl.startsWith(targetDomain) && !isLocalhost) {
        console.log(`当前URL: ${currentUrl}`);
        console.log(`目标URL: ${targetDomain}`);
        console.log("正在重定向到官方域名...");

        // 保留当前路径和查询参数
        const currentPath = window.location.pathname;
        const currentSearch = window.location.search;
        const currentHash = window.location.hash;

        // 构建完整的目标URL
        let redirectUrl = targetDomain;

        // 如果不是根路径，添加路径
        if (currentPath && currentPath !== "/") {
          redirectUrl = redirectUrl.replace(/\/$/, "") + currentPath;
        }

        // 添加查询参数和哈希
        redirectUrl += currentSearch + currentHash;

        // 执行重定向
        window.location.replace(redirectUrl);
      } else if (isLocalhost) {
        console.log(`检测到本地开发环境 (${currentHostname})，跳过重定向`);
      }
    }
  }); // 只在组件首次挂载时执行

  // --- Download function (ensure filename includes palette) ---
  const handleDownloadRequest = (options?: GridDownloadOptions) => {
    // 调用移动到utils/imageDownloader.ts中的downloadImage函数
    void downloadImage({
      mappedPixelData: mappedPixelData.value,
      gridDimensions: gridDimensions.value,
      colorCounts: colorCounts.value,
      totalBeadCount: totalBeadCount.value,
      options: options || downloadOptions.value,
      activeBeadPalette: activeBeadPalette.value,
      selectedColorSystem: selectedColorSystem.value,
    });
  };

  // --- Handler to toggle color exclusion ---
  const handleToggleExcludeColor = (hexKey: string) => {
    const currentExcluded = excludedColorKeys.value;
    const isExcluding = !currentExcluded.has(hexKey);

    if (isExcluding) {
      console.log(`---------\nAttempting to EXCLUDE color: ${hexKey}`);

      // --- 确保初始颜色键已记录 ---
      if (initialGridColorKeys.value.size === 0) {
        console.error("Cannot exclude color: Initial grid color keys not yet calculated.");
        alert("无法排除颜色，初始颜色数据尚未准备好，请稍候。");
        return;
      }
      console.log("Initial Grid Hex Keys:", Array.from(initialGridColorKeys.value));
      console.log("Currently Excluded Hex Keys (before this op):", Array.from(currentExcluded));

      const nextExcludedKeys = new Set(currentExcluded);
      nextExcludedKeys.add(hexKey);

      // --- 使用初始颜色键进行重映射目标逻辑 ---
      // 1. 从初始网格颜色集合开始（hex值）
      const potentialRemapHexKeys = new Set(initialGridColorKeys.value);
      console.log("Step 1: Potential Hex Keys (from initial):", Array.from(potentialRemapHexKeys));

      // 2. 移除当前要排除的hex键
      potentialRemapHexKeys.delete(hexKey);
      console.log(
        `Step 2: Potential Hex Keys (after removing ${hexKey}):`,
        Array.from(potentialRemapHexKeys),
      );

      // 3. 移除任何*其他*当前也被排除的hex键
      currentExcluded.forEach((excludedHexKey) => {
        potentialRemapHexKeys.delete(excludedHexKey);
      });
      console.log(
        "Step 3: Potential Hex Keys (after removing other current exclusions):",
        Array.from(potentialRemapHexKeys),
      );

      // 4. 基于剩余的hex值创建重映射调色板
      const remapTargetPalette = availableBeadPalette.value.filter((color) =>
        potentialRemapHexKeys.has(color.hex.toUpperCase()),
      );
      const remapTargetHexKeys = remapTargetPalette.map((p) => p.hex.toUpperCase());
      console.log("Step 4: Remap Target Palette Hex Keys:", remapTargetHexKeys);

      // 5. *** 关键检查 ***：如果在考虑所有排除项后，没有*初始*颜色可供映射，则阻止此次排除
      if (remapTargetPalette.length === 0) {
        console.warn(
          `Cannot exclude color '${hexKey}'. No other valid colors from the initial grid remain after considering all current exclusions.`,
        );
        alert(
          `无法排除颜色 ${hexKey}，因为图中最初存在的其他可用颜色也已被排除。请先恢复部分其他颜色。`,
        );
        console.log("---------");
        return; // 停止排除过程
      }
      console.log(
        `Remapping target palette (based on initial grid colors minus all exclusions) contains ${remapTargetPalette.length} colors.`,
      );

      // 查找被排除颜色的RGB值用于重映射
      const excludedColorData = fullBeadPalette.find((p) => p.hex.toUpperCase() === hexKey);
      // 检查排除颜色的数据是否存在
      if (!excludedColorData || !mappedPixelData.value || !gridDimensions.value) {
        console.error("Cannot exclude color: Missing data for remapping.");
        alert("无法排除颜色，缺少必要数据。");
        console.log("---------");
        return;
      }

      console.log(`Remapping cells currently using excluded color: ${hexKey}`);
      // 仅在需要重映射时创建深拷贝
      const newMappedData = mappedPixelData.value.map((row) => row.map((cell) => ({ ...cell })));
      let remappedCount = 0;
      const { N, M } = gridDimensions.value;
      let firstReplacementHex: string | null = null;

      for (let j = 0; j < M; j++) {
        for (let i = 0; i < N; i++) {
          const cell = newMappedData[j]?.[i];
          // 此条件正确地仅针对具有排除hex值的单元格
          if (cell && !cell.isExternal && cell.color.toUpperCase() === hexKey) {
            // *** 使用派生的 remapTargetPalette 查找最接近的颜色 ***
            const replacementColor = findClosestPaletteColor(
              excludedColorData.rgb,
              remapTargetPalette,
            );
            if (!firstReplacementHex) firstReplacementHex = replacementColor.hex;
            newMappedData[j][i] = {
              ...cell,
              key: replacementColor.key,
              color: replacementColor.hex,
            };
            remappedCount++;
          }
        }
      }
      console.log(
        `Remapped ${remappedCount} cells. First replacement hex found was: ${firstReplacementHex || "N/A"}`,
      );

      // 同时更新状态
      excludedColorKeys.value = nextExcludedKeys; // 应用此颜色的排除
      mappedPixelData.value = newMappedData; // 使用重映射的数据更新

      // 基于*新*映射数据重新计算计数（以hex为键）
      const newCounts: { [hexKey: string]: { count: number; color: string } } = {};
      let newTotalCount = 0;
      newMappedData.flat().forEach((cell) => {
        if (cell && cell.color && !cell.isExternal) {
          const cellHex = cell.color.toUpperCase();
          if (!newCounts[cellHex]) {
            newCounts[cellHex] = { count: 0, color: cellHex };
          }
          newCounts[cellHex].count++;
          newTotalCount++;
        }
      });
      colorCounts.value = newCounts;
      totalBeadCount.value = newTotalCount;
      console.log("State updated after exclusion and local remap based on initial grid colors.");
      console.log("---------");

      // ++ 在更新状态后，重新绘制 Canvas ++
      if (canvasHandle.current && gridDimensions.value) {
        mappedPixelData.value = newMappedData;
        // 不要调用 setGridDimensions，因为颜色排除不需要改变网格尺寸
      } else {
        console.error(
          "Canvas ref or grid dimensions missing, skipping draw call in handleToggleExcludeColor.",
        );
      }
    } else {
      // --- Re-including ---
      console.log(`---------\nAttempting to RE-INCLUDE color: ${hexKey}`);
      console.log(`Re-including color: ${hexKey}. Triggering full remap.`);
      const nextExcludedKeys = new Set(currentExcluded);
      nextExcludedKeys.delete(hexKey);
      excludedColorKeys.value = nextExcludedKeys;
      // 此处无需重置 initialGridColorKeys，完全重映射会通过 pixelateImage 重新计算它
      remapTrigger.value++; // *** KEPT setRemapTrigger here for re-inclusion ***
      console.log("---------");
    }
    // ++ Exit manual mode if colors are excluded/included ++
    isManualColoringMode.value = false;
    selectedColor.value = null;
  };

  // 一键去背景：识别边缘主色并洪水填充去除
  const handleAutoRemoveBackground = () => {
    if (!mappedPixelData.value || !gridDimensions.value) {
      alert("请先生成图纸后再使用一键去背景。");
      return;
    }

    const { N, M } = gridDimensions.value;
    const pixelData = mappedPixelData.value;
    const borderCounts = new Map<string, number>();

    const countBorderCell = (row: number, col: number) => {
      const cell = pixelData[row]?.[col];
      if (!cell || cell.isExternal || cell.key === TRANSPARENT_KEY) return;
      borderCounts.set(cell.key, (borderCounts.get(cell.key) || 0) + 1);
    };

    for (let col = 0; col < N; col++) {
      countBorderCell(0, col);
      if (M > 1) countBorderCell(M - 1, col);
    }
    for (let row = 1; row < M - 1; row++) {
      countBorderCell(row, 0);
      if (N > 1) countBorderCell(row, N - 1);
    }

    if (borderCounts.size === 0) {
      alert("边缘没有可识别的背景颜色。");
      return;
    }

    let targetKey = "";
    let maxCount = -1;
    borderCounts.forEach((count, key) => {
      if (count > maxCount) {
        maxCount = count;
        targetKey = key;
      }
    });

    const newPixelData = mappedPixelData.value.map((row) => row.map((cell) => ({ ...cell })));
    const visited = Array(M)
      .fill(null)
      .map(() => Array(N).fill(false));
    const stack: { row: number; col: number }[] = [];

    const pushIfTarget = (row: number, col: number) => {
      if (row < 0 || row >= M || col < 0 || col >= N || visited[row][col]) {
        return;
      }
      const cell = newPixelData[row][col];
      if (!cell || cell.isExternal || cell.key !== targetKey) return;
      visited[row][col] = true;
      stack.push({ row, col });
    };

    for (let col = 0; col < N; col++) {
      pushIfTarget(0, col);
      if (M > 1) pushIfTarget(M - 1, col);
    }
    for (let row = 1; row < M - 1; row++) {
      pushIfTarget(row, 0);
      if (N > 1) pushIfTarget(row, N - 1);
    }

    if (stack.length === 0) {
      alert("未找到可去除的背景区域。");
      return;
    }

    while (stack.length > 0) {
      const { row, col } = stack.pop()!;
      newPixelData[row][col] = { ...transparentColorData };
      pushIfTarget(row - 1, col);
      pushIfTarget(row + 1, col);
      pushIfTarget(row, col - 1);
      pushIfTarget(row, col + 1);
    }

    mappedPixelData.value = newPixelData;

    const newColorCounts: {
      [hexKey: string]: { count: number; color: string };
    } = {};
    let newTotalCount = 0;
    newPixelData.flat().forEach((cell) => {
      if (cell && !cell.isExternal && cell.key !== TRANSPARENT_KEY) {
        const cellHex = cell.color.toUpperCase();
        if (!newColorCounts[cellHex]) {
          newColorCounts[cellHex] = {
            count: 0,
            color: cellHex,
          };
        }
        newColorCounts[cellHex].count++;
        newTotalCount++;
      }
    });

    colorCounts.value = newColorCounts;
    totalBeadCount.value = newTotalCount;
    initialGridColorKeys.value = new Set(Object.keys(newColorCounts));
  };

  // --- Tooltip Logic ---

  // --- Canvas Interaction ---

  // 洪水填充擦除函数
  const floodFillErase = (startRow: number, startCol: number, targetKey: string) => {
    if (!mappedPixelData.value || !gridDimensions.value) return;

    const { N, M } = gridDimensions.value;
    const newPixelData = mappedPixelData.value.map((row) => row.map((cell) => ({ ...cell })));
    const visited = Array(M)
      .fill(null)
      .map(() => Array(N).fill(false));

    // 使用栈实现非递归洪水填充
    const stack = [{ row: startRow, col: startCol }];

    while (stack.length > 0) {
      const { row, col } = stack.pop()!;

      // 检查边界
      if (row < 0 || row >= M || col < 0 || col >= N || visited[row][col]) {
        continue;
      }

      const currentCell = newPixelData[row][col];

      // 检查是否是目标颜色且不是外部区域
      if (!currentCell || currentCell.isExternal || currentCell.key !== targetKey) {
        continue;
      }

      // 标记为已访问
      visited[row][col] = true;

      // 擦除当前像素（设为透明）
      newPixelData[row][col] = { ...transparentColorData };

      // 添加相邻像素到栈中
      stack.push(
        { row: row - 1, col }, // 上
        { row: row + 1, col }, // 下
        { row, col: col - 1 }, // 左
        { row, col: col + 1 }, // 右
      );
    }

    // 更新状态
    mappedPixelData.value = newPixelData;

    // 重新计算颜色统计
    if (colorCounts.value) {
      const newColorCounts: {
        [hexKey: string]: { count: number; color: string };
      } = {};
      let newTotalCount = 0;

      newPixelData.flat().forEach((cell) => {
        if (cell && !cell.isExternal && cell.key !== TRANSPARENT_KEY) {
          const cellHex = cell.color.toUpperCase();
          if (!newColorCounts[cellHex]) {
            newColorCounts[cellHex] = {
              count: 0,
              color: cellHex,
            };
          }
          newColorCounts[cellHex].count++;
          newTotalCount++;
        }
      });

      colorCounts.value = newColorCounts;
      totalBeadCount.value = newTotalCount;
    }
  };

  // ++ Re-introduce the combined interaction handler ++
  const handleCanvasInteraction = (
    clientX: number,
    clientY: number,
    pageX: number,
    pageY: number,
    isClick: boolean = false,
    isTouchEnd: boolean = false,
  ) => {
    // 如果是触摸结束或鼠标离开事件，隐藏提示
    if (isTouchEnd) {
      tooltipData.value = null;
      return;
    }

    const canvas = canvasHandle.current;
    if (!canvas || !mappedPixelData.value || !gridDimensions.value) {
      tooltipData.value = null;
      return;
    }

    const rect = canvas.getBoundingClientRect();
    const scaleX = canvas.width / rect.width;
    const scaleY = canvas.height / rect.height;
    const canvasX = (clientX - rect.left) * scaleX;
    const canvasY = (clientY - rect.top) * scaleY;

    const { N, M } = gridDimensions.value;
    const cellWidthOutput = canvas.width / N;
    const cellHeightOutput = canvas.height / M;

    const i = Math.floor(canvasX / cellWidthOutput);
    const j = Math.floor(canvasY / cellHeightOutput);

    if (i >= 0 && i < N && j >= 0 && j < M) {
      const cellData = mappedPixelData.value[j][i];

      // 颜色替换模式逻辑 - 选择源颜色
      if (isClick && colorReplaceState.value.isActive && colorReplaceState.value.step === "select-source") {
        if (cellData && !cellData.isExternal && cellData.key && cellData.key !== TRANSPARENT_KEY) {
          // 执行选择源颜色
          handleCanvasColorSelect({
            key: cellData.key,
            color: cellData.color,
          });
          tooltipData.value = null;
        }
        return;
      }

      // 一键擦除模式逻辑
      if (isClick && isEraseMode.value) {
        if (cellData && !cellData.isExternal && cellData.key && cellData.key !== TRANSPARENT_KEY) {
          // 执行洪水填充擦除
          floodFillErase(j, i, cellData.key);
          isEraseMode.value = false; // 擦除完成后退出擦除模式
          tooltipData.value = null;
        }
        return;
      }

      // Manual Coloring Logic - 保持原有的上色逻辑
      if (isClick && isManualColoringMode.value && selectedColor.value) {
        // 手动上色模式逻辑保持不变
        // ...现有代码...
        const newPixelData = mappedPixelData.value.map((row) => row.map((cell) => ({ ...cell })));
        const currentCell = newPixelData[j]?.[i];

        if (!currentCell) return;

        const previousKey = currentCell.key;
        const wasExternal = currentCell.isExternal;

        let newCellData: MappedPixel;

        if (selectedColor.value.key === TRANSPARENT_KEY) {
          newCellData = { ...transparentColorData };
        } else {
          newCellData = { ...selectedColor.value, isExternal: false };
        }

        // Only update if state changes
        if (newCellData.key !== previousKey || newCellData.isExternal !== wasExternal) {
          newPixelData[j][i] = newCellData;
          mappedPixelData.value = newPixelData;

          // Update color counts
          if (colorCounts.value) {
            const newColorCounts = { ...colorCounts.value };
            let newTotalCount = totalBeadCount.value;

            // 处理之前颜色的减少（使用hex值）
            if (!wasExternal && previousKey !== TRANSPARENT_KEY) {
              const previousHex = currentCell.color?.toUpperCase();
              if (previousHex && newColorCounts[previousHex]) {
                newColorCounts[previousHex].count--;
                if (newColorCounts[previousHex].count <= 0) {
                  delete newColorCounts[previousHex];
                }
                newTotalCount--;
              }
            }

            // 处理新颜色的增加（使用hex值）
            if (!newCellData.isExternal && newCellData.key !== TRANSPARENT_KEY) {
              const newHex = newCellData.color.toUpperCase();
              if (!newColorCounts[newHex]) {
                newColorCounts[newHex] = {
                  count: 0,
                  color: newHex,
                };
              }
              newColorCounts[newHex].count++;
              newTotalCount++;
            }

            colorCounts.value = newColorCounts;
            totalBeadCount.value = newTotalCount;
          }
        }

        // 上色操作后隐藏提示
        tooltipData.value = null;
      }
      // Tooltip Logic (非手动上色模式点击或悬停)
      else if (!isManualColoringMode.value) {
        // 只有单元格实际有内容（非背景/外部区域）才会显示提示
        if (cellData && !cellData.isExternal && cellData.key) {
          // 检查是否已经显示了提示框，并且是否点击的是同一个位置
          // 对于移动设备，位置可能有细微偏差，所以我们检查单元格索引而不是具体坐标
          if (tooltipData.value) {
            // 如果已经有提示框，计算当前提示框对应的格子的索引
            const tooltipRect = canvas.getBoundingClientRect();

            // 还原提示框位置为相对于canvas的坐标
            const prevX = tooltipData.value.x; // 页面X坐标
            const prevY = tooltipData.value.y; // 页面Y坐标

            // 转换为相对于canvas的坐标
            const prevCanvasX = (prevX - tooltipRect.left) * scaleX;
            const prevCanvasY = (prevY - tooltipRect.top) * scaleY;

            // 计算之前显示提示框位置对应的网格索引
            const prevCellI = Math.floor(prevCanvasX / cellWidthOutput);
            const prevCellJ = Math.floor(prevCanvasY / cellHeightOutput);

            // 如果点击的是同一个格子，则切换tooltip的显示/隐藏状态
            if (i === prevCellI && j === prevCellJ) {
              tooltipData.value = null; // 隐藏提示
              return;
            }
          }

          // 计算相对于main元素的位置
          const mainElement = mainRef.value;
          if (mainElement) {
            const mainRect = mainElement.getBoundingClientRect();
            // 计算相对于main元素的坐标
            const relativeX = pageX - mainRect.left - window.scrollX;
            const relativeY = pageY - mainRect.top - window.scrollY;

            // 如果是移动/悬停到一个新的有效格子，或者点击了不同的格子，则显示提示
            tooltipData.value = {
              x: relativeX,
              y: relativeY,
              key: cellData.key,
              color: cellData.color,
            };
          } else {
            // 如果没有找到main元素，使用原始坐标
            tooltipData.value = {
              x: pageX,
              y: pageY,
              key: cellData.key,
              color: cellData.color,
            };
          }
        } else {
          // 如果点击/悬停在外部区域或背景上，隐藏提示
          tooltipData.value = null;
        }
      }
    } else {
      // 如果点击/悬停在画布外部，隐藏提示
      tooltipData.value = null;
    }
  };

  // 处理自定义色板中单个颜色的选择变化
  const handleSelectionChange = (hexValue: string, isSelected: boolean) => {
    const normalizedHex = hexValue.toUpperCase();
    customPaletteSelections.value = {
      ...customPaletteSelections.value,
      [normalizedHex]: isSelected,
    };
    isCustomPalette.value = true;
  };

  // 保存自定义色板并应用
  const handleSaveCustomPalette = () => {
    savePaletteSelections(customPaletteSelections.value);
    isCustomPalette.value = true;
    isCustomPaletteEditorOpen.value = false;
    // 触发图像重新处理
    remapTrigger.value++;
    // 退出手动上色模式
    isManualColoringMode.value = false;
    selectedColor.value = null;
    isEraseMode.value = false;
  };

  // ++ 新增：导出自定义色板配置 ++
  const handleExportCustomPalette = () => {
    const selectedHexValues = Object.entries(customPaletteSelections.value)
      .filter(([, isSelected]) => isSelected)
      .map(([hexValue]) => hexValue);

    if (selectedHexValues.length === 0) {
      alert("当前没有选中的颜色，无法导出。");
      return;
    }

    // 导出格式：仅基于hex值
    const exportData = {
      version: "3.0", // 新版本号
      selectedHexValues: selectedHexValues,
      exportDate: new Date().toISOString(),
      totalColors: selectedHexValues.length,
    };

    const blob = new Blob([JSON.stringify(exportData, null, 2)], {
      type: "application/json",
    });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = "custom-perler-palette.json";
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    URL.revokeObjectURL(url);
  };

  // ++ 新增：处理导入的色板文件 ++
  const handleImportPaletteFile = (event: Event) => {
    const file = (event.target as HTMLInputElement).files?.[0];
    if (!file) return;

    const reader = new FileReader();
    reader.onload = (e) => {
      try {
        const content = e.target?.result as string;
        const data = JSON.parse(content);

        // 检查文件格式
        if (!Array.isArray(data.selectedHexValues)) {
          throw new Error("无效的文件格式：文件必须包含 'selectedHexValues' 数组。");
        }

        console.log("检测到基于hex值的色板文件");

        const importedHexValues = data.selectedHexValues as string[];
        const validHexValues: string[] = [];
        const invalidHexValues: string[] = [];

        // 验证hex值
        importedHexValues.forEach((hex) => {
          const normalizedHex = hex.toUpperCase();
          const colorData = fullBeadPalette.find(
            (color) => color.hex.toUpperCase() === normalizedHex,
          );
          if (colorData) {
            validHexValues.push(normalizedHex);
          } else {
            invalidHexValues.push(hex);
          }
        });

        if (invalidHexValues.length > 0) {
          console.warn("导入时发现无效的hex值:", invalidHexValues);
          alert(`导入完成，但以下颜色无效已被忽略：\n${invalidHexValues.join(", ")}`);
        }

        if (validHexValues.length === 0) {
          alert("导入的文件中不包含任何有效的颜色。");
          return;
        }

        console.log(`成功验证 ${validHexValues.length} 个有效的hex值`);

        // 基于有效的hex值创建新的selections对象
        const allHexValues = fullBeadPalette.map((color) => color.hex.toUpperCase());
        const newSelections = presetToSelections(allHexValues, validHexValues);
        customPaletteSelections.value = newSelections;
        isCustomPalette.value = true; // 标记为自定义
        alert(`成功导入 ${validHexValues.length} 个颜色！`);
      } catch (error) {
        console.error("导入色板配置失败:", error);
        alert(`导入失败: ${error instanceof Error ? error.message : "未知错误"}`);
      } finally {
        // 重置文件输入，以便可以再次导入相同的文件
        if (event.target) {
          (event.target as HTMLInputElement).value = "";
        }
      }
    };
    reader.onerror = () => {
      alert("读取文件失败。");
      // 重置文件输入
      if (event.target) {
        (event.target as HTMLInputElement).value = "";
      }
    };
    reader.readAsText(file);
  };

  // ++ 新增：触发导入文件选择 ++
  const triggerImportPalette = () => {
    importPaletteInputRef.value?.click();
  };

  // 新增：处理颜色高亮
  const handleHighlightColor = (colorHex: string) => {
    highlightColorKey.value = colorHex;
  };

  // 新增：高亮完成回调
  const handleHighlightComplete = () => {
    highlightColorKey.value = null;
  };

  // 新增：切换完整色板显示
  const handleToggleFullPalette = () => {
    showFullPalette.value = !showFullPalette.value;
  };

  // 新增：处理颜色选择，同时管理模式切换
  const handleColorSelect = (colorData: { key: string; color: string; isExternal?: boolean }) => {
    // 如果选择的是橡皮擦（透明色）且当前在颜色替换模式，退出替换模式
    if (colorData.key === TRANSPARENT_KEY && colorReplaceState.value.isActive) {
      colorReplaceState.value = {
        isActive: false,
        step: "select-source",
      };
      highlightColorKey.value = null;
    }

    // 选择任何颜色（包括橡皮擦）时，都应该退出一键擦除模式
    if (isEraseMode.value) {
      isEraseMode.value = false;
    }

    // 设置选中的颜色
    selectedColor.value = colorData;
  };

  // 新增：颜色替换相关处理函数
  const handleColorReplaceToggle = () => {
    if (colorReplaceState.value.isActive) {
      colorReplaceState.value = { isActive: false, step: "select-source" };
    } else {
        isEraseMode.value = false;
        selectedColor.value = null;
        colorReplaceState.value = { isActive: true, step: "select-source" };
    }
  };

  // 新增：处理从画布选择源颜色
  const handleCanvasColorSelect = (colorData: { key: string; color: string }) => {
    if (colorReplaceState.value.isActive && colorReplaceState.value.step === "select-source") {
      // 高亮显示选中的颜色
      highlightColorKey.value = colorData.color;
      // 进入第二步：选择目标颜色
      colorReplaceState.value = {
        isActive: true,
        step: "select-target",
        sourceColor: colorData,
      };
    }
  };

  // 新增：执行颜色替换
  const handleColorReplace = (
    sourceColor: { key: string; color: string },
    targetColor: { key: string; color: string },
  ) => {
    if (!mappedPixelData.value || !gridDimensions.value) return;

    const { N, M } = gridDimensions.value;
    const newPixelData = mappedPixelData.value.map((row) => row.map((cell) => ({ ...cell })));
    let replaceCount = 0;

    // 遍历所有像素，替换匹配的颜色
    for (let j = 0; j < M; j++) {
      for (let i = 0; i < N; i++) {
        const currentCell = newPixelData[j][i];
        if (
          currentCell &&
          !currentCell.isExternal &&
          currentCell.color.toUpperCase() === sourceColor.color.toUpperCase()
        ) {
          // 替换颜色
          newPixelData[j][i] = {
            key: targetColor.key,
            color: targetColor.color,
            isExternal: false,
          };
          replaceCount++;
        }
      }
    }

    if (replaceCount > 0) {
      // 更新像素数据
      mappedPixelData.value = newPixelData;

      // 重新计算颜色统计
      if (colorCounts.value) {
        const newColorCounts: {
          [hexKey: string]: { count: number; color: string };
        } = {};
        let newTotalCount = 0;

        newPixelData.flat().forEach((cell) => {
          if (cell && !cell.isExternal && cell.key !== TRANSPARENT_KEY) {
            const cellHex = cell.color.toUpperCase();
            if (!newColorCounts[cellHex]) {
              newColorCounts[cellHex] = {
                count: 0,
                color: cellHex,
              };
            }
            newColorCounts[cellHex].count++;
            newTotalCount++;
          }
        });

        colorCounts.value = newColorCounts;
        totalBeadCount.value = newTotalCount;
      }

      console.log(
        `颜色替换完成：将 ${replaceCount} 个 ${sourceColor.key} 替换为 ${targetColor.key}`,
      );
    }

    // 退出替换模式
    colorReplaceState.value = {
      isActive: false,
      step: "select-source",
    };

    // 清除高亮
    highlightColorKey.value = null;
  };

  // 生成完整色板数据（用户自定义色板中选中的所有颜色）
  const fullPaletteColors = computed(() => {
    const selectedColors: { key: string; color: string }[] = [];

    availableBeadPalette.value.forEach(({ hex: hexValue }) => {
      if (customPaletteSelections.value[hexValue.toUpperCase()]) {
        // 根据选择的色号系统获取显示的色号
        const displayKey = getColorKeyByHex(hexValue, selectedColorSystem.value);
        selectedColors.push({
          key: displayKey,
          color: hexValue,
        });
      }
    });

    // 使用色相排序而不是色号排序
    return sortColorsByHue(selectedColors);
  });

  
</script>

<template>
<div class="min-h-screen p-4 sm:p-6 flex flex-col items-center bg-linear-to-b from-gray-50 to-white dark:from-gray-800 dark:to-gray-900 font-(family-name:--font-geist-sans) overflow-x-hidden">
<header class="w-full md:max-w-4xl text-center mt-6 mb-8 sm:mt-8 sm:mb-10 relative overflow-hidden">
<div class="absolute top-0 left-0 w-48 h-48 bg-blue-100 dark:bg-blue-900 rounded-full opacity-30 dark:opacity-20 blur-3xl">
</div>
<div class="absolute bottom-0 right-0 w-48 h-48 bg-pink-100 dark:bg-pink-900 rounded-full opacity-30 dark:opacity-20 blur-3xl">
</div>
<div class="absolute top-0 right-0 grid grid-cols-5 gap-1 opacity-20 dark:opacity-10">
<template v-for='(_, i) in 25' :key='i'>
<div class="w-1.5 h-1.5 rounded-full bg-gray-400 dark:bg-gray-600">
</div>
</template>
</div>
<div class="absolute bottom-0 left-0 grid grid-cols-5 gap-1 opacity-20 dark:opacity-10">
<template v-for='(_, i) in 25' :key='i'>
<div class="w-1.5 h-1.5 rounded-full bg-gray-400 dark:bg-gray-600">
</div>
</template>
</div>
<div class="relative z-10 py-8">
<div class="relative flex flex-col items-center">
<div class="relative flex flex-col items-center space-y-3">
<div class="relative">
<h1 class="relative text-4xl sm:text-6xl font-black text-transparent bg-clip-text bg-linear-to-br from-pink-500 via-purple-500 to-cyan-400 tracking-wider drop-shadow-2xl transform hover:scale-105 transition-transform duration-300 animate-bounce">Mardize
                  </h1>
<div class="absolute -top-4 -right-5 w-4 h-4 bg-linear-to-br from-yellow-400 to-pink-500 rounded-full animate-spin transform rotate-12">
</div>
<div class="absolute -top-2 -right-2 w-2.5 h-2.5 bg-linear-to-br from-pink-400 to-purple-500 rounded-full animate-ping">
</div>
<div class="absolute -top-1 -right-0.5 w-1.5 h-1.5 bg-linear-to-br from-purple-400 to-blue-500 rotate-45 animate-pulse delay-100">
</div>
<div class="absolute -bottom-3 -left-5 w-4 h-4 bg-linear-to-br from-blue-400 to-purple-500 rotate-45 animate-bounce delay-200">
</div>
<div class="absolute -bottom-1 -left-2 w-2 h-2 bg-linear-to-br from-cyan-400 to-blue-500 rounded-full animate-spin delay-300">
</div>
<div class="absolute top-0 left-1/2 w-1.5 h-1.5 bg-linear-to-br from-purple-400 to-pink-500 rounded-full animate-pulse delay-400">
</div>
<div class="absolute -bottom-4 -right-3 w-3 h-3 bg-linear-to-br from-cyan-400 to-teal-500 rounded-full animate-bounce delay-500">
</div>
<div class="absolute top-1 -left-4 w-2 h-2 bg-linear-to-br from-pink-400 to-red-500 rotate-45 animate-ping delay-600">
</div>
<div class="absolute -top-3 left-0 w-1 h-1 bg-yellow-300 rounded-full animate-pulse delay-700">
</div>
<div class="absolute -top-2 right-3 w-0.5 h-0.5 bg-pink-300 rounded-full animate-bounce delay-800">
</div>
<div class="absolute bottom-0 -left-1 w-0.5 h-0.5 bg-blue-300 rounded-full animate-ping delay-900">
</div>
<div class="absolute bottom-1 right-0 w-1 h-1 bg-purple-300 rounded-full animate-pulse delay-1000">
</div>
</div>
<div class="relative">
<h2 class="relative text-xl sm:text-3xl font-bold text-transparent bg-clip-text bg-linear-to-br from-blue-500 via-green-500 to-emerald-400 tracking-widest transform hover:scale-102 transition-all duration-300">拼豆AI生成
                  </h2>
<div class="absolute -top-3 -left-6 w-3.5 h-3.5 bg-linear-to-br from-blue-400 to-teal-500 rounded-full animate-bounce delay-75">
</div>
<div class="absolute -top-1 -left-3 w-2 h-2 bg-linear-to-br from-teal-400 to-green-500 rounded-full animate-ping delay-150">
</div>
<div class="absolute -top-0.5 -left-1 w-1 h-1 bg-linear-to-br from-green-400 to-emerald-500 rotate-45 animate-pulse delay-225">
</div>
<div class="absolute -top-3 -right-6 w-3 h-3 bg-linear-to-br from-green-400 to-emerald-500 rotate-45 animate-spin delay-300">
</div>
<div class="absolute -top-1 -right-3 w-1.5 h-1.5 bg-linear-to-br from-emerald-400 to-cyan-500 rounded-full animate-bounce delay-375">
</div>
<div class="absolute -bottom-2 -right-3 w-2.5 h-2.5 bg-linear-to-br from-emerald-400 to-teal-500 rounded-full animate-pulse delay-450">
</div>
<div class="absolute -bottom-1 -left-1 w-2 h-2 bg-linear-to-br from-teal-400 to-blue-500 rotate-45 animate-spin delay-525">
</div>
<div class="absolute -top-2 left-2 w-0.5 h-0.5 bg-blue-300 rounded-full animate-ping delay-600">
</div>
<div class="absolute -top-1 right-2 w-1 h-1 bg-teal-300 rounded-full animate-pulse delay-675">
</div>
<div class="absolute bottom-0 left-4 w-0.5 h-0.5 bg-green-300 rounded-full animate-bounce delay-750">
</div>
<div class="absolute bottom-1 right-4 w-0.5 h-0.5 bg-emerald-300 rounded-full animate-pulse delay-825">
</div>
<div class="absolute top-2 -left-2 w-0.5 h-0.5 bg-cyan-300 rounded-full animate-ping delay-900">
</div>
<div class="absolute top-2 -right-2 w-1 h-1 bg-teal-300 rounded-full animate-bounce delay-975">
</div>
</div>
</div>
<div class="absolute -top-10 -left-10 w-3 h-3 bg-linear-to-br from-pink-400 to-purple-500 rounded-full animate-float">
</div>
<div class="absolute -top-8 -left-6 w-1.5 h-1.5 bg-linear-to-br from-purple-400 to-pink-500 rotate-45 animate-spin delay-100">
</div>
<div class="absolute -top-6 -left-12 w-2 h-2 bg-linear-to-br from-pink-400 to-red-500 rounded-full animate-bounce delay-200">
</div>
<div class="absolute -top-10 -right-10 w-2.5 h-2.5 bg-linear-to-br from-blue-400 to-cyan-500 rounded-full animate-ping delay-300">
</div>
<div class="absolute -top-6 -right-14 w-1 h-1 bg-linear-to-br from-cyan-400 to-blue-500 rotate-45 animate-pulse delay-400">
</div>
<div class="absolute -top-4 -right-8 w-3 h-3 bg-linear-to-br from-blue-400 to-purple-500 rounded-full animate-bounce delay-500">
</div>
<div class="absolute -bottom-10 -left-10 w-2 h-2 bg-linear-to-br from-yellow-400 to-orange-500 rounded-full animate-pulse delay-600">
</div>
<div class="absolute -bottom-8 -left-14 w-1.5 h-1.5 bg-linear-to-br from-orange-400 to-red-500 rotate-45 animate-spin delay-700">
</div>
<div class="absolute -bottom-6 -left-6 w-2.5 h-2.5 bg-linear-to-br from-yellow-400 to-pink-500 rounded-full animate-float delay-800">
</div>
<div class="absolute -bottom-10 -right-10 w-3 h-3 bg-linear-to-br from-green-400 to-teal-500 rotate-45 animate-bounce delay-900">
</div>
<div class="absolute -bottom-8 -right-6 w-1 h-1 bg-linear-to-br from-teal-400 to-cyan-500 rounded-full animate-ping delay-1000">
</div>
<div class="absolute -bottom-6 -right-14 w-2 h-2 bg-linear-to-br from-emerald-400 to-green-500 rounded-full animate-pulse delay-1100">
</div>
<div class="absolute -top-12 left-0 w-0.5 h-0.5 bg-yellow-300 rounded-full animate-ping delay-1200">
</div>
<div class="absolute -top-2 -left-16 w-1 h-1 bg-pink-300 rounded-full animate-bounce delay-1300">
</div>
<div class="absolute top-2 -right-18 w-0.5 h-0.5 bg-blue-300 rounded-full animate-pulse delay-1400">
</div>
<div class="absolute -bottom-12 right-0 w-1 h-1 bg-purple-300 rounded-full animate-float delay-1500">
</div>
<div class="absolute -bottom-2 -right-16 w-0.5 h-0.5 bg-green-300 rounded-full animate-ping delay-1600">
</div>
<div class="absolute bottom-2 -left-18 w-1 h-1 bg-teal-300 rounded-full animate-bounce delay-1700">
</div>
</div>
<div class="h-1 w-24 mx-auto my-3 bg-linear-to-r from-blue-500 to-pink-500 rounded-full">
</div>
<p class="mt-4 text-base sm:text-lg font-light text-gray-600 dark:text-gray-300 max-w-lg mx-auto text-center tracking-widest leading-relaxed">AI帮帮忙，像素创意更简单
            </p>
</div>
</header>
<main ref="mainRef" class="w-full md:max-w-4xl flex flex-col items-center space-y-5 sm:space-y-6 relative overflow-hidden">
<div @drop='handleDrop' @dragover='handleDragOver' @dragenter='handleDragOver' @click='isMounted && triggerFileInput()' :class='`border-2 border-dashed border-gray-300 dark:border-gray-600 rounded-lg p-6 sm:p-8 text-center ${isMounted ? "cursor-pointer hover:border-blue-400 dark:hover:border-blue-500 hover:bg-blue-50 dark:hover:bg-gray-800" : "cursor-wait"} transition-all duration-300 w-full md:max-w-md flex flex-col justify-center items-center shadow-sm hover:shadow-md`' :style='{ minHeight: "130px" }'>
<svg xmlns="http://www.w3.org/2000/svg" class="h-10 w-10 sm:h-12 sm:w-12 text-gray-400 dark:text-gray-500 mb-2 sm:mb-3" fill="none" viewBox="0 0 24 24" stroke="currentColor" :stroke-width='1'>
<path stroke-linecap="round" stroke-linejoin="round" d="M7 16a4 4 0 01-.88-7.903A5 5 0 1115.9 6L16 6a5 5 0 011 9.9M15 13l-3-3m0 0l-3 3m3-3v12" />
</svg>
<p class="text-xs sm:text-sm text-gray-500 dark:text-gray-400">拖放图片到此处，或
              <span class="font-medium text-blue-600 dark:text-blue-400">点击选择文件</span>
</p>
<p class="text-xs text-gray-400 dark:text-gray-500 mt-1">支持 JPG, PNG 图片格式，或 CSV 数据文件
            </p>
</div>
<template v-if='!originalImageSrc'>
<div class="w-full md:max-w-md bg-linear-to-br from-blue-50 to-indigo-50 dark:from-gray-800 dark:to-gray-700 p-3 rounded-lg border border-blue-100 dark:border-gray-600 shadow-sm">
<p class="text-xs text-indigo-700 dark:text-indigo-300 flex items-start">
<svg xmlns="http://www.w3.org/2000/svg" class="h-4 w-4 mr-1.5 shrink-0 text-blue-500 dark:text-blue-400 mt-0.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
<path stroke-linecap="round" stroke-linejoin="round" :stroke-width='2' d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
</svg>
<span class="text-indigo-700 dark:text-indigo-300">小贴士：使用像素图进行转换前，请确保图片的边缘吻合像素格子的边界线，这样可以获得更精确的切割效果和更好的成品。
                </span>
</p>
</div>
</template>
<input type="file" accept="image/jpeg, image/png, .csv, text/csv, application/csv, text/plain" @change='handleFileChange' ref="fileInputRef" class="hidden" />
<template v-if='originalImageSrc'>
<div class="w-full flex flex-col items-center space-y-5 sm:space-y-6">
<template v-if='!isManualColoringMode'>
<div class="w-full md:max-w-2xl grid grid-cols-1 sm:grid-cols-2 gap-4 bg-white dark:bg-gray-800 p-4 sm:p-5 rounded-xl shadow-md border border-gray-100 dark:border-gray-700">
<div class="flex-1">
<label for="granularityInput" class="block text-xs sm:text-sm font-medium text-gray-700 dark:text-gray-300 mb-1.5 sm:mb-2">横轴切割数量 (10-300):
                    </label>
<div class="flex items-center gap-2">
<input type="number" id="granularityInput" :value='granularityInput' @change='handleGranularityInputChange' class="w-full p-1.5 border border-gray-300 dark:border-gray-600 rounded-md text-sm focus:ring-blue-500 focus:border-blue-500 h-9 shadow-sm bg-white dark:bg-gray-700 text-gray-900 dark:text-gray-200 placeholder-gray-400 dark:placeholder-gray-500" min="10" max="300" />
</div>
</div>
<div class="flex-1">
<label for="similarityThresholdInput" class="block text-xs sm:text-sm font-medium text-gray-700 dark:text-gray-300 mb-1.5 sm:mb-2">颜色合并阈值 (0-100):
                    </label>
<div class="flex items-center gap-2">
<input type="number" id="similarityThresholdInput" :value='similarityThresholdInput' @change='handleSimilarityThresholdInputChange' class="w-full p-1.5 border border-gray-300 dark:border-gray-600 rounded-md text-sm focus:ring-blue-500 focus:border-blue-500 h-9 shadow-sm bg-white dark:bg-gray-700 text-gray-900 dark:text-gray-200 placeholder-gray-400 dark:placeholder-gray-500" min="0" max="100" />
</div>
</div>
<div class="sm:col-span-2 flex flex-wrap items-center gap-2">
<button @click='handleConfirmParameters' class="h-9 bg-blue-500 hover:bg-blue-600 text-white text-sm px-3 rounded-md whitespace-nowrap transition-colors duration-200 shadow-sm">应用数字
                    </button>
<button @click='handleAutoRemoveBackground' :disabled='!mappedPixelData || !gridDimensions' class="inline-flex items-center justify-center h-9 px-3 text-sm rounded-md border border-blue-200 dark:border-blue-700 bg-blue-50 dark:bg-blue-900/30 text-blue-700 dark:text-blue-200 hover:bg-blue-100 dark:hover:bg-blue-800/40 transition-colors duration-200 disabled:opacity-50 disabled:cursor-not-allowed whitespace-nowrap">一键去背景
                    </button>
</div>
<div class="sm:col-span-2">
<label for="pixelationModeSelect" class="block text-xs sm:text-sm font-medium text-gray-700 dark:text-gray-300 mb-1.5 sm:mb-2">处理模式:
                    </label>
<div class="flex items-center gap-2">
<select id="pixelationModeSelect" :value='pixelationMode' @change='handlePixelationModeChange' class="w-full p-1.5 border border-gray-300 dark:border-gray-600 rounded-md text-sm focus:ring-blue-500 focus:border-blue-500 h-9 shadow-sm bg-white dark:bg-gray-700 text-gray-900 dark:text-gray-200">
<option :value='PixelationMode.Dominant' class="bg-white dark:bg-gray-700 text-gray-900 dark:text-gray-200">卡通 (主色)
                        </option>
<option :value='PixelationMode.Average' class="bg-white dark:bg-gray-700 text-gray-900 dark:text-gray-200">真实 (平均)
                        </option>
</select>
</div>
</div>
<div class="sm:col-span-2">
<label for="paletteSizeSelect" class="block text-xs sm:text-sm font-medium text-gray-700 dark:text-gray-300 mb-1.5 sm:mb-2">处理色板:</label>
<select id="paletteSizeSelect" v-model.number="paletteSize" class="w-full p-1.5 border border-gray-300 dark:border-gray-600 rounded-md text-sm focus:ring-blue-500 focus:border-blue-500 h-9 shadow-sm bg-white dark:bg-gray-700 text-gray-900 dark:text-gray-200">
<option :value="291">MARD 291 色（全部）</option>
<option :value="221">MARD 221 色（标准）</option>
</select>
</div>
<div class="sm:col-span-2">
<button @click='() => isColorSystemCollapsed = !isColorSystemCollapsed' class="flex items-center justify-between w-full text-xs sm:text-sm font-medium text-gray-700 dark:text-gray-300 mb-1.5 sm:mb-2">
<span>色号系统:</span>
<svg xmlns="http://www.w3.org/2000/svg" :class='`h-4 w-4 transition-transform duration-200 ${isColorSystemCollapsed ? "rotate-0" : "rotate-180"}`' fill="none" viewBox="0 0 24 24" stroke="currentColor">
<path stroke-linecap="round" stroke-linejoin="round" :stroke-width='2' d="M19 9l-7 7-7-7" />
</svg>
</button>
<template v-if='!isColorSystemCollapsed'>
<div class="space-y-3">
<div class="flex flex-wrap gap-2">
<template v-for='(option) in colorSystemOptions' :key='option.key'>
<button @click='() => selectedColorSystem = option.key as ColorSystem' :class='`px-3 py-2 text-sm rounded-lg border transition-all duration-200 shrink-0 ${selectedColorSystem === option.key     ? "bg-blue-500 text-white border-blue-500 shadow-md transform scale-105"     : "bg-white dark:bg-gray-700 text-gray-700 dark:text-gray-300 border-gray-300 dark:border-gray-600 hover:border-blue-400 dark:hover:border-blue-500 hover:bg-blue-50 dark:hover:bg-gray-600"}`'>{{ option.name }}</button>
</template>
</div>
<div class="mt-3">
<button @click='() => isCustomPaletteEditorOpen = true' class="w-full py-2.5 px-3 flex items-center justify-center gap-2 bg-linear-to-br from-blue-500 to-purple-500 text-white font-medium rounded-lg shadow-sm transition-all duration-200 hover:shadow-md hover:from-blue-600 hover:to-purple-600">
<svg xmlns="http://www.w3.org/2000/svg" class="h-5 w-5" viewBox="0 0 20 20" fill="currentColor">
<path fill-rule="evenodd" d="M4 2a2 2 0 00-2 2v11a3 3 0 106 0V4a2 2 0 00-2-2H4zm1 14a1 1 0 100-2 1 1 0 000 2zm5-1.757l4.9-4.9a2 2 0 000-2.828L13.485 5.1a2 2 0 00-2.828 0L10 5.757v8.486zM16 18H9.071l6-6H16a2 2 0 012 2v2a2 2 0 01-2 2z" clip-rule="evenodd" />
</svg>管理色板 (
                            {{ availableBeadPalette.filter((color) => customPaletteSelections[color.hex.toUpperCase()]).length }}色)
                          </button>
<template v-if='isCustomPalette'>
<p class="text-xs text-center text-blue-500 dark:text-blue-400 mt-1.5">当前使用自定义色板
                            </p>
</template>
</div>
</div>
</template>
</div>
</div>
</template>
<template v-if='isCustomPaletteEditorOpen'>
<div class="fixed inset-0 bg-black bg-opacity-50 backdrop-blur-sm z-50 flex justify-center items-center p-4">
<div class="bg-white dark:bg-gray-800 rounded-xl shadow-2xl w-full max-w-4xl max-h-[90vh] overflow-hidden flex flex-col">
<input type="file" accept=".json" ref="importPaletteInputRef" @change='handleImportPaletteFile' class="hidden" />
<div class="p-4 sm:p-6 flex-1 overflow-y-auto"> <CustomPaletteEditor :allColors='availableBeadPalette' :currentSelections='customPaletteSelections' :onSelectionChange='handleSelectionChange' :onSaveCustomPalette='handleSaveCustomPalette' :onClose='() => isCustomPaletteEditorOpen = false' :onExportCustomPalette='handleExportCustomPalette' :onImportCustomPalette='triggerImportPalette' :selectedColorSystem='selectedColorSystem' />
</div>
</div>
</div>
</template>
<div class="w-full md:max-w-2xl">
<canvas ref="originalCanvasRef" class="hidden">
</canvas>
<template v-if='isManualColoringMode && mappedPixelData && gridDimensions'>
<div class="w-full mb-4 p-3 bg-blue-50 dark:bg-gray-800 rounded-lg shadow-sm border border-blue-100 dark:border-gray-700">
<div class="flex justify-center">
<div class="bg-blue-50 dark:bg-gray-700 border border-blue-100 dark:border-gray-600 rounded-lg p-2 flex flex-col sm:flex-row items-start sm:items-center gap-2 sm:gap-3 text-xs text-gray-600 dark:text-gray-300 w-full sm:w-auto">
<div class="flex items-center gap-1 w-full sm:w-auto">
<svg xmlns="http://www.w3.org/2000/svg" class="h-3.5 w-3.5 text-blue-500 dark:text-blue-400 shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor">
<path stroke-linecap="round" stroke-linejoin="round" :stroke-width='2' d="M15.232 5.232l3.536 3.536m-2.036-5.036a2.5 2.5 0 113.536 3.536L6.5 21.036H3v-3.572L16.732 3.732z" />
</svg>
<span>使用右上角菜单操作</span>
</div>
<span class="hidden sm:inline text-gray-300 dark:text-gray-500">|</span>
<div class="flex items-center gap-1 w-full sm:w-auto">
<svg xmlns="http://www.w3.org/2000/svg" class="h-3.5 w-3.5 text-blue-500 dark:text-blue-400 shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor">
<path stroke-linecap="round" stroke-linejoin="round" :stroke-width='2' d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
</svg>
<span>推荐电脑操作，上色更精准</span>
</div>
</div>
</div>
</div>
</template>
<div class="bg-white dark:bg-gray-800 p-4 rounded-xl shadow-md border border-gray-100 dark:border-gray-700">
<template v-if='gridDimensions && gridDimensions.N > 100'>
<div class="mb-3 p-2 bg-blue-50 dark:bg-blue-900/30 border border-blue-200 dark:border-blue-800 rounded-lg text-xs text-blue-700 dark:text-blue-300 text-center">
<div class="flex items-center justify-center gap-1">
<svg xmlns="http://www.w3.org/2000/svg" class="h-3.5 w-3.5 text-blue-500 dark:text-blue-400" fill="none" viewBox="0 0 24 24" stroke="currentColor">
<path stroke-linecap="round" stroke-linejoin="round" :stroke-width='2' d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
</svg>
<span>高精度网格 ({{ gridDimensions.N }}×{{ gridDimensions.M }}) -
                          画布已自动放大，可左右滚动、放大查看精细图像
                        </span>
</div>
</div>
</template>
<div class="flex justify-center mb-3 sm:mb-4 bg-gray-100 dark:bg-gray-700 p-2 rounded-lg overflow-x-auto overflow-y-hidden" :style='{ minHeight: "150px" }'>
<PixelatedPreviewCanvas :canvasRef='canvasHandle' :mappedPixelData='mappedPixelData' :gridDimensions='gridDimensions' :isManualColoringMode='isManualColoringMode' :onInteraction='handleCanvasInteraction' :highlightColorKey='highlightColorKey' :onHighlightComplete='handleHighlightComplete' />
</div>
</div>
</div>
</div>
</template>
<template v-if='!isManualColoringMode &&     originalImageSrc &&     colorCounts &&     Object.keys(colorCounts).length > 0'>
<div class="w-full md:max-w-2xl mt-6 bg-white dark:bg-gray-800 p-4 rounded-lg shadow border border-gray-100 dark:border-gray-700 color-stats-panel">
<h3 class="text-lg font-semibold mb-1 text-gray-700 dark:text-gray-200 text-center">去除杂色
                </h3>
<p class="text-xs text-center text-gray-500 dark:text-gray-400 mb-3">点击下方列表中的颜色可将其从可用列表中排除。总计: {{ totalBeadCount }}颗
                </p>
<ul class="space-y-1 max-h-60 overflow-y-auto pr-2 text-sm">
<template v-for='({ hexKey, displayColorKey, isExcluded, count, colorHex }) in gridColorStats' :key='hexKey'>
<li @click='() => handleToggleExcludeColor(hexKey)' :class='`flex items-center justify-between p-1.5 rounded cursor-pointer transition-colors ${isExcluded     ? "bg-red-100 dark:bg-red-900/50 hover:bg-red-200 dark:hover:bg-red-800/60 opacity-60 dark:opacity-70"     : "hover:bg-gray-100 dark:hover:bg-gray-700"}`' :title='isExcluded     ? `点击恢复 ${displayColorKey}`     : `点击排除 ${displayColorKey}`'>
<div :class='`flex items-center space-x-2 ${isExcluded ? "line-through" : ""}`'>
<span class="inline-block w-4 h-4 rounded border border-gray-400 dark:border-gray-500 shrink-0" :style='{     backgroundColor: isExcluded ? "#666" : colorHex, }'>
</span>
<span :class='`font-mono font-medium ${isExcluded ? "text-red-700 dark:text-red-400" : "text-gray-800 dark:text-gray-200"}`'>{{ displayColorKey }}</span>
</div>
<span :class='`text-xs ${isExcluded ? "text-red-600 dark:text-red-400 line-through" : "text-gray-600 dark:text-gray-300"}`'>{{ count }}颗
                          </span>
</li>
</template>
</ul>
<template v-if='excludedColorKeys.size > 0'>
<div class="mt-3">
<button @click='showExcludedColors = !showExcludedColors' class="w-full text-xs py-1.5 px-2 bg-gray-200 dark:bg-gray-600 text-gray-700 dark:text-gray-200 rounded hover:bg-gray-300 dark:hover:bg-gray-500 transition-colors flex items-center justify-between">
<span>已排除的颜色 ({{ excludedColorKeys.size }})</span>
<svg xmlns="http://www.w3.org/2000/svg" :class='`h-4 w-4 text-gray-500 dark:text-gray-400 transform transition-transform ${showExcludedColors ? "rotate-180" : ""}`' fill="none" viewBox="0 0 24 24" stroke="currentColor">
<path stroke-linecap="round" stroke-linejoin="round" :stroke-width='2' d="M19 9l-7 7-7-7" />
</svg>
</button>
<template v-if='showExcludedColors'>
<div class="mt-2 border border-gray-200 dark:border-gray-700 rounded-md p-2 bg-gray-100 dark:bg-gray-800">
<div class="max-h-40 overflow-y-auto">
<template v-if='Array.from(excludedColorKeys).length > 0'>
<ul class="space-y-1">
<template v-for='({ hexKey, colorData }) in excludedColors' :key='hexKey'>
<li class="flex justify-between items-center p-1 hover:bg-gray-200 dark:hover:bg-gray-700 rounded">
<div class="flex items-center space-x-2">
<span class="inline-block w-4 h-4 rounded border border-gray-400 dark:border-gray-500 shrink-0" :style='{     backgroundColor: colorData?.hex || hexKey, }'>
</span>
<span class="font-mono text-xs text-gray-800 dark:text-gray-200">{{ getColorKeyByHex(hexKey, selectedColorSystem) }}</span>
</div>
<button @click='handleToggleExcludeColor(hexKey)' class="text-xs py-0.5 px-2 bg-blue-100 text-blue-700 dark:bg-blue-900/30 dark:text-blue-300 rounded hover:bg-blue-200 dark:hover:bg-blue-800/40">恢复
                                      </button>
</li>
</template>
</ul>
</template>
<template v-else>
<p class="text-xs text-center text-gray-500 dark:text-gray-400 py-2">没有排除的颜色
                            </p>
</template>
</div>
<button @click='restoreAllExcludedColors' class="mt-2 w-full text-xs py-1 px-2 bg-blue-500 hover:bg-blue-600 text-white rounded transition-colors">一键恢复所有颜色
                        </button>
</div>
</template>
</div>
</template>
</div>
</template> <template v-if='!isManualColoringMode &&     originalImageSrc &&     activeBeadPalette.length === 0 &&     excludedColorKeys.size > 0'>
<div class="w-full md:max-w-2xl mt-6 bg-yellow-100 dark:bg-yellow-900/50 p-4 rounded-lg shadow border border-yellow-200 dark:border-yellow-800/60 text-center text-sm text-yellow-800 dark:text-yellow-300">当前可用颜色过少或为空。请在上方统计列表中查看已排除的颜色并恢复部分，或更换色板。
                <template v-if='excludedColorKeys.size > 0'>
<button @click='showExcludedColorList' class="mt-2 ml-2 text-xs py-1 px-2 bg-yellow-200 dark:bg-yellow-700/60 text-yellow-900 dark:text-yellow-200 rounded hover:bg-yellow-300 dark:hover:bg-yellow-600/70 transition-colors">查看已排除颜色 ({{ excludedColorKeys.size }})
                  </button>
</template>
</div>
</template>
<template v-if='!isManualColoringMode && originalImageSrc && mappedPixelData && gridDimensions'>
<div class="w-full md:max-w-2xl mt-4 space-y-3"> <button @click='() => {     isManualColoringMode = true;     selectedColor = null;     tooltipData = null; }' :class='`w-full py-2.5 px-4 text-sm sm:text-base rounded-lg transition-all duration-300 flex items-center justify-center gap-2 bg-linear-to-br from-blue-500 to-blue-600 hover:from-blue-600 hover:to-blue-700 text-white shadow-md hover:shadow-lg hover:translate-y-[-1px]`'>
<svg xmlns="http://www.w3.org/2000/svg" class="h-5 w-5" viewBox="0 0 20 20" fill="currentColor"> <path d="M13.586 3.586a2 2 0 112.828 2.828l-.793.793-2.828-2.828.793-.793zM11.379 5.793L3 14.172V17h2.828l8.38-8.379-2.83-2.828z" /> </svg>进入手动编辑模式
              </button>
<button @click='handleEnterFocusMode' :class='`w-full py-2.5 px-4 text-sm sm:text-base rounded-lg transition-all duration-300 flex items-center justify-center gap-2 bg-linear-to-br from-purple-500 to-purple-600 hover:from-purple-600 hover:to-purple-700 text-white shadow-md hover:shadow-lg hover:translate-y-[-1px]`'>
<svg xmlns="http://www.w3.org/2000/svg" class="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
<path stroke-linecap="round" stroke-linejoin="round" :stroke-width='2' d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
<path stroke-linecap="round" stroke-linejoin="round" :stroke-width='2' d="M2.458 12C3.732 7.943 7.523 5 12 5c4.478 0 8.268 2.943 9.542 7-1.274 4.057-5.064 7-9.542 7-4.477 0-8.268-2.943-9.542-7z" />
</svg>进入专心拼豆模式（AplhaTest）
              </button>
</div>
</template> <template v-if='!isManualColoringMode && originalImageSrc && mappedPixelData'>
<div class="w-full md:max-w-2xl mt-4">
<button @click='() => isDownloadSettingsOpen = true' :disabled='!mappedPixelData ||     !gridDimensions ||     gridDimensions.N === 0 ||     gridDimensions.M === 0 ||     activeBeadPalette.length === 0' class="w-full py-2.5 px-4 bg-linear-to-br from-green-500 to-green-600 text-white text-sm sm:text-base rounded-lg hover:from-green-600 hover:to-green-700 focus:outline-none focus:ring-2 focus:ring-green-500 focus:ring-offset-2 transition-all duration-300 flex items-center justify-center gap-2 disabled:opacity-50 disabled:cursor-not-allowed shadow-md hover:shadow-lg hover:translate-y-[-1px] disabled:hover:translate-y-0 disabled:hover:shadow-md">
<svg xmlns="http://www.w3.org/2000/svg" class="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" :stroke-width='2'>
<path stroke-linecap="round" stroke-linejoin="round" d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4" />
</svg>下载拼豆图纸
              </button>
</div>
</template> <template v-if='tooltipData'>
<GridTooltip :tooltipData='tooltipData' :selectedColorSystem='selectedColorSystem' />
</template>
</main>
<FloatingToolbar
  :isManualColoringMode='isManualColoringMode'
  :isPaletteOpen='isFloatingPaletteOpen'
  :onTogglePalette='toggleFloatingPalette'
  :onExitManualMode='exitManualMode'
  :onToggleMagnifier='handleToggleMagnifier'
  :isMagnifierActive='isMagnifierActive'
/>
<template v-if='isManualColoringMode'>
<FloatingColorPalette :colors='currentGridColors' :selectedColor='selectedColor' :onColorSelect='handleColorSelect' :selectedColorSystem='selectedColorSystem' :isEraseMode='isEraseMode' :onEraseToggle='handleEraseToggle' :fullPaletteColors='fullPaletteColors' :showFullPalette='showFullPalette' :onToggleFullPalette='handleToggleFullPalette' :colorReplaceState='colorReplaceState' :onColorReplaceToggle='handleColorReplaceToggle' :onColorReplace='handleColorReplace' :onHighlightColor='handleHighlightColor' :isOpen='isFloatingPaletteOpen' :onToggleOpen='toggleFloatingPalette' :isActive='activeFloatingTool === "palette"' :onActivate='handleActivatePalette' />
</template>
<template v-if='isManualColoringMode'>
<MagnifierTool :isActive='isMagnifierActive' :onToggle='handleToggleMagnifier' :mappedPixelData='mappedPixelData' :gridDimensions='gridDimensions' :selectedColor='selectedColor' :selectedColorSystem='selectedColorSystem' :onPixelEdit='handleMagnifierPixelEdit' :cellSize='gridDimensions     ? Math.min(6, Math.max(4, 500 / Math.max(gridDimensions.N, gridDimensions.M)))     : 6' :selectionArea='magnifierSelectionArea' :onClearSelection='closeMagnifierSelection' :isFloatingActive='activeFloatingTool === "magnifier"' :onActivateFloating='handleActivateMagnifier' :highlightColorKey='highlightColorKey' />
<MagnifierSelectionOverlay :isActive='isMagnifierActive && !magnifierSelectionArea' :canvasRef='canvasHandle' :gridDimensions='gridDimensions' :cellSize='gridDimensions     ? Math.min(6, Math.max(4, 500 / Math.max(gridDimensions.N, gridDimensions.M)))     : 6' :onSelectionComplete='updateMagnifierSelection' />
</template>
<footer class="w-full md:max-w-4xl mt-10 mb-6 py-6 text-center text-xs sm:text-sm text-gray-500 dark:text-gray-400 border-t border-gray-200 dark:border-gray-700 bg-gradient-to-b from-white to-gray-50 dark:from-gray-900 dark:to-gray-800/50 rounded-lg shadow-inner">
<div class="flex gap-3 justify-center mb-5">
<button @click='() => isDonationModalOpen = true' class="px-6 py-2.5 bg-linear-to-br from-pink-500 to-rose-500 text-white rounded-full shadow-lg transition-all duration-300 hover:shadow-xl hover:translate-y-[-2px] flex items-center">
<svg xmlns="http://www.w3.org/2000/svg" class="h-5 w-5 mr-2" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
<path d="M18 8h1a2 2 0 0 1 2 2v1c0 1.1-.9 2-2 2h-1" fill="#f9a8d4" />
<path d="M6 8h12v9a3 3 0 0 1-3 3H9a3 3 0 0 1-3-3V8z" fill="#f9a8d4" />
<path d="M6 8V7a3 3 0 0 1 3-3h6a3 3 0 0 1 3 3v1" fill="#f472b6" />
<path d="M12 16v-4" stroke="#7d2a5a" />
<path d="M9.5 14.5L9 16" stroke="#7d2a5a" />
<path d="M14.5 14.5L15 16" stroke="#7d2a5a" />
</svg>
<span>请作者喝一杯奶茶</span>
</button>
<button @click='() => isTutorialModalOpen = true' class="px-6 py-2.5 bg-linear-to-br from-blue-500 to-indigo-500 text-white rounded-full shadow-lg transition-all duration-300 hover:shadow-xl hover:translate-y-[-2px] flex items-center">
<svg xmlns="http://www.w3.org/2000/svg" class="h-5 w-5 mr-2" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
<circle cx="12" cy="12" r="10" />
<path d="m9 12 2 2 4-4" />
</svg>
<span>帮助教程</span>
</button>
</div>
<p class="font-medium text-gray-600 dark:text-gray-300">Mardize 拼豆底稿生成器 &copy; {{ new Date().getFullYear() }}</p>
</footer>
<DonationModal :isOpen='isDonationModalOpen' :onClose='() => isDonationModalOpen = false' />
<template v-if='isTutorialModalOpen'>
<div class="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-sm p-4">
<div class="bg-white dark:bg-gray-900 rounded-xl shadow-2xl max-w-2xl w-full max-h-[90vh] flex flex-col">
<div class="flex items-center justify-between px-6 py-4 border-b border-gray-200 dark:border-gray-700">
<h2 class="text-lg font-semibold text-gray-900 dark:text-white flex items-center gap-2">
<svg class="w-5 h-5 text-blue-500" fill="none" stroke="currentColor" viewBox="0 0 24 24">
<circle cx="12" cy="12" r="10" />
<path d="m9 12 2 2 4-4" />
</svg>使用教程
                </h2>
<button @click='() => isTutorialModalOpen = false' class="text-gray-500 hover:text-gray-700 dark:text-gray-400 dark:hover:text-gray-200 transition-colors">
<svg class="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
<path stroke-linecap="round" stroke-linejoin="round" :stroke-width='2' d="M6 18L18 6M6 6l12 12" />
</svg>
</button>
</div>
<div class="flex-1 overflow-auto p-6">
<div class="space-y-6">
<div class="space-y-2">
<h3 class="text-md font-medium text-gray-900 dark:text-white flex items-center gap-2">
<span class="inline-flex items-center justify-center w-6 h-6 rounded-full bg-blue-100 dark:bg-blue-900 text-blue-600 dark:text-blue-300 text-sm font-medium">1
                      </span>一般使用流程
                    </h3>
<div class="bg-gray-50 dark:bg-gray-800/50 p-4 rounded-lg border border-gray-200 dark:border-gray-700">
<p class="text-gray-700 dark:text-gray-300">上传图片 → 去掉背景 → 下载图纸 → 专心拼豆
                      </p>
</div>
</div>
<div class="space-y-2">
<h3 class="text-md font-medium text-gray-900 dark:text-white flex items-center gap-2">
<span class="inline-flex items-center justify-center w-6 h-6 rounded-full bg-blue-100 dark:bg-blue-900 text-blue-600 dark:text-blue-300 text-sm font-medium">2
                      </span>处理模式
                    </h3>
<div class="bg-gray-50 dark:bg-gray-800/50 p-4 rounded-lg border border-gray-200 dark:border-gray-700">
<p class="text-gray-700 dark:text-gray-300">可选卡通模式和真实模式，真实模式会使用更细的颜色更逼真更复杂。
                      </p>
</div>
</div>
<div class="space-y-2">
<h3 class="text-md font-medium text-gray-900 dark:text-white flex items-center gap-2">
<span class="inline-flex items-center justify-center w-6 h-6 rounded-full bg-blue-100 dark:bg-blue-900 text-blue-600 dark:text-blue-300 text-sm font-medium">3
                      </span>档案管理
                    </h3>
<div class="bg-gray-50 dark:bg-gray-800/50 p-4 rounded-lg border border-gray-200 dark:border-gray-700">
<p class="text-gray-700 dark:text-gray-300">下载档案可以下次直接导入使用。
                      </p>
</div>
</div>
</div>
</div>
<div class="flex items-center justify-end px-6 py-4 border-t border-gray-200 dark:border-gray-700">
<button @click='() => isTutorialModalOpen = false' class="px-6 py-2 rounded-lg bg-blue-600 text-white hover:bg-blue-700 transition-colors flex items-center gap-2">
<svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
<path stroke-linecap="round" stroke-linejoin="round" :stroke-width='2' d="M5 13l4 4L19 7" />
</svg>我知道了
                </button>
</div>
</div>
</div>
</template>
<DownloadSettingsModal
  :isOpen='isDownloadSettingsOpen'
  :onClose='() => isDownloadSettingsOpen = false'
  :options='downloadOptions'
  :onOptionsChange='updateDownloadOptions'
  :onDownload='handleDownloadRequest'
/>
<FocusModePreDownloadModal :isOpen='isFocusModePreDownloadModalOpen' :onClose='() => isFocusModePreDownloadModalOpen = false' :onProceedWithoutDownload='handleProceedToFocusMode' :mappedPixelData='mappedPixelData' :gridDimensions='gridDimensions' :selectedColorSystem='selectedColorSystem' />
<ImageCropperModal :imageSrc='cropperImageSrc' :isOpen='isCropperOpen' :onClose='handleCropCancel' :onConfirm='handleCropConfirm' />
</div>
</template>

<style>
@keyframes float {
  0% { transform: translateY(0px); }
  50% { transform: translateY(-5px); }
  100% { transform: translateY(0px); }
}
.animate-float { animation: float 3s ease-in-out infinite; }
</style>
