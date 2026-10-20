<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue';
import mapping from '../colorSystemMapping.json';
import { cleanColorFringe } from './cleanColorFringe';

type Tool = 'pencil' | 'eraser' | 'picker' | 'line' | 'rectangle' | 'fill';
type PixelPosition = { x: number; y: number };
type AnnotationStatus = 'unmodified' | 'pending' | 'human_edited' | 'qualified' | 'unqualified';
type SampleSummary = { id: string; width: number; height: number; model_version: string; status: AnnotationStatus; changed_pixels: number };
type Sample = SampleSummary & { indices: number[]; corrected_indices?: number[]; review_reason?: string; paths: Record<string, string> };
type SamplePage = { items: SampleSummary[]; total: number; all_total: number; completed: number; offset: number; limit: number };
type PaletteColor = { hex: string; code: string };
type SizeFilter = '' | '24' | '52' | '78' | '104';
const palette: PaletteColor[] = Object.entries(mapping).map(([hex, names]) => ({ hex, code: names.MARD }));
const PAGE_SIZE = 100;
const ROW_HEIGHT = 62;
const sampleCache = ref<Record<number, SampleSummary>>({});
const total = ref(0);
const datasetTotal = ref(0);
const completedCount = ref(0);
const selectedIndex = ref(-1);
const listElement = ref<HTMLDivElement | null>(null);
const listScrollTop = ref(0);
const listHeight = ref(500);
const query = ref('');
const sizeFilter = ref<SizeFilter>('');
const filterBusy = ref(false);
const sizeOptions: { value: SizeFilter; label: string }[] = [
  { value: '', label: '全部' }, { value: '24', label: '24' }, { value: '52', label: '52' },
  { value: '78', label: '78' }, { value: '104', label: '104' },
];
let cacheVersion = 0;
let searchTimer: number | undefined;
let refreshTimer: number | undefined;
let listResizeObserver: ResizeObserver | null = null;
const loadedPages = new Set<number>();
const loadingPages = new Set<number>();
const sample = ref<Sample | null>(null);
const pixels = ref<number[]>([]);
const savedPixels = ref<number[]>([]);
const selectedColor = ref(0);
const tool = ref<Tool>('pencil');
const zoom = ref(12);
const grid = ref(true);
const editorBackground = ref<'light' | 'dark'>('light');
const hover = ref<{ x: number; y: number } | null>(null);
const canvas = ref<HTMLCanvasElement | null>(null);
const viewport = ref<HTMLDivElement | null>(null);
const paletteSearch = ref('');
const sampleSearch = ref('');
const error = ref('');
const notice = ref('');
const busy = ref(false);
const importOpen = ref(false);
const importId = ref('');
const modelVersion = ref('v0.1');
const sourceFile = ref<File | null>(null);
const predictionFile = ref<File | null>(null);
const undoStack = ref<number[][]>([]);
const redoStack = ref<number[][]>([]);
const flashedColor = ref<number | null>(null);
let flashTimer: number | undefined;
let strokeStart: number[] | null = null;
let strokeAnchor: PixelPosition | null = null;
let strokeLast: PixelPosition | null = null;
let strokeTool: Tool | null = null;
let strokeColor = -1;
let activePointerId: number | null = null;
let panning = false;
let panStart = { x: 0, y: 0, left: 0, top: 0 };
let spaceHeld = false;

const visibleStart = computed(() => Math.max(0, Math.floor(listScrollTop.value / ROW_HEIGHT) - 5));
const visibleEnd = computed(() => Math.min(total.value, visibleStart.value + Math.ceil(listHeight.value / ROW_HEIGHT) + 12));
const visibleRows = computed(() => Array.from({ length: visibleEnd.value - visibleStart.value }, (_, offset) => {
  const index = visibleStart.value + offset;
  return { index, item: sampleCache.value[index] };
}));
const filteredPalette = computed(() => palette.map((color, index) => ({ ...color, index })).filter(color => `${color.code} ${color.hex}`.toLowerCase().includes(paletteSearch.value.toLowerCase())));
const changedPixels = computed(() => sample.value ? pixels.value.reduce((n, value, i) => n + Number(value !== sample.value!.indices[i]), 0) : 0);
const dirty = computed(() => pixels.value.some((value, i) => value !== savedPixels.value[i]));
const selected = computed(() => palette[selectedColor.value]);
const colorUsage = computed(() => {
  const counts = new Map<number, number>();
  for (const index of pixels.value) {
    if (index >= 0 && palette[index]) counts.set(index, (counts.get(index) || 0) + 1);
  }
  return [...counts].map(([index, count]) => ({ index, count, ...palette[index] }))
    .sort((a, b) => b.count - a.count || a.index - b.index);
});
const statusLabel = (status: AnnotationStatus) => ({ unmodified: '未修改', pending: '待审核', human_edited: '已人工修改', qualified: '合格', unqualified: '不合格' })[status];
const imageUrl = (id: string, kind: string) => `/api/annotation/samples/${encodeURIComponent(id)}/image?kind=${kind}`;

function pickUsedColor(index: number) {
  selectedColor.value = index;
  tool.value = 'pencil';
  window.clearTimeout(flashTimer);
  flashedColor.value = index;
  draw();
  flashTimer = window.setTimeout(() => { flashedColor.value = null; }, 900);
}

async function request<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await fetch(url, init);
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || '请求失败');
  return data as T;
}

async function loadPage(page: number) {
  if (loadedPages.has(page) || loadingPages.has(page)) return;
  loadingPages.add(page);
  const version = cacheVersion;
  try {
    const params = new URLSearchParams({ offset: String(page * PAGE_SIZE), limit: String(PAGE_SIZE), q: query.value, size: sizeFilter.value });
    const result = await request<SamplePage>(`/api/annotation/samples?${params}`);
    if (version !== cacheVersion) return;
    const next = { ...sampleCache.value };
    result.items.forEach((item, offset) => { next[result.offset + offset] = item; });
    sampleCache.value = next;
    total.value = result.total;
    datasetTotal.value = result.all_total;
    completedCount.value = result.completed;
    loadedPages.add(page);
  } catch (cause) { if (version === cacheVersion) error.value = message(cause); }
  finally { if (version === cacheVersion) loadingPages.delete(page); }
}

async function ensureVisiblePages() {
  const first = Math.floor(visibleStart.value / PAGE_SIZE);
  const last = Math.floor(Math.max(visibleStart.value, visibleEnd.value - 1) / PAGE_SIZE);
  await Promise.all(Array.from({ length: last - first + 1 }, (_, offset) => loadPage(first + offset)));
}

async function refreshSamples(clear = false) {
  cacheVersion++;
  loadedPages.clear(); loadingPages.clear();
  if (clear) sampleCache.value = {};
  await ensureVisiblePages();
}

async function setSizeFilter(size: SizeFilter) {
  if (size === sizeFilter.value || busy.value || filterBusy.value) return;
  if (dirty.value && !window.confirm('当前修改尚未保存，确定切换尺寸吗？')) return;
  filterBusy.value = true;
  sizeFilter.value = size;
  localStorage.setItem('annotationSizeFilter', size);
  sample.value = null;
  selectedIndex.value = -1;
  if (listElement.value) listElement.value.scrollTop = 0;
  listScrollTop.value = 0;
  try {
    await refreshSamples(true);
    await loadPage(0);
    if (sampleCache.value[0]) await openSample(sampleCache.value[0].id, true, 0);
  } finally { filterBusy.value = false; }
}

function onListScroll() {
  if (!listElement.value) return;
  listScrollTop.value = listElement.value.scrollTop;
  void ensureVisiblePages();
}

async function openSample(id: string, force = false, index = -1) {
  if (busy.value) return;
  if (dirty.value && !force && !window.confirm('当前修改尚未保存，确定切换样本吗？')) return;
  if (activePointerId !== null) finishStroke(true);
  error.value = ''; notice.value = '';
  try {
    const loaded = await request<Sample>(`/api/annotation/samples/${encodeURIComponent(id)}`);
    sample.value = loaded;
    selectedIndex.value = index;
    pixels.value = [...(loaded.corrected_indices || loaded.indices)];
    savedPixels.value = [...pixels.value];
    undoStack.value = []; redoStack.value = []; hover.value = null;
    window.clearTimeout(flashTimer); flashedColor.value = null;
    await nextTick();
    if (viewport.value) {
      const fit = Math.floor(Math.min(
        (viewport.value.clientWidth - 24) / loaded.width,
        (viewport.value.clientHeight - 24) / loaded.height,
      ));
      zoom.value = Math.max(2, Math.min(20, fit));
    }
    draw();
    if (viewport.value) { viewport.value.scrollLeft = 0; viewport.value.scrollTop = 0; }
  } catch (cause) { error.value = message(cause); }
}

function message(cause: unknown) { return cause instanceof Error ? cause.message : String(cause); }

function draw() {
  if (!canvas.value || !sample.value) return;
  const { width, height } = sample.value;
  const size = zoom.value;
  const element = canvas.value;
  element.width = width * size; element.height = height * size;
  const ctx = element.getContext('2d');
  if (!ctx) return;
  ctx.imageSmoothingEnabled = false;
  for (let y = 0; y < height; y++) for (let x = 0; x < width; x++) {
    const i = y * width + x;
    ctx.fillStyle = pixels.value[i] === -1
      ? editorBackground.value === 'dark'
        ? ((x + y) % 2 ? '#343c40' : '#485257')
        : ((x + y) % 2 ? '#e3e9e8' : '#f6f8f7')
      : palette[pixels.value[i]]?.hex || '#ff00ff';
    ctx.fillRect(x * size, y * size, size, size);
  }
  if (flashedColor.value !== null) {
    ctx.fillStyle = 'rgba(255, 107, 51, .72)';
    for (let i = 0; i < pixels.value.length; i++) {
      if (pixels.value[i] === flashedColor.value) {
        ctx.fillRect((i % width) * size, Math.floor(i / width) * size, size, size);
      }
    }
  }
  if (grid.value && size >= 2) {
    ctx.strokeStyle = editorBackground.value === 'dark' ? 'rgba(220, 232, 229, .25)' : 'rgba(27, 43, 45, .17)'; ctx.lineWidth = 1; ctx.beginPath();
    for (let x = 0; x <= width; x++) { ctx.moveTo(x * size + .5, 0); ctx.lineTo(x * size + .5, height * size); }
    for (let y = 0; y <= height; y++) { ctx.moveTo(0, y * size + .5); ctx.lineTo(width * size, y * size + .5); }
    ctx.stroke();
  }
  if (hover.value) {
    ctx.strokeStyle = '#f07842'; ctx.lineWidth = 2;
    ctx.strokeRect(hover.value.x * size + 1, hover.value.y * size + 1, size - 2, size - 2);
  }
}
watch([pixels, zoom, grid, hover, flashedColor, editorBackground], draw, { deep: true });
watch(editorBackground, value => localStorage.setItem('annotationEditorBackground', value));

function position(event: PointerEvent) {
  if (!canvas.value || !sample.value) return null;
  const rect = canvas.value.getBoundingClientRect();
  const x = Math.floor((event.clientX - rect.left) / zoom.value);
  const y = Math.floor((event.clientY - rect.top) / zoom.value);
  return x >= 0 && y >= 0 && x < sample.value.width && y < sample.value.height ? { x, y } : null;
}

function paintLine(target: number[], from: PixelPosition, to: PixelPosition, color: number) {
  if (!sample.value) return;
  const width = sample.value.width;
  let x = from.x, y = from.y;
  const dx = Math.abs(to.x - x), dy = Math.abs(to.y - y);
  const stepX = x < to.x ? 1 : -1, stepY = y < to.y ? 1 : -1;
  let error = dx - dy;
  while (true) {
    target[y * width + x] = color;
    if (x === to.x && y === to.y) break;
    const doubled = error * 2;
    if (doubled > -dy) { error -= dy; x += stepX; }
    if (doubled < dx) { error += dx; y += stepY; }
  }
}

function paintRectangle(target: number[], from: PixelPosition, to: PixelPosition, color: number) {
  if (!sample.value) return;
  const width = sample.value.width;
  const left = Math.min(from.x, to.x), right = Math.max(from.x, to.x);
  const top = Math.min(from.y, to.y), bottom = Math.max(from.y, to.y);
  for (let x = left; x <= right; x++) { target[top * width + x] = color; target[bottom * width + x] = color; }
  for (let y = top; y <= bottom; y++) { target[y * width + left] = color; target[y * width + right] = color; }
}

function floodFill(pos: PixelPosition, color: number) {
  if (!sample.value) return;
  const { width, height } = sample.value;
  const start = pos.y * width + pos.x;
  const original = pixels.value[start];
  if (original === color) return;
  const queue = [start];
  pixels.value[start] = color;
  for (let head = 0; head < queue.length; head++) {
    const index = queue[head];
    const x = index % width, y = Math.floor(index / width);
    for (const neighbor of [x > 0 ? index - 1 : -1, x + 1 < width ? index + 1 : -1,
      y > 0 ? index - width : -1, y + 1 < height ? index + width : -1]) {
      if (neighbor >= 0 && pixels.value[neighbor] === original) {
        pixels.value[neighbor] = color;
        queue.push(neighbor);
      }
    }
  }
  draw();
}

function previewShape(pos: PixelPosition) {
  if (!strokeStart || !strokeAnchor || !strokeTool) return;
  const preview = [...strokeStart];
  if (strokeTool === 'line') paintLine(preview, strokeAnchor, pos, strokeColor);
  if (strokeTool === 'rectangle') paintRectangle(preview, strokeAnchor, pos, strokeColor);
  pixels.value = preview;
  draw();
}

function finishStroke(cancel = false) {
  panning = false;
  activePointerId = null;
  if (strokeStart) {
    if (cancel) pixels.value = strokeStart;
    else if (strokeStart.some((value, i) => value !== pixels.value[i])) {
      undoStack.value.push(strokeStart);
      if (undoStack.value.length > 100) undoStack.value.shift();
      redoStack.value = [];
    }
  }
  strokeStart = null; strokeAnchor = null; strokeLast = null; strokeTool = null;
  if (cancel) draw();
}

function pointerDown(event: PointerEvent) {
  if (!sample.value || !viewport.value || activePointerId !== null) return;
  if (event.button === 1 || (event.button === 0 && spaceHeld)) {
    panning = true;
    activePointerId = event.pointerId;
    panStart = { x: event.clientX, y: event.clientY, left: viewport.value.scrollLeft, top: viewport.value.scrollTop };
    canvas.value?.setPointerCapture(event.pointerId); event.preventDefault(); return;
  }
  if (event.button !== 0) return;
  const pos = position(event);
  if (!pos) return;
  if (tool.value === 'picker') {
    const picked = pixels.value[pos.y * sample.value.width + pos.x];
    if (picked >= 0) { selectedColor.value = picked; tool.value = 'pencil'; }
    else tool.value = 'eraser';
    return;
  }
  strokeStart = [...pixels.value];
  strokeAnchor = pos; strokeLast = pos; strokeTool = tool.value;
  strokeColor = tool.value === 'eraser' ? -1 : selectedColor.value;
  if (tool.value === 'fill') { floodFill(pos, strokeColor); finishStroke(); return; }
  activePointerId = event.pointerId;
  if (tool.value === 'pencil' || tool.value === 'eraser') { paintLine(pixels.value, pos, pos, strokeColor); draw(); }
  else previewShape(pos);
  canvas.value?.setPointerCapture(event.pointerId);
  event.preventDefault();
}

function pointerMove(event: PointerEvent) {
  if (panning && activePointerId === event.pointerId && viewport.value) {
    viewport.value.scrollLeft = panStart.left - (event.clientX - panStart.x);
    viewport.value.scrollTop = panStart.top - (event.clientY - panStart.y); return;
  }
  hover.value = position(event);
  if (strokeStart && activePointerId === event.pointerId && hover.value) {
    if (strokeTool === 'pencil' || strokeTool === 'eraser') {
      paintLine(pixels.value, strokeLast || hover.value, hover.value, strokeColor);
      draw();
    } else previewShape(hover.value);
    strokeLast = hover.value;
  }
}

function pointerUp(event: PointerEvent) {
  if (activePointerId !== event.pointerId) return;
  const pos = position(event);
  if (strokeStart && pos) {
    if (strokeTool === 'line' || strokeTool === 'rectangle') previewShape(pos);
    else if (strokeLast) paintLine(pixels.value, strokeLast, pos, strokeColor);
  }
  finishStroke();
}

function pointerCancel(event: PointerEvent) { if (activePointerId === event.pointerId) finishStroke(true); }

function undo() {
  const previous = undoStack.value.pop(); if (!previous) return;
  redoStack.value.push([...pixels.value]); pixels.value = previous;
}
function redo() {
  const next = redoStack.value.pop(); if (!next) return;
  undoStack.value.push([...pixels.value]); pixels.value = next;
}
function replacePixels(next: number[]) {
  if (!sample.value || next.every((value, i) => value === pixels.value[i])) return;
  undoStack.value.push([...pixels.value]); redoStack.value = []; pixels.value = next;
}
function reset() { if (sample.value) replacePixels([...sample.value.indices]); }
function clear() { if (sample.value && window.confirm('清空整张画布的像素吗？')) replacePixels(Array(pixels.value.length).fill(-1)); }
function cleanEdges() {
  if (!sample.value || busy.value) return;
  const result = cleanColorFringe(
    pixels.value, sample.value.width, sample.value.height, palette.map(color => color.hex),
  );
  if (!result) { notice.value = '未识别到适合自动描边的单色主体'; return; }
  if (!result.outlinePixels && !result.clearedPixels) { notice.value = '没有需要清理的彩边'; return; }
  replacePixels(result.pixels);
  notice.value = `已生成 ${result.outlinePixels} 个黑色描边像素，清理 ${result.clearedPixels} 个彩边像素`;
}
function removeBackground() {
  if (!sample.value || busy.value) return;
  const { width, height } = sample.value;
  const borderCounts = new Map<number, number>();
  const countBorder = (index: number) => {
    const color = pixels.value[index];
    if (color >= 0) borderCounts.set(color, (borderCounts.get(color) || 0) + 1);
  };
  for (let x = 0; x < width; x++) {
    countBorder(x);
    if (height > 1) countBorder((height - 1) * width + x);
  }
  for (let y = 1; y < height - 1; y++) {
    countBorder(y * width);
    if (width > 1) countBorder(y * width + width - 1);
  }
  if (!borderCounts.size) { notice.value = '边缘没有可识别的背景颜色'; return; }

  let background = -1, maxCount = -1;
  for (const [color, count] of borderCounts) {
    if (count > maxCount) { background = color; maxCount = count; }
  }
  const next = [...pixels.value];
  const stack: number[] = [];
  const pushIfBackground = (index: number) => {
    if (next[index] !== background) return;
    next[index] = -1;
    stack.push(index);
  };
  for (let x = 0; x < width; x++) {
    pushIfBackground(x);
    if (height > 1) pushIfBackground((height - 1) * width + x);
  }
  for (let y = 1; y < height - 1; y++) {
    pushIfBackground(y * width);
    if (width > 1) pushIfBackground(y * width + width - 1);
  }
  for (let head = 0; head < stack.length; head++) {
    const index = stack[head];
    const x = index % width, y = Math.floor(index / width);
    if (x > 0) pushIfBackground(index - 1);
    if (x + 1 < width) pushIfBackground(index + 1);
    if (y > 0) pushIfBackground(index - width);
    if (y + 1 < height) pushIfBackground(index + width);
  }
  if (!stack.length) { notice.value = '未找到可去除的背景区域'; return; }
  replacePixels(next);
  notice.value = `已去除 ${stack.length} 个背景像素，可撤销或继续修正`;
}
function changeZoom(delta: number) { zoom.value = Math.max(2, Math.min(28, zoom.value + delta)); }
function wheel(event: WheelEvent) { event.preventDefault(); changeZoom(event.deltaY < 0 ? 1 : -1); }

async function save(accept = false): Promise<boolean> {
  if (!sample.value || busy.value) return false;
  if (accept && dirty.value && !window.confirm('直接通过会舍弃当前修改，继续吗？')) return false;
  busy.value = true; error.value = ''; notice.value = '';
  try {
    const id = sample.value.id;
    const wasRejected = sample.value.status === 'unqualified';
    const saved = accept ? [...sample.value.indices] : [...pixels.value];
    const result = await request<{ changed_pixels: number }>(`/api/annotation/samples/${encodeURIComponent(id)}/save`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ accept, indices: saved }),
    });
    await refreshSamples();
    // Saving a rejected sample removes it from the priority section. Start
    // Next from the new head so no other rejected sample is skipped.
    if (wasRejected) selectedIndex.value = -1;
    if (sample.value?.id === id) {
      if (accept) pixels.value = saved;
      savedPixels.value = saved;
      sample.value.status = accept ? 'pending' : 'human_edited';
      sample.value.corrected_indices = saved;
    }
    notice.value = `${id} 已${accept ? '送审核' : '保存为已人工修改'} · ${result.changed_pixels} 处修改`;
    return true;
  } catch (cause) { error.value = message(cause); return false; }
  finally { busy.value = false; }
}

async function nextSample(force = false) {
  if (busy.value || !total.value) return;
  const index = (selectedIndex.value + 1) % total.value;
  await loadPage(Math.floor(index / PAGE_SIZE));
  const next = sampleCache.value[index];
  if (next) {
    await openSample(next.id, force, index);
    if (listElement.value) listElement.value.scrollTop = index * ROW_HEIGHT;
  }
}
async function updateStatus(nextStatus: 'pending' | 'human_edited') {
  if (!sample.value || busy.value || sample.value.status === nextStatus) return;
  busy.value = true; error.value = ''; notice.value = '';
  try {
    const id = sample.value.id;
    await request<{ success: boolean; status: string }>(`/api/annotation/samples/${encodeURIComponent(id)}/status`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ status: nextStatus }),
    });
    if (sample.value?.id === id) {
      sample.value.status = nextStatus;
    }
    await refreshSamples();
    const label = nextStatus === 'pending' ? '待审核' : '已人工修改';
    notice.value = `${id} 状态已更新为「${label}」`;
  } catch (cause) {
    error.value = message(cause);
  } finally {
    busy.value = false;
  }
}

async function saveAndNext() { if (busy.value || !sample.value) return; if (await save()) await nextSample(true); }
async function acceptAndNext() { if (busy.value || !sample.value) return; if (await save(true)) await nextSample(true); }

function fileData(file: File): Promise<string> {
  return new Promise((resolve, reject) => { const reader = new FileReader(); reader.onload = () => resolve(String(reader.result)); reader.onerror = reject; reader.readAsDataURL(file); });
}
function onSource(event: Event) { sourceFile.value = (event.target as HTMLInputElement).files?.[0] || null; if (sourceFile.value && !importId.value) importId.value = sourceFile.value.name.replace(/\.png$/i, ''); }
function onPrediction(event: Event) { predictionFile.value = (event.target as HTMLInputElement).files?.[0] || null; }
async function importPair() {
  if (!sourceFile.value || !predictionFile.value) { error.value = '请选择原图和预测 PNG'; return; }
  busy.value = true; error.value = '';
  try {
    const [source, prediction] = await Promise.all([fileData(sourceFile.value), fileData(predictionFile.value)]);
    const result = await request<{ id: string }>('/api/annotation/samples', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ id: importId.value, model_version: modelVersion.value, source, prediction }),
    });
    sampleSearch.value = result.id; query.value = result.id;
    if (listElement.value) listElement.value.scrollTop = 0;
    listScrollTop.value = 0;
    await refreshSamples(true); importOpen.value = false; sourceFile.value = null; predictionFile.value = null; importId.value = '';
    busy.value = false;
    await openSample(result.id, true, 0);
  } catch (cause) { error.value = message(cause); }
  finally { busy.value = false; }
}

function keydown(event: KeyboardEvent) {
  const target = event.target as HTMLElement;
  if (['INPUT', 'TEXTAREA', 'SELECT'].includes(target.tagName) || event.altKey) return;
  if (event.code === 'Space') { spaceHeld = true; event.preventDefault(); return; }
  const key = event.key.toLowerCase();
  if ((event.ctrlKey || event.metaKey) && key === 'z') { event.preventDefault(); event.shiftKey ? redo() : undo(); return; }
  if (event.ctrlKey || event.metaKey) return;
  if (key === 'b') tool.value = 'pencil';
  else if (key === 'e') tool.value = 'eraser';
  else if (key === 'i') tool.value = 'picker';
  else if (key === 'l') tool.value = 'line';
  else if (key === 'r') tool.value = 'rectangle';
  else if (key === 'f') tool.value = 'fill';
  else if (key === 'g') { event.preventDefault(); removeBackground(); }
  else if (key === 'j') { event.preventDefault(); cleanEdges(); }
  else if (key === 'a') { event.preventDefault(); void acceptAndNext(); }
  else if (key === 's') { event.preventDefault(); void save(); }
  else if (key === 'n') { event.preventDefault(); void nextSample(); }
}
function keyup(event: KeyboardEvent) { if (event.code === 'Space') spaceHeld = false; }
function beforeUnload(event: BeforeUnloadEvent) { if (dirty.value) { event.preventDefault(); event.returnValue = ''; } }
watch(sampleSearch, value => {
  if (query.value === value.trim()) return;
  window.clearTimeout(searchTimer);
  searchTimer = window.setTimeout(() => {
    query.value = value.trim();
    if (listElement.value) listElement.value.scrollTop = 0;
    listScrollTop.value = 0;
    selectedIndex.value = -1;
    void refreshSamples(true);
  }, 250);
});
onMounted(async () => {
  window.addEventListener('keydown', keydown); window.addEventListener('keyup', keyup); window.addEventListener('beforeunload', beforeUnload);
  const requestedId = new URLSearchParams(window.location.search).get('q') || '';
  if (requestedId) { sampleSearch.value = requestedId; query.value = requestedId; }
  const storedSize = localStorage.getItem('annotationSizeFilter');
  if (storedSize === '24' || storedSize === '52' || storedSize === '78' || storedSize === '104') sizeFilter.value = storedSize;
  if (localStorage.getItem('annotationEditorBackground') === 'dark') editorBackground.value = 'dark';
  listHeight.value = listElement.value?.clientHeight || 500;
  if (listElement.value) {
    listResizeObserver = new ResizeObserver(() => {
      listHeight.value = listElement.value?.clientHeight || 500;
      void ensureVisiblePages();
    });
    listResizeObserver.observe(listElement.value);
  }
  try { await refreshSamples(); if (sampleCache.value[0]) await openSample(sampleCache.value[0].id, false, 0); } catch (cause) { error.value = message(cause); }
  refreshTimer = window.setInterval(() => { if (!busy.value) void refreshSamples(); }, 15000);
});
onUnmounted(() => { window.removeEventListener('keydown', keydown); window.removeEventListener('keyup', keyup); window.removeEventListener('beforeunload', beforeUnload); window.clearInterval(refreshTimer); window.clearTimeout(searchTimer); window.clearTimeout(flashTimer); listResizeObserver?.disconnect(); });
</script>

<template>
  <div class="annotator">
    <header class="topbar">
      <div class="brand"><span class="brand-mark">▦</span><div><strong>Pixel Review</strong><small>拼豆图纠错工作台</small></div></div>
      <a class="review-link" href="/review">最终审核</a><div class="top-status"><span class="status-dot"></span> 本地数据集 <b>{{ completedCount }} / {{ datasetTotal }}</b> 已完成</div>
      <button class="primary import-button" @click="importOpen = true">＋ 导入样本</button>
    </header>

    <div v-if="error" class="alert error" role="alert">{{ error }} <button @click="error = ''">×</button></div>
    <div v-if="notice" class="alert success" role="status">{{ notice }} <button @click="notice = ''">×</button></div>

    <div class="workspace">
      <aside class="sample-rail">
        <div class="rail-heading"><div><span class="eyebrow">QUEUE</span><h2>样本队列</h2></div><span class="count">{{ total.toLocaleString() }}</span></div>
        <label class="search"><svg class="search-icon" viewBox="0 0 20 20" fill="none" aria-hidden="true"><circle cx="8.5" cy="8.5" r="5.5" stroke="currentColor" stroke-width="1.7"/><path d="m13 13 4.5 4.5" stroke="currentColor" stroke-width="1.7" stroke-linecap="round"/></svg><input v-model="sampleSearch" placeholder="搜索样本 ID" aria-label="搜索样本 ID"></label>
        <div class="size-filter" role="group" aria-label="按像素尺寸筛选"><button v-for="option in sizeOptions" :key="option.value" type="button" :disabled="filterBusy" :class="{ active: sizeFilter === option.value }" :aria-pressed="sizeFilter === option.value" @click="setSizeFilter(option.value)">{{ option.label }}<span v-if="option.value">px</span></button></div>
        <div v-if="!datasetTotal" class="empty-rail">还没有样本。<br>点击右上角导入一组原图与预测图。</div>
        <div v-else-if="!total" class="empty-rail">没有匹配的样本。</div>
        <div ref="listElement" class="sample-list" @scroll="onListScroll">
          <div :style="{ height: `${visibleStart * ROW_HEIGHT}px` }"></div>
          <button v-for="row in visibleRows" :key="row.index" class="sample-row" :class="{ active: sample?.id === row.item?.id, loading: !row.item }" :disabled="!row.item" @click="row.item && openSample(row.item.id, false, row.index)">
            <span class="row-number">{{ String(row.index + 1).padStart(5, '0') }}</span>
            <span class="thumb"><img v-if="row.item" :src="imageUrl(row.item.id, 'predictions')" alt=""></span>
            <span class="sample-info"><strong>{{ row.item?.id || '载入中…' }}</strong><small v-if="row.item">{{ row.item.width }} × {{ row.item.height }} · {{ row.item.model_version }}</small></span>
            <span v-if="row.item" class="state" :class="row.item.status" :title="row.item.status">{{ statusLabel(row.item.status) }}</span>
          </button>
          <div :style="{ height: `${Math.max(0, total - visibleEnd) * ROW_HEIGHT}px` }"></div>
        </div>
        <div class="rail-foot">数据保存在 <code>webui/data/</code></div>
      </aside>

      <main v-if="sample" class="main-area">
        <div class="work-heading"><div><span class="eyebrow">ANNOTATION / {{ sample.id }}</span><h1>审阅与纠错</h1><p>按逻辑像素修正模型结果。保存时自动生成修正图与编辑 mask。</p></div><div class="heading-meta"><span>{{ sample.width }} × {{ sample.height }}</span><span>{{ sample.model_version }}</span><label class="status-select-wrap" :class="sample.status" title="保存后可切换待审核与已人工修改；最终结果在审核页确认"><span class="status-indicator"></span><select :value="sample.status" :disabled="busy || !sample.corrected_indices || sample.status === 'qualified' || sample.status === 'unqualified'" aria-label="样本状态" @change="updateStatus(($event.target as HTMLSelectElement).value as 'pending' | 'human_edited')"><option value="unmodified" disabled>未修改</option><option value="pending">待审核</option><option value="human_edited">已人工修改</option><option value="qualified" disabled>合格 · 在最终审核页设置</option><option value="unqualified" disabled>不合格 · 在最终审核页设置</option></select></label></div></div>
        <div v-if="sample.review_reason" class="review-reason"><strong>上次不合格原因：</strong>{{ sample.review_reason }}</div>
        <div class="boards">
          <section class="board source-board"><div class="board-title"><div><span class="section-number">01</span><h2>原图</h2></div><span>参考图像</span></div><div class="source-stage"><img :src="imageUrl(sample.id, 'sources')" alt="原图"></div><div class="board-caption">观察主体、轮廓与关键细节</div></section>
          <section class="board editor-board"><div class="board-title"><div><span class="section-number">02</span><h2>模型输出 · 可编辑</h2></div><span class="modified">{{ changedPixels }} 像素已修改</span></div>
            <div ref="viewport" class="canvas-viewport" :class="{ 'dark-background': editorBackground === 'dark' }" @wheel="wheel"><canvas ref="canvas" class="pixel-canvas" :class="{ panning: spaceHeld }" aria-label="可编辑像素画布" @pointerdown="pointerDown" @pointermove="pointerMove" @pointerup="pointerUp" @pointercancel="pointerCancel" @pointerleave="hover = null" @contextmenu.prevent></canvas></div>
            <div class="canvas-footer"><span>{{ hover ? `(${hover.x}, ${hover.y})` : '移动鼠标查看坐标' }}</span><div><button title="缩小" @click="changeZoom(-1)">−</button><span>{{ zoom }}×</span><button title="放大" @click="changeZoom(1)">＋</button></div><div class="background-switch" role="group" aria-label="编辑背景"><span>背景</span><button type="button" :class="{ active: editorBackground === 'light' }" :aria-pressed="editorBackground === 'light'" @click="editorBackground = 'light'">浅色</button><button type="button" :class="{ active: editorBackground === 'dark' }" :aria-pressed="editorBackground === 'dark'" @click="editorBackground = 'dark'">深色</button></div><label><input v-model="grid" type="checkbox"> 网格</label></div>
          </section>
        </div>
        <div class="action-bar"><div class="action-hint">{{ dirty ? '当前修改尚未保存' : '当前无未保存修改' }} <span>· 空格拖动画布，滚轮缩放</span></div><div class="action-buttons"><button class="quiet" @click="nextSample()">跳过 / 下一张 <kbd>N</kbd></button><button class="quiet" :disabled="busy" @click="save()">保存 <kbd>S</kbd></button><button class="secondary" :disabled="busy" @click="saveAndNext()">保存并下一张</button><button class="primary" :disabled="busy" @click="acceptAndNext()">无需修改，送审核 <kbd>A</kbd></button></div></div>
      </main>
      <main v-else class="main-area welcome"><div class="welcome-icon">▦</div><h1>{{ filterBusy ? '正在载入样本' : datasetTotal ? '当前筛选没有样本' : '开始构建纠错数据集' }}</h1><p>{{ filterBusy ? '正在读取这个尺寸的样本队列。' : datasetTotal ? '试试其他尺寸，或清除搜索条件。' : '导入一张原图和对应的逻辑像素预测 PNG，随后即可逐格修改并保存训练数据。' }}</p><button v-if="!datasetTotal" class="primary" @click="importOpen = true">导入第一条样本</button></main>

      <aside class="tools-rail" :class="{ disabled: !sample }"><div class="tool-section"><span class="eyebrow">TOOLS</span><h2>编辑工具</h2><div class="tool-list"><button :class="{ selected: tool === 'pencil' }" @click="tool = 'pencil'"><svg class="tool-icon" viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M14.2 2.8a2.1 2.1 0 0 1 3 3L6.5 16.5l-4 1 1-4L14.2 2.8z"/><path d="m12 5 3 3"/></svg> 铅笔 <kbd>B</kbd></button><button :class="{ selected: tool === 'eraser' }" @click="tool = 'eraser'"><svg class="tool-icon" viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="m6 16.5-3.5-3.5a1.8 1.8 0 0 1 0-2.5l7.5-7.5a1.8 1.8 0 0 1 2.5 0l4.5 4.5a1.8 1.8 0 0 1 0 2.5L11.5 16.5"/><path d="M17.5 16.5H6"/><path d="m5 10 6.5 6.5"/></svg> 橡皮 <kbd>E</kbd></button><button :class="{ selected: tool === 'picker' }" @click="tool = 'picker'"><svg class="tool-icon" viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="m11 5.5 1.8-1.8a2 2 0 1 1 2.8 2.8L13.8 8.3"/><path d="m12 6.5-6.8 6.8c-.3.3-.5.7-.6 1.1L4 16.5l2.1-.6c.4-.1.8-.3 1.1-.6l6.8-6.8"/><path d="m9.5 9 1.5 1.5"/></svg> 取色 <kbd>I</kbd></button><button :class="{ selected: tool === 'line' }" @click="tool = 'line'"><svg class="tool-icon" viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><line x1="4.5" y1="15.5" x2="15.5" y2="4.5"/><circle cx="4.5" cy="15.5" r="1.8" fill="currentColor"/><circle cx="15.5" cy="4.5" r="1.8" fill="currentColor"/></svg> 直线 <kbd>L</kbd></button><button :class="{ selected: tool === 'rectangle' }" @click="tool = 'rectangle'"><svg class="tool-icon" viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="3" y="4" width="14" height="12" rx="2.5"/></svg> 矩形 <kbd>R</kbd></button><button :class="{ selected: tool === 'fill' }" @click="tool = 'fill'"><svg class="tool-icon" viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="m14 8.5-5.5-5.5-6 6a1.8 1.8 0 0 0 0 2.5l4 4a1.8 1.8 0 0 0 2.5 0L14 8.5z"/><path d="M4 3 7.5 6.5"/><path d="M2.5 9.5h10"/><path d="M16.8 14.2c0 1.2-.9 2-2 2s-2-.8-2-2c0-1.2 2-3.4 2-3.4s2 2.2 2 3.4z" fill="currentColor" stroke="none"/></svg> 填充 <kbd>F</kbd></button><button class="background-tool" :disabled="!sample || busy" title="移除与边缘主色连通的背景像素" @click="removeBackground"><svg class="tool-icon" viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="m13 4 3 3L6 17l-3 1 1-3L13 4z"/><path d="m11 6 3 3"/><path d="M10 2v2M18 10h-2M15 2.5l1.5 1.5M3 8.5l1.5 1.5"/></svg> 一键去背景 <kbd>G</kbd></button><button class="background-tool" :disabled="!sample || busy" title="识别单色主体，将轮廓彩边变为黑色描边并清除外层杂色" @click="cleanEdges"><svg class="tool-icon" viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="m10 2.2 2.2 4.6 5 .6-3.8 3.5 1.1 5-4.5-2.5-4.5 2.5 1.1-5-3.8-3.5 5-.6L10 2.2z" stroke-width="1.8"/><circle cx="16" cy="3.5" r="1.2" fill="currentColor"/></svg> 净化彩边 <kbd>J</kbd></button></div><div class="history"><button :disabled="!undoStack.length" @click="undo()"><svg class="btn-icon" viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M4 8h8a4.5 4.5 0 0 1 4.5 4.5v0a4.5 4.5 0 0 1-4.5 4.5H8"/><path d="m7.5 4.5-3.5 3.5 3.5 3.5"/></svg>撤销</button><button :disabled="!redoStack.length" @click="redo()"><svg class="btn-icon" viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M16 8H8a4.5 4.5 0 0 0-4.5 4.5v0A4.5 4.5 0 0 0 8 17h4"/><path d="m12.5 4.5 3.5 3.5-3.5 3.5"/></svg>重做</button></div><div class="history"><button :disabled="!sample" @click="reset()"><svg class="btn-icon" viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M2.5 10a7.5 7.5 0 1 0 2.2-5.3L2.5 7"/><path d="M2.5 2.5V7H7"/></svg>重置预测</button><button :disabled="!sample" @click="clear()"><svg class="btn-icon" viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M3 5.5h14M7 5.5V3.5a1 1 0 0 1 1-1h4a1 1 0 0 1 1 1v2M15 5.5v10.5a1.5 1.5 0 0 1-1.5 1.5h-7A1.5 1.5 0 0 1 5 16V5.5"/><path d="M8 9v5M12 9v5"/></svg>清空画布</button></div></div>
        <div class="tool-section usage-section"><span class="eyebrow">CURRENT IMAGE · {{ colorUsage.length }}</span><h2>画布用色</h2><p class="usage-help">按数量排序 · 点击取色并闪烁定位</p><div v-if="sample && colorUsage.length" class="usage-list"><button v-for="color in colorUsage" :key="color.index" class="usage-row" :class="{ active: selectedColor === color.index && tool === 'pencil' }" :title="`${color.code} · ${color.hex} · index ${color.index}`" :aria-label="`取色 ${color.code}，${color.count} 格`" @click="pickUsedColor(color.index)"><span class="usage-swatch" :style="{ background: color.hex }"></span><span class="usage-code">{{ color.code }}<small>#{{ color.index }}</small></span><span class="usage-count">{{ color.count }} <small>格</small></span></button></div><p v-else class="usage-empty">画布暂无颜色</p></div>
        <div class="tool-section palette-section"><span class="eyebrow">MARD PALETTE · {{ palette.length }}</span><h2>固定调色板</h2><div class="chosen"><span class="chosen-swatch" :style="{ background: selected?.hex }"></span><div><strong>{{ selected?.code }}</strong><small>Index {{ selectedColor }} · {{ selected?.hex }}</small></div></div><label class="search"><svg class="search-icon" viewBox="0 0 20 20" fill="none" aria-hidden="true"><circle cx="8.5" cy="8.5" r="5.5" stroke="currentColor" stroke-width="1.7"/><path d="m13 13 4.5 4.5" stroke="currentColor" stroke-width="1.7" stroke-linecap="round"/></svg><input v-model="paletteSearch" placeholder="搜索色号 / HEX" aria-label="搜索调色板"></label><div class="swatches"><button v-for="color in filteredPalette" :key="color.index" class="swatch" :class="{ active: selectedColor === color.index }" :style="{ background: color.hex }" :title="`${color.code} · ${color.hex} · index ${color.index}`" :aria-label="`选择 ${color.code}`" @click="selectedColor = color.index; tool = 'pencil'"></button></div><button class="transparent" @click="tool = 'eraser'"><svg class="checker-icon" viewBox="0 0 20 20" aria-hidden="true"><rect width="20" height="20" rx="3" fill="#eef3f0"/><rect x="0" y="0" width="10" height="10" rx="1" fill="#cdd8d4"/><rect x="10" y="10" width="10" height="10" rx="1" fill="#cdd8d4"/></svg>透明 / 空白像素</button></div>
      </aside>
    </div>

    <div v-if="importOpen" class="modal-backdrop" @click.self="importOpen = false"><div class="import-modal" role="dialog" aria-modal="true" aria-label="导入样本"><button class="close" @click="importOpen = false">×</button><span class="eyebrow">NEW SAMPLE</span><h2>导入样本</h2><p>原图用于参考；预测图必须是逻辑像素尺寸的 PNG，导入时会映射到 MARD 色板。</p><label>样本 ID<input v-model="importId" placeholder="例如 000001"></label><label>模型版本<input v-model="modelVersion" placeholder="例如 v0.1"></label><div class="file-row"><label>原图 PNG<input type="file" accept="image/png" @change="onSource"></label><label>预测 PNG<input type="file" accept="image/png" @change="onPrediction"></label></div><button class="primary" :disabled="busy" @click="importPair()">{{ busy ? '导入中…' : '导入并开始标注' }}</button></div></div>
  </div>
</template>

<style scoped>
.annotator{--ink:#1f3031;--muted:#738080;--line:#dfe6e4;--accent:#e96f43;min-height:100vh;background:#f5f7f6;color:var(--ink);font-family:Inter,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}.annotator *{box-sizing:border-box}button,input{font:inherit}button{cursor:pointer}.topbar{height:72px;background:#fff;border-bottom:1px solid var(--line);display:flex;align-items:center;justify-content:space-between;padding:0 26px;gap:16px}.brand{display:flex;align-items:center;gap:12px}.brand-mark{display:grid;place-items:center;width:38px;height:38px;border-radius:10px;background:#183d3c;color:#fff;font-size:24px}.brand strong{display:block;font-size:17px;letter-spacing:-.04em}.brand small{display:block;color:var(--muted);font-size:11px;margin-top:2px}.top-status{color:var(--muted);font-size:13px}.top-status b{color:var(--ink);margin-left:6px}.status-dot{display:inline-block;width:7px;height:7px;background:#48b88a;border-radius:50%;margin-right:6px}.primary,.secondary,.quiet{border-radius:9px;padding:11px 15px;font-weight:650;font-size:13px}.primary{border:1px solid #173e3d;background:#173e3d;color:#fff}.primary:hover{background:#245a56}.secondary{border:1px solid #e96f43;background:#e96f43;color:#fff}.secondary:hover{background:#d75f36}.quiet{background:#fff;color:#3f5050;border:1px solid var(--line)}.quiet:hover{border-color:#aabbb8}.workspace{display:grid;grid-template-columns:244px minmax(500px,1fr) 260px;min-height:calc(100vh - 72px)}.sample-rail,.tools-rail{background:#fff}.sample-rail{border-right:1px solid var(--line);display:flex;flex-direction:column;min-width:0}.tools-rail{border-left:1px solid var(--line);overflow:auto}.rail-heading{display:flex;align-items:end;justify-content:space-between;padding:25px 18px 14px}.eyebrow{display:block;color:#9aa9a6;font-size:10px;font-weight:800;letter-spacing:.16em}.rail-heading h2,.tool-section h2{margin:5px 0 0;font-size:16px;letter-spacing:-.03em}.count{font-size:12px;color:var(--muted);background:#eef3f1;border-radius:6px;padding:3px 7px}.search{margin:0 14px 12px;position:relative;display:block}.search span{position:absolute;left:11px;top:6px;color:#899896;font-size:21px}.search input{width:100%;height:36px;background:#f7f9f8;border:1px solid #e8edeb;border-radius:8px;padding:0 9px 0 35px;outline:none;font-size:12px;color:var(--ink)}.search input:focus{border-color:#80aaa3}.sample-list{overflow:auto;flex:1}.sample-row{width:100%;border:0;border-left:3px solid transparent;background:#fff;padding:10px 12px;display:flex;align-items:center;text-align:left;gap:10px}.sample-row:hover{background:#f6f9f8}.sample-row.active{background:#eaf3ef;border-left-color:#e96f43}.thumb{width:41px;height:41px;flex:none;border-radius:6px;background:#ecf0ed;overflow:hidden;display:grid;place-items:center}.thumb img{width:100%;height:100%;object-fit:contain;image-rendering:pixelated}.sample-info{min-width:0;flex:1}.sample-info strong{display:block;font-size:12px;overflow:hidden;text-overflow:ellipsis}.sample-info small{display:block;color:var(--muted);font-size:10px;white-space:nowrap;margin-top:4px}.state{font-size:10px;color:#899593;white-space:nowrap}.state.accepted{color:#2b9b74}.state.edited{color:#dc7751}.rail-foot{border-top:1px solid var(--line);padding:14px;color:#8c9996;font-size:11px}.rail-foot code{font-size:10px}.empty-rail{padding:18px;color:var(--muted);font-size:12px;line-height:1.7}.main-area{padding:28px 30px 24px;min-width:0;display:flex;flex-direction:column}.work-heading{display:flex;justify-content:space-between;align-items:end;gap:20px;margin-bottom:23px}.work-heading h1{font-size:26px;letter-spacing:-.055em;margin:7px 0}.work-heading p{color:var(--muted);font-size:12px;margin:0}.heading-meta{display:flex;gap:7px}.heading-meta span{background:#eaf0ed;border:1px solid #dde7e2;border-radius:6px;padding:6px 8px;font-size:11px;color:#56716b;white-space:nowrap}.boards{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1.25fr);gap:16px;flex:none;height:clamp(410px,calc(100vh - 300px),680px)}.board{background:white;border:1px solid var(--line);border-radius:13px;overflow:hidden;display:flex;flex-direction:column;min-width:0}.board-title{height:57px;padding:0 17px;display:flex;justify-content:space-between;align-items:center;border-bottom:1px solid var(--line);font-size:11px;color:#8a9995}.board-title>div{display:flex;align-items:center;gap:10px}.board-title h2{color:var(--ink);font-size:14px;margin:0}.section-number{font-size:10px;font-weight:800;color:var(--accent)}.modified{color:#df6b45}.source-stage,.canvas-viewport{min-height:350px;flex:1;display:flex;align-items:center;justify-content:center;overflow:auto;background-color:#f6f8f7;background-image:linear-gradient(45deg,#eef2f0 25%,transparent 25%),linear-gradient(-45deg,#eef2f0 25%,transparent 25%),linear-gradient(45deg,transparent 75%,#eef2f0 75%),linear-gradient(-45deg,transparent 75%,#eef2f0 75%);background-size:24px 24px;background-position:0 0,0 12px,12px -12px,-12px 0}.source-stage{padding:20px}.source-stage img{max-width:100%;max-height:calc(100vh - 310px);object-fit:contain;box-shadow:0 10px 28px #2d4b4320}.pixel-canvas{display:block;flex:none;margin:auto;image-rendering:pixelated;touch-action:none;cursor:crosshair;box-shadow:0 9px 30px #334e4430}.pixel-canvas.panning{cursor:grab}.board-caption,.canvas-footer{height:43px;display:flex;align-items:center;padding:0 15px;font-size:11px;color:#7d8d89;border-top:1px solid var(--line)}.canvas-footer{justify-content:space-between}.canvas-footer>div{display:flex;align-items:center;gap:7px;color:#344e4a}.canvas-footer button{border:0;background:#eef3f1;color:#33514b;width:23px;height:23px;border-radius:5px}.canvas-footer label{white-space:nowrap}.canvas-footer input{accent-color:#2a635b;vertical-align:middle}.action-bar{display:flex;justify-content:space-between;align-items:center;gap:16px;padding-top:18px}.action-hint{font-size:11px;color:#788883}.action-hint span{color:#a5b2ae}.action-buttons{display:flex;gap:8px;flex-wrap:wrap;justify-content:end}kbd{font-size:10px;opacity:.65;margin-left:4px;font-family:inherit}.tools-rail.disabled{opacity:.65}.tool-section{padding:25px 18px;border-bottom:1px solid var(--line)}.tool-list{display:grid;gap:6px;margin-top:17px}.tool-list button{height:38px;display:flex;align-items:center;text-align:left;gap:10px;padding:0 10px;border:1px solid transparent;border-radius:7px;background:#fff;color:#52615f;font-size:12px}.tool-list button span{font-size:17px;width:20px;text-align:center}.tool-list button kbd{margin-left:auto}.tool-list button.selected{background:#eaf3ef;border-color:#d7e7df;color:#1e554c;font-weight:700}.history{display:flex;gap:7px;margin-top:11px}.history button{flex:1;background:#f8faf9;border:1px solid #e4ebe7;border-radius:7px;padding:8px 3px;color:#536561;font-size:11px}.history button:disabled{opacity:.45;cursor:default}.chosen{display:flex;align-items:center;gap:11px;padding:12px;margin:15px 0;background:#f7f9f8;border:1px solid var(--line);border-radius:9px}.chosen-swatch{width:34px;height:34px;border-radius:6px;border:1px solid #0001}.chosen strong{display:block;font-size:13px}.chosen small{color:var(--muted);font-size:10px}.palette-section .search{margin:0 0 12px}.swatches{display:grid;grid-template-columns:repeat(8,1fr);gap:5px;max-height:250px;overflow:auto;padding:2px}.swatch{aspect-ratio:1;border:1px solid #0002;border-radius:4px;min-width:0}.swatch.active{outline:2px solid #e46a40;outline-offset:1px}.transparent{width:100%;margin-top:13px;padding:9px;background:#fff;border:1px solid var(--line);border-radius:7px;color:#526560;font-size:11px;text-align:left}.welcome{justify-content:center;align-items:center;text-align:center}.welcome-icon{width:74px;height:74px;border-radius:20px;display:grid;place-items:center;background:#e6f0eb;color:#28564e;font-size:42px}.welcome h1{font-size:25px;margin:20px 0 9px}.welcome p{font-size:13px;line-height:1.7;color:var(--muted);max-width:420px;margin:0 0 20px}.alert{display:flex;justify-content:space-between;align-items:center;padding:9px 22px;font-size:12px}.alert button{border:0;background:transparent;font-size:18px;color:inherit}.error{background:#fff0eb;color:#a84128}.success{background:#e7f5ec;color:#297c59}.modal-backdrop{position:fixed;z-index:10;inset:0;background:#1428249c;display:grid;place-items:center;padding:20px}.import-modal{position:relative;background:#fff;width:min(520px,100%);border-radius:15px;box-shadow:0 24px 70px #071f1b45;padding:30px}.import-modal .close{position:absolute;right:20px;top:15px;border:0;background:none;font-size:22px;color:#8b9a96}.import-modal h2{font-size:24px;margin:7px 0}.import-modal p{color:var(--muted);font-size:12px;line-height:1.6;margin-bottom:21px}.import-modal label{display:block;font-size:12px;font-weight:650;margin:13px 0}.import-modal input{display:block;width:100%;margin-top:7px;border:1px solid #dbe5e0;border-radius:7px;padding:10px;font-size:12px;background:#fafcfb}.file-row{display:grid;grid-template-columns:1fr 1fr;gap:12px}.import-modal .primary{margin-top:14px;width:100%}@media(max-width:1200px){.workspace{grid-template-columns:205px minmax(450px,1fr) 220px}.main-area{padding:22px 18px}.action-bar{align-items:stretch;flex-direction:column}.swatches{grid-template-columns:repeat(7,1fr)}}@media(max-width:900px){.workspace{grid-template-columns:190px minmax(0,1fr)}.tools-rail{grid-column:2;border-left:0;border-top:1px solid var(--line);display:grid;grid-template-columns:1fr 1fr}.boards{min-height:360px}.source-stage,.canvas-viewport{min-height:280px}.action-hint span{display:none}}@media(max-width:650px){.topbar{height:64px;padding:0 12px}.brand small,.top-status{display:none}.workspace{display:block}.sample-rail{height:auto;border:0;border-bottom:1px solid var(--line)}.sample-rail .rail-heading{padding:13px}.sample-rail .search,.rail-foot{display:none}.sample-list{display:flex;overflow:auto}.sample-row{min-width:170px;width:auto;border-left:0;border-bottom:3px solid transparent}.sample-row.active{border-bottom-color:#e96f43}.main-area{padding:17px 12px}.work-heading{align-items:start}.work-heading p{line-height:1.5}.heading-meta{flex-direction:column}.boards{grid-template-columns:1fr;gap:12px}.source-stage{max-height:250px}.source-stage img{max-height:210px}.canvas-viewport{min-height:380px;max-height:520px}.tools-rail{display:block}.action-buttons{justify-content:stretch}.action-buttons button{flex:1}.import-button{padding:9px 11px}.file-row{grid-template-columns:1fr}}

.tool-icon{width:18px;height:18px;flex:none;stroke:currentColor;fill:none;stroke-width:1.75;stroke-linecap:round;stroke-linejoin:round;color:#5c706b;transition:color .12s}
.tool-list button:hover:not(:disabled) .tool-icon{color:#1e554c}
.tool-list button.selected .tool-icon{color:#1e554c}
.tool-list button.background-tool .tool-icon{color:#286c58}
.tool-list button:disabled .tool-icon{opacity:.45}
.history button{display:inline-flex;align-items:center;justify-content:center;gap:5px}
.btn-icon{width:13px;height:13px;flex:none;stroke:currentColor;fill:none;stroke-width:1.8;stroke-linecap:round;stroke-linejoin:round}
.transparent{width:100%;margin-top:13px;padding:9px 12px;background:#fff;border:1px solid var(--line);border-radius:7px;color:#526560;font-size:11px;text-align:left;display:flex;align-items:center;gap:8px}
.transparent:hover{border-color:#b4c7c1;background:#f9fbfb;color:#20403a}
.checker-icon{width:16px;height:16px;flex:none;border:1px solid #0002;border-radius:3px;display:block}

.review-link{font-size:12px;font-weight:700;color:#245a56;text-decoration:none;padding:8px 10px;border:1px solid #d7e7df;border-radius:7px;background:#eef6f1}.review-link:hover{background:#e2f0e8}
.status-select-wrap{display:inline-flex;align-items:center;gap:6px;background:#fff;border:1px solid #dde7e2;border-radius:6px;padding:2px 8px 2px 9px;font-size:11px;font-weight:650;color:#3d5650;cursor:pointer;position:relative;transition:border-color .15s,background .15s}
.status-select-wrap:hover{border-color:#9cbdb3}
.status-select-wrap select{border:0;background:transparent;color:inherit;font-weight:inherit;font-size:11px;cursor:pointer;outline:none;padding:3px 0}
.status-indicator{display:inline-block;width:7px;height:7px;border-radius:50%;flex:none;background:#9aa9a6}
.status-select-wrap.pending .status-indicator{background:#eab308}
.status-select-wrap.qualified .status-indicator{background:#2b9b74}
.status-select-wrap.unqualified .status-indicator{background:#c3483e}
.status-select-wrap.human_edited .status-indicator{background:#e96f43}
.review-reason{padding:10px 13px;margin:-8px 0 16px;background:#fff2ed;border:1px solid #f2d2c5;border-radius:8px;color:#934c38;font-size:12px;line-height:1.5}
</style>
<style scoped>
@media(max-width:650px){.boards{height:auto}.board{min-height:0}.source-stage{min-height:230px}.canvas-viewport{min-height:380px}.source-board{height:330px}.editor-board{height:490px}}
.canvas-viewport.dark-background{background-color:#343c40;background-image:linear-gradient(45deg,#485257 25%,transparent 25%),linear-gradient(-45deg,#485257 25%,transparent 25%),linear-gradient(45deg,transparent 75%,#485257 75%),linear-gradient(-45deg,transparent 75%,#485257 75%)}
.editor-board .canvas-footer{height:auto;min-height:43px;gap:9px;flex-wrap:wrap;padding-top:7px;padding-bottom:7px}
.background-switch{display:inline-flex;align-items:center;gap:4px;white-space:nowrap}
.background-switch>span{margin-right:2px}
.background-switch button{width:auto;height:25px;padding:0 7px;border:1px solid #d5dfda;background:#f7f9f8;color:#536862;font-size:11px}
.background-switch button.active{border-color:#2a635b;background:#e6f2ec;color:#20554c;font-weight:700}
.background-switch button:focus-visible{outline:2px solid #e96f43;outline-offset:2px}
.search-icon{position:absolute;left:11px;top:10px;width:16px;height:16px;color:#899896;pointer-events:none}
.size-filter{display:grid;grid-template-columns:repeat(5,minmax(0,1fr));gap:4px;margin:0 14px 12px}.size-filter button{min-width:0;height:30px;padding:0 2px;border:1px solid #e3ebe7;border-radius:7px;background:#f7f9f8;color:#62736e;font-size:11px;font-weight:650}.size-filter button span{font-size:9px;margin-left:1px;font-weight:500}.size-filter button:hover{border-color:#9bbab0}.size-filter button.active{border-color:#276458;background:#e8f2ed;color:#235c50}.size-filter button:disabled{cursor:wait;opacity:.65}.size-filter button:focus-visible{outline:2px solid #e96f43;outline-offset:2px}@media(max-width:650px){.size-filter{margin:0 13px 10px}}
.sample-row{height:62px;padding:7px 8px;gap:6px}
.sample-row:disabled{opacity:1;cursor:default}
.sample-row.loading{background:#fafbfa;color:#9aa8a3}
.tool-list button.background-tool{margin-top:5px;border-color:#d7e7df;background:#f1f8f4;color:#286c58;font-weight:700}.tool-list button.background-tool:hover{background:#e5f3ea}.tool-list button.background-tool:disabled{opacity:.5;cursor:default}
.usage-section{padding-top:20px;padding-bottom:20px}.usage-help{margin:7px 0 12px;color:#8a9995;font-size:10px}.usage-list{display:grid;gap:4px;max-height:260px;overflow:auto;padding-right:3px}.usage-row{width:100%;min-height:38px;display:flex;align-items:center;gap:9px;padding:5px 8px;border:1px solid #e5ece8;border-radius:7px;background:#fff;color:#344b46;text-align:left}.usage-row:hover{background:#f3f8f5;border-color:#b7d1c5}.usage-row.active{background:#eaf3ef;border-color:#80b49e}.usage-row:focus-visible{outline:2px solid #e96f43;outline-offset:2px}.usage-swatch{width:22px;height:22px;flex:none;border:1px solid #0002;border-radius:5px}.usage-code{display:flex;align-items:baseline;gap:5px;min-width:0;font-size:12px;font-weight:700}.usage-code small{font-size:10px;color:#92a09b;font-weight:500}.usage-count{margin-left:auto;white-space:nowrap;font-size:12px;font-variant-numeric:tabular-nums;font-weight:700}.usage-count small{font-size:10px;color:#92a09b;font-weight:500}.usage-empty{margin:10px 0 0;color:#92a09b;font-size:11px}
.row-number{flex:none;width:31px;text-align:right;font-size:10px;font-variant-numeric:tabular-nums;color:#94a39f}
.sample-row.active .row-number{color:#be6544;font-weight:700}
@media(min-width:901px){.workspace{height:calc(100vh - 72px);min-height:620px;overflow:hidden}.sample-rail{min-height:0}.sample-list{min-height:0}.main-area{overflow:auto}}
@media(min-width:651px) and (max-width:900px){.sample-rail{height:calc(100vh - 72px)}.sample-list{min-height:0}}
@media(max-width:650px){.sample-list{display:block;height:190px;flex:none}.sample-row{height:62px;width:100%;min-width:0}.row-number{width:26px}}
</style>
