#!/usr/bin/env node

import { mkdir, readFile as fsReadFile, readdir as fsReaddir, rename, writeFile } from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { spawnSync } from 'node:child_process';
import { DatabaseSync } from 'node:sqlite';
import { deflateSync, inflateSync } from 'node:zlib';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const projectRoot = path.resolve(__dirname, '..');
const defaultDataRoot = path.join(projectRoot, 'webui/data');
const mappingFile = path.join(projectRoot, 'webui/src/app/colorSystemMapping.json');
let activeDataRoot = defaultDataRoot;
let annotationDb;

function database() {
  if (!annotationDb) {
    annotationDb = new DatabaseSync(path.join(activeDataRoot, 'annotation.sqlite3'));
    annotationDb.exec('PRAGMA busy_timeout = 5000');
    if (!annotationDb.prepare('PRAGMA table_info(samples)').all().some(column => column.name === 'queue_order')) {
      annotationDb.exec('ALTER TABLE samples ADD COLUMN queue_order INTEGER NOT NULL DEFAULT 0');
    }
  }
  return annotationDb;
}

function storedPath(file) {
  const relative = path.relative(activeDataRoot, file);
  if (relative.startsWith('..') || path.isAbsolute(relative)) return null;
  const [kind, name] = relative.split(path.sep);
  if (!['indices', 'meta', 'predictions', 'corrected', 'edit_masks'].includes(kind) || !name) return null;
  return { kind, id: name.replace(/\.(json|png)$/, '') };
}

function missing(file) {
  const error = new Error(`ENOENT: ${file}`);
  error.code = 'ENOENT';
  throw error;
}

async function readFile(file, encoding) {
  const stored = storedPath(file);
  if (!stored) return fsReadFile(file, encoding);
  const row = stored.kind === 'indices'
    ? database().prepare('SELECT record AS content FROM samples WHERE id=?').get(stored.id)
    : stored.kind === 'meta'
      ? database().prepare('SELECT json AS content FROM metadata WHERE id=?').get(stored.id)
      : database().prepare('SELECT png AS content FROM images WHERE id=? AND kind=?').get(stored.id, stored.kind);
  if (!row) missing(file);
  const content = stored.kind === 'indices' ? inflateSync(row.content) : row.content;
  return encoding ? content.toString(encoding) : Buffer.from(content);
}

async function readdir(folder) {
  if (path.resolve(folder) === path.join(activeDataRoot, 'indices')) {
    return database().prepare('SELECT id FROM samples ORDER BY sort_key').all().map(row => `${row.id}.json`);
  }
  return fsReaddir(folder);
}

// Import pngjs
let PNG;
try {
  const mod = await import(path.join(projectRoot, 'webui/node_modules/pngjs/lib/png.js'));
  PNG = mod.PNG;
} catch (e) {
  console.error('Error importing pngjs from webui/node_modules/pngjs. Please run pnpm install in webui.');
  process.exit(1);
}

// Digits font 3x5 for rulers
const DIGITS = {
  '0': [0b111, 0b101, 0b101, 0b101, 0b111],
  '1': [0b010, 0b110, 0b010, 0b010, 0b111],
  '2': [0b111, 0b001, 0b111, 0b100, 0b111],
  '3': [0b111, 0b001, 0b111, 0b001, 0b111],
  '4': [0b101, 0b101, 0b111, 0b001, 0b001],
  '5': [0b111, 0b100, 0b111, 0b001, 0b111],
  '6': [0b111, 0b100, 0b111, 0b101, 0b111],
  '7': [0b111, 0b001, 0b010, 0b010, 0b010],
  '8': [0b111, 0b101, 0b111, 0b101, 0b111],
  '9': [0b111, 0b101, 0b111, 0b001, 0b111],
};

// Load palette
const mapping = JSON.parse(await readFile(mappingFile, 'utf8'));
const palette = Object.entries(mapping).map(([hex, names], index) => ({
  index,
  hex: hex.toUpperCase(),
  code: names.MARD,
  rgb: [1, 3, 5].map(at => Number.parseInt(hex.slice(at, at + 2), 16)),
}));

const codeToColor = new Map(palette.map(c => [c.code.toUpperCase(), c]));
const hexToColor = new Map(palette.map(c => [c.hex.toUpperCase(), c]));

function rgbDist(r1, g1, b1, r2, g2, b2) {
  const dr = r1 - r2, dg = g1 - g2, db = b1 - b2;
  return dr * dr + dg * dg + db * db;
}

function resolveColor(input) {
  if (input === undefined || input === null) return -1;
  const s = String(input).trim().toUpperCase();
  if (['-1', 'NONE', 'TRANS', 'TRANSPARENT', 'NULL', 'CLEAR'].includes(s)) return -1;
  if (/^\d+$/.test(s)) {
    const idx = Number.parseInt(s, 10);
    if (idx >= 0 && idx < palette.length) return idx;
  }
  if (codeToColor.has(s)) return codeToColor.get(s).index;
  const cleanHex = s.startsWith('#') ? s : `#${s}`;
  if (hexToColor.has(cleanHex)) return hexToColor.get(cleanHex).index;
  if (/^#[0-9A-F]{6}$/i.test(cleanHex)) {
    const r = Number.parseInt(cleanHex.slice(1, 3), 16);
    const g = Number.parseInt(cleanHex.slice(3, 5), 16);
    const b = Number.parseInt(cleanHex.slice(5, 7), 16);
    let best = 0, bestDist = Infinity;
    for (const c of palette) {
      const d = rgbDist(r, g, b, c.rgb[0], c.rgb[1], c.rgb[2]);
      if (d < bestDist) { bestDist = d; best = c.index; }
    }
    return best;
  }
  throw new Error(`无法识别颜色: "${input}"。可用 MARD 色号 (如 H07)、HEX (如 #000000)、索引或 "transparent"`);
}

function colorDesc(index) {
  if (index < 0) return '透明 (-1)';
  const c = palette[index];
  return `${c.code} (${c.hex}, #${index})`;
}

async function atomicWrite(file, content) {
  const stored = storedPath(file);
  if (stored) {
    const db = database();
    if (stored.kind === 'indices') {
      const record = JSON.parse(content);
      const status = record.status || (record.corrected_indices ? 'pending' : 'unmodified');
      const history = Array.isArray(record.review_history) && record.review_history.length
        ? record.review_history
        : ['qualified', 'unqualified'].includes(status)
          ? [{ from: null, to: status, reason: record.review_reason || '', timestamp: record.reviewed_at || null }]
          : [];
      const sortKey = record.id.replace(/\d+/g, number => number.padStart(12, '0'));
      db.prepare(`INSERT INTO samples (id, sort_key, width, height, model_version, status,
        changed_pixels, reviewed_at, review_reason, review_history, history_count,
        has_corrected, has_meta, record)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, COALESCE((SELECT has_meta FROM samples WHERE id=?), 0), ?)
        ON CONFLICT(id) DO UPDATE SET width=excluded.width, height=excluded.height,
        model_version=excluded.model_version, status=excluded.status, changed_pixels=excluded.changed_pixels,
        reviewed_at=excluded.reviewed_at, review_reason=excluded.review_reason,
        review_history=excluded.review_history, history_count=excluded.history_count,
        has_corrected=excluded.has_corrected, record=excluded.record`).run(
          record.id, sortKey, record.width, record.height, record.model_version, status,
          record.changed_pixels || 0, record.reviewed_at || null, record.review_reason || null,
          JSON.stringify(history), history.length, Number(Boolean(record.corrected_indices)),
          record.id, deflateSync(JSON.stringify(record), { level: 1 }));
    } else if (stored.kind === 'meta') {
      db.prepare('INSERT INTO metadata (id,json) VALUES (?,?) ON CONFLICT(id) DO UPDATE SET json=excluded.json')
        .run(stored.id, String(content));
      db.prepare('UPDATE samples SET has_meta=1 WHERE id=?').run(stored.id);
    } else {
      db.prepare('INSERT INTO images (id,kind,png) VALUES (?,?,?) ON CONFLICT(id,kind) DO UPDATE SET png=excluded.png')
        .run(stored.id, stored.kind, content);
    }
    return;
  }
  const temporary = `${file}.${process.pid}.tmp`;
  await writeFile(temporary, content);
  await rename(temporary, file);
}

function resizeBilinear(src, targetW, targetH) {
  const dst = new PNG({ width: targetW, height: targetH });
  const xRatio = src.width / targetW;
  const yRatio = src.height / targetH;
  for (let y = 0; y < targetH; y++) {
    for (let x = 0; x < targetW; x++) {
      const srcX = Math.min(src.width - 1, x * xRatio);
      const srcY = Math.min(src.height - 1, y * yRatio);
      const xFloor = Math.floor(srcX);
      const yFloor = Math.floor(srcY);
      const xCeil = Math.min(src.width - 1, Math.ceil(srcX));
      const yCeil = Math.min(src.height - 1, Math.ceil(srcY));
      const xWeight = srcX - xFloor;
      const yWeight = srcY - yFloor;

      const idxTL = (yFloor * src.width + xFloor) * 4;
      const idxTR = (yFloor * src.width + xCeil) * 4;
      const idxBL = (yCeil * src.width + xFloor) * 4;
      const idxBR = (yCeil * src.width + xCeil) * 4;
      const dstIdx = (y * targetW + x) * 4;

      for (let c = 0; c < 4; c++) {
        const top = src.data[idxTL + c] * (1 - xWeight) + src.data[idxTR + c] * xWeight;
        const bottom = src.data[idxBL + c] * (1 - xWeight) + src.data[idxBR + c] * xWeight;
        dst.data[dstIdx + c] = Math.round(top * (1 - yWeight) + bottom * yWeight);
      }
    }
  }
  return dst;
}

function drawDigit(png, digit, startX, startY, color = [100, 120, 115]) {
  const pattern = DIGITS[digit];
  if (!pattern) return;
  for (let row = 0; row < 5; row++) {
    const bits = pattern[row];
    for (let col = 0; col < 3; col++) {
      if ((bits >> (2 - col)) & 1) {
        const px = startX + col, py = startY + row;
        if (px >= 0 && px < png.width && py >= 0 && py < png.height) {
          const idx = (py * png.width + px) * 4;
          png.data[idx] = color[0]; png.data[idx + 1] = color[1]; png.data[idx + 2] = color[2]; png.data[idx + 3] = 255;
        }
      }
    }
  }
}

function drawNumber(png, num, startX, startY, color = [100, 120, 115]) {
  const str = String(num);
  let curX = startX;
  for (const ch of str) {
    drawDigit(png, ch, curX, startY, color);
    curX += 4;
  }
}

function renderPixelGrid(width, height, pixels, scale = 16, drawRuler = true) {
  const rulerLeft = drawRuler ? 26 : 0;
  const rulerTop = drawRuler ? 20 : 0;
  const gridW = width * scale;
  const gridH = height * scale;
  const totalW = gridW + rulerLeft;
  const totalH = gridH + rulerTop;
  const png = new PNG({ width: totalW, height: totalH });

  // Background
  png.data.fill(248);

  // Ruler numbers
  if (drawRuler) {
    for (let x = 0; x < width; x += (width > 50 ? 10 : 5)) {
      const px = rulerLeft + x * scale + Math.floor(scale / 2) - 2;
      drawNumber(png, x, px, 8);
    }
    for (let y = 0; y < height; y += (height > 50 ? 10 : 5)) {
      const py = rulerTop + y * scale + Math.floor(scale / 2) - 2;
      drawNumber(png, y, 4, py);
    }
  }

  // Draw cells
  for (let y = 0; y < height; y++) {
    for (let x = 0; x < width; x++) {
      const colorIdx = pixels[y * width + x];
      const startX = rulerLeft + x * scale;
      const startY = rulerTop + y * scale;
      let rgb;
      if (colorIdx < 0) {
        // Checkerboard
        rgb = null;
      } else {
        rgb = palette[colorIdx].rgb;
      }

      for (let dy = 0; dy < scale; dy++) {
        for (let dx = 0; dx < scale; dx++) {
          const px = startX + dx;
          const py = startY + dy;
          const idx = (py * totalW + px) * 4;

          // Grid border
          const isBorder = (dx === scale - 1 || dy === scale - 1);
          const isMajor = (x % 5 === 4 && dx === scale - 1) || (y % 5 === 4 && dy === scale - 1);

          if (rgb) {
            if (isBorder && scale >= 6) {
              const borderDark = isMajor ? 0.75 : 0.88;
              png.data[idx] = Math.round(rgb[0] * borderDark);
              png.data[idx + 1] = Math.round(rgb[1] * borderDark);
              png.data[idx + 2] = Math.round(rgb[2] * borderDark);
            } else {
              png.data[idx] = rgb[0];
              png.data[idx + 1] = rgb[1];
              png.data[idx + 2] = rgb[2];
            }
          } else {
            // Checkerboard for transparent
            const check = ((Math.floor(px / 4) + Math.floor(py / 4)) % 2 === 0);
            const val = check ? 238 : 222;
            png.data[idx] = val; png.data[idx + 1] = val + 4; png.data[idx + 2] = val + 2;
          }
          png.data[idx + 3] = 255;
        }
      }
    }
  }
  return png;
}

function cleanColorFringe(pixels, width, height) {
  if (width < 3 || height < 3 || pixels.length !== width * height) return null;
  const blackIndex = palette.findIndex(c => c.hex === '#000000');
  if (blackIndex < 0) return null;

  const isVivid = (idx) => {
    if (idx < 0 || idx >= palette.length) return false;
    const ch = palette[idx].rgb;
    return Math.max(...ch) - Math.min(...ch) >= 60 && Math.max(...ch) >= 150;
  };
  const counts = new Map();
  let vividTotal = 0;
  for (const idx of pixels) {
    if (!isVivid(idx)) continue;
    counts.set(idx, (counts.get(idx) || 0) + 1);
    vividTotal++;
  }
  let fillIndex = -1, fillCount = 0;
  for (const [idx, count] of counts) {
    if (count > fillCount) { fillIndex = idx; fillCount = count; }
  }
  if (fillCount < width * height * 0.12 || fillCount < vividTotal * 0.72) return null;

  const neighbors4 = (idx) => {
    const x = idx % width, y = Math.floor(idx / width);
    return [
      x > 0 ? idx - 1 : -1, x + 1 < width ? idx + 1 : -1,
      y > 0 ? idx - width : -1, y + 1 < height ? idx + width : -1
    ];
  };

  const visited = new Uint8Array(pixels.length);
  let mainComponent = [];
  for (let start = 0; start < pixels.length; start++) {
    if (pixels[start] !== fillIndex || visited[start]) continue;
    const component = [start];
    visited[start] = 1;
    for (let head = 0; head < component.length; head++) {
      for (const n of neighbors4(component[head])) {
        if (n >= 0 && !visited[n] && pixels[n] === fillIndex) {
          visited[n] = 1;
          component.push(n);
        }
      }
    }
    if (component.length > mainComponent.length) mainComponent = component;
  }
  if (mainComponent.length < fillCount * 0.8) return null;

  const distance = new Int8Array(pixels.length).fill(-1);
  const queue = [...mainComponent];
  for (const idx of mainComponent) distance[idx] = 0;
  for (let head = 0; head < queue.length; head++) {
    const idx = queue[head];
    if (distance[idx] >= 1) continue;
    const x = idx % width, y = Math.floor(idx / width);
    for (let dy = -1; dy <= 1; dy++) for (let dx = -1; dx <= 1; dx++) {
      const nx = x + dx, ny = y + dy;
      if ((!dx && !dy) || nx < 0 || nx >= width || ny < 0 || ny >= height) continue;
      const n = ny * width + nx;
      if (distance[n] !== -1) continue;
      distance[n] = distance[idx] + 1;
      queue.push(n);
    }
  }

  const result = [...pixels];
  let outlinePixels = 0, clearedPixels = 0;
  for (let i = 0; i < result.length; i++) {
    if (distance[i] === 1 && result[i] !== blackIndex) {
      result[i] = blackIndex;
      outlinePixels++;
    } else if (distance[i] !== 0 && distance[i] !== 1 && result[i] >= 0) {
      result[i] = -1;
      clearedPixels++;
    }
  }
  return { pixels: result, outlinePixels, clearedPixels, fillIndex };
}

function removeBackground(pixels, width, height) {
  const borderCounts = new Map();
  const countBorder = (idx) => {
    const c = pixels[idx];
    if (c >= 0) borderCounts.set(c, (borderCounts.get(c) || 0) + 1);
  };
  for (let x = 0; x < width; x++) {
    countBorder(x);
    if (height > 1) countBorder((height - 1) * width + x);
  }
  for (let y = 1; y < height - 1; y++) {
    countBorder(y * width);
    if (width > 1) countBorder(y * width + width - 1);
  }
  if (!borderCounts.size) return null;

  let bg = -1, maxCount = -1;
  for (const [c, count] of borderCounts) {
    if (count > maxCount) { bg = c; maxCount = count; }
  }

  const next = [...pixels];
  const stack = [];
  const pushIfBg = (idx) => {
    if (next[idx] !== bg) return;
    next[idx] = -1;
    stack.push(idx);
  };
  for (let x = 0; x < width; x++) {
    pushIfBg(x);
    if (height > 1) pushIfBg((height - 1) * width + x);
  }
  for (let y = 1; y < height - 1; y++) {
    pushIfBg(y * width);
    if (width > 1) pushIfBg(y * width + width - 1);
  }
  for (let head = 0; head < stack.length; head++) {
    const idx = stack[head];
    const x = idx % width, y = Math.floor(idx / width);
    if (x > 0) pushIfBg(idx - 1);
    if (x + 1 < width) pushIfBg(idx + 1);
    if (y > 0) pushIfBg(idx - width);
    if (y + 1 < height) pushIfBg(idx + width);
  }
  return { pixels: next, clearedCount: stack.length, bgColor: bg };
}

function floodFill(pixels, width, height, startX, startY, targetColor) {
  if (startX < 0 || startX >= width || startY < 0 || startY >= height) return pixels;
  const startIdx = startY * width + startX;
  const origColor = pixels[startIdx];
  if (origColor === targetColor) return pixels;

  const next = [...pixels];
  const stack = [startIdx];
  next[startIdx] = targetColor;

  while (stack.length > 0) {
    const idx = stack.pop();
    const x = idx % width, y = Math.floor(idx / width);
    const neighbors = [
      x > 0 ? idx - 1 : -1, x + 1 < width ? idx + 1 : -1,
      y > 0 ? idx - width : -1, y + 1 < height ? idx + width : -1
    ];
    for (const n of neighbors) {
      if (n >= 0 && next[n] === origColor) {
        next[n] = targetColor;
        stack.push(n);
      }
    }
  }
  return next;
}

function drawLine(pixels, width, height, x0, y0, x1, y1, color) {
  const next = [...pixels];
  const dx = Math.abs(x1 - x0);
  const dy = Math.abs(y1 - y0);
  const sx = x0 < x1 ? 1 : -1;
  const sy = y0 < y1 ? 1 : -1;
  let err = dx - dy;
  let curX = x0, curY = y0;

  while (true) {
    if (curX >= 0 && curX < width && curY >= 0 && curY < height) {
      next[curY * width + curX] = color;
    }
    if (curX === x1 && curY === y1) break;
    const e2 = 2 * err;
    if (e2 > -dy) { err -= dy; curX += sx; }
    if (e2 < dx) { err += dx; curY += sy; }
  }
  return next;
}

function drawRect(pixels, width, height, x0, y0, x1, y1, color, fill = false) {
  const next = [...pixels];
  const minX = Math.max(0, Math.min(x0, x1));
  const maxX = Math.min(width - 1, Math.max(x0, x1));
  const minY = Math.max(0, Math.min(y0, y1));
  const maxY = Math.min(height - 1, Math.max(y0, y1));

  for (let y = minY; y <= maxY; y++) {
    for (let x = minX; x <= maxX; x++) {
      if (fill || x === minX || x === maxX || y === minY || y === maxY) {
        next[y * width + x] = color;
      }
    }
  }
  return next;
}

async function generateSideBySidePreview(dataRoot, sampleRecord, outputPath) {
  const { id, width, height } = sampleRecord;
  const sourcePath = path.join(dataRoot, 'sources', `${id}.png`);
  let sourcePng;
  try {
    sourcePng = PNG.sync.read(await readFile(sourcePath));
  } catch {
    sourcePng = new PNG({ width: 256, height: 256 });
    sourcePng.data.fill(240);
  }

  const scale = Math.max(3, Math.min(22, Math.floor(420 / Math.max(width, height))));
  const predPixels = sampleRecord.indices;
  const currentPixels = sampleRecord.corrected_indices || sampleRecord.indices;

  const predGrid = renderPixelGrid(width, height, predPixels, scale, false);
  const currGrid = renderPixelGrid(width, height, currentPixels, scale, true);

  const canvasW = currGrid.width;
  const canvasH = currGrid.height;
  const resizedSource = resizeBilinear(sourcePng, canvasW, canvasH);

  const margin = 20;
  const headerH = 34;
  const totalW = margin + (canvasW * 3) + (margin * 2) + margin;
  const totalH = margin + headerH + canvasH + margin;

  const combined = new PNG({ width: totalW, height: totalH });
  combined.data.fill(244); // light clean neutral background

  // Composite 3 panels
  const panels = [
    { title: '01 原图', png: resizedSource, x: margin },
    { title: '02 模型原始预测', png: predGrid, x: margin + canvasW + margin },
    { title: `03 纠错画布 (${sampleRecord.changed_pixels || 0} 已改)`, png: currGrid, x: margin + (canvasW + margin) * 2 }
  ];

  for (const p of panels) {
    const startX = p.x;
    const startY = margin + headerH;
    for (let y = 0; y < p.png.height; y++) {
      for (let x = 0; x < p.png.width; x++) {
        const srcIdx = (y * p.png.width + x) * 4;
        const dstIdx = ((startY + y) * totalW + (startX + x)) * 4;
        combined.data[dstIdx] = p.png.data[srcIdx];
        combined.data[dstIdx + 1] = p.png.data[srcIdx + 1];
        combined.data[dstIdx + 2] = p.png.data[srcIdx + 2];
        combined.data[dstIdx + 3] = p.png.data[srcIdx + 3];
      }
    }
  }

  await atomicWrite(outputPath, PNG.sync.write(combined));
  return outputPath;
}

// CLI Arg parser
function parseArgs(args) {
  const parsed = { _: [] };
  for (let i = 0; i < args.length; i++) {
    const a = args[i];
    if (a.startsWith('--')) {
      const key = a.slice(2);
      if (i + 1 < args.length && !args[i + 1].startsWith('--')) {
        parsed[key] = args[++i];
      } else {
        parsed[key] = true;
      }
    } else {
      parsed._.push(a);
    }
  }
  return parsed;
}

async function main() {
  const args = parseArgs(process.argv.slice(2));
  const command = args._[0] || 'help';
  const dataRoot = args['data-dir'] || defaultDataRoot;
  activeDataRoot = path.resolve(dataRoot);

  try {
    if (command === 'help') {
      console.log(`
Pixel Art 纠错标注 CLI 工具 (AI 协作标注助手)
==============================================
用法:
  node scripts/pixel_annotate.mjs <command> [options]

常用命令:
  profile-ellipse <序号> 添加圆形或椭圆细节（512 坐标）
                       --rect x1,y1,x2,y2 --color <索引> --outline <索引> --width 4
  profile-mirror <序号> 镜像指定尺寸手工稿的左半边到右半边
                       --size 24 --keep x1,y1,x2,y2（可选保留区域，逻辑像素坐标）
  profile-stroke <序号>  追加细线（512 坐标，自动适配四种尺寸，裁切到主体内）
                       --points 'x,y;x,y;...' --color <索引> --width 4
  profile-grid <序号>   保存指定尺寸的手工像素稿
                       --size 24 --rows '逐行字符，用 / 分隔' --legend '.:-1,K:189,W:184,P:244,Y:246'
  profile-patch <序号>  追加局部改色（坐标基于 512×512 原图）
                       --rect x1,y1,x2,y2 --from <原色板索引> --color <新色板索引>
  profile-set <序号>    保存可复用的平涂纠错参数（第一色必须是背景）
                       --colors '#FFFFFF:-1,#F29DE8:244,#FFFF00:246,#000000:189'
                       --ink 3 --enclosed-white 184 --coverage 0.44 --ink-coverage 0.24
                       --symmetry --outline（可选）
                       然后 recipe-preview / recipe-apply <序号>，支持 --sizes
  list                 列出样本队列进度与筛选列表
                       --size 24|52|78|104
                       --status unmodified|pending|human_edited|qualified|unqualified|all
                       --limit 20  --offset 0  --search <id>

  next                 获取下一个待标注样本 ID（优先不合格）
                       --size 24|52|78|104

  show <id>            查看样本详情、画布色卡统计，并生成原图/预测/纠错三栏对照图
                       --preview-file <path> (默认写入 /tmp/annot_<id>.png)
                       --render (在终端直接输出 ANSI 彩色字符画)

  palette [query]      搜索或列出 MARD 291 色板 (按色号/HEX/名称)

  edit <id> [options]  对逻辑像素进行精细编辑修图，并自动更新预览图:
                       --set "x,y:color" (支持多个坐标点)
                       --line "x1,y1,x2,y2:color" (Bresenham 直线)
                       --rect "x1,y1,x2,y2:color" (矩形框)
                       --rect-fill "x1,y1,x2,y2:color" (实心矩形)
                       --fill "x,y:color" (连通区域漫水填充)
                       --erase "x,y" (设为透明)
                       --replace "old_color:new_color" (全局颜色替换)
                       --remove-bg (自动去边缘背景)
                       --clean-fringe (单色主体彩边净化为纯黑描边并去杂色)

  save <id>            提交保存纠错标注 (纠错图、mask、元数据写入 SQLite)
                       --accept (直接通过，0 处修改)
                       --status pending|human_edited (默认 pending)

  recipe-preview <n>  为已定义的简单图案生成原图与 24/52/78/104 多尺寸预览
                       --sizes 24,52,78,104 (可只选部分尺寸)

  recipe-apply <n>    将看过的配方预览写入纠错图、mask、meta；状态为 pending
                       --sizes 24,52,78,104  --force (明确覆盖已有标注)

  recipe-list         列出目前已经检查并写成配方的图案序号

  batch-clean         批量清理候选，默认只统计；--save 才写入待审核标注
                       --size 24|52|78|104  --limit 50

  status <id> <status> 手动更改标注状态 (pending | human_edited)
                       可将已保存的样本重置为 "pending" (待审核)

  diff <id>            查看当前编辑与原始模型预测的所有差异点 (坐标与颜色)

  reset <id>           重置画布像素回模型原始预测

示例:
  # 1. 查找下一个待标的 24 像素样本
  node scripts/pixel_annotate.mjs next --size 24

  # 2. 生成预览并在工作区查看
  node scripts/pixel_annotate.mjs show 8_24

  # 3. 进行修正修图 (去背景 + 修线 + 换色)
  node scripts/pixel_annotate.mjs edit 8_24 --remove-bg --set 10,12:H07 10,13:H07

  # 4. 保存待审核标注
  node scripts/pixel_annotate.mjs save 8_24

  # 5. 人工修图后可标为已人工修改
  node scripts/pixel_annotate.mjs status 8_24 human_edited

  # 6. 预览并应用一组已定义的简单图案
  node scripts/pixel_annotate.mjs recipe-preview 122
  node scripts/pixel_annotate.mjs recipe-apply 122
`);
      return;
    }

    if (command === 'profile-ellipse') {
      const id = args._[1], color = Number(args.color), width = Number(args.width ?? 4);
      const rect = String(args.rect || '').split(',').map(Number);
      const outline = args.outline === undefined ? color : Number(args.outline);
      if (!/^\d+$/.test(id || '') || args.color === undefined || ![color, outline].every(n => Number.isInteger(n) && n >= 0 && n < palette.length) || !Number.isFinite(width) || width <= 0 || width > 512 || rect.length !== 4 || rect.some(n => !Number.isFinite(n) || n < 0 || n > 512) || rect[0] > rect[2] || rect[1] > rect[3]) throw new Error('需要有效的椭圆矩形、颜色及线宽');
      const file = path.join(projectRoot, 'scripts/annotation_profiles', `${id}.json`);
      const profile = JSON.parse(await readFile(file, 'utf8'));
      profile.ellipses = [...(profile.ellipses || []), { rect, color, outline, width }];
      await atomicWrite(file, JSON.stringify(profile, null, 2) + '\n');
      console.log(`已追加 ${id} 椭圆，请重新预览。`);
      return;
    }

    if (command === 'profile-mirror') {
      const id = args._[1], size = Number(args.size);
      if (!/^\d+$/.test(id || '') || ![24, 52, 78, 104].includes(size)) throw new Error('需要图片序号及 --size');
      const keep = args.keep === undefined ? null : String(args.keep).split(',').map(Number);
      if (keep && (keep.length !== 4 || !keep.every(n => Number.isInteger(n) && n >= 0 && n < size) || keep[0] > keep[2] || keep[1] > keep[3])) throw new Error('--keep 需要有效的逻辑像素矩形');
      const file = path.join(projectRoot, 'scripts/annotation_profiles', `${id}.json`);
      const profile = JSON.parse(await readFile(file, 'utf8'));
      const grid = profile.sizes?.[size]?.grid;
      if (!grid || grid.length !== size || grid.some(row => row.length !== size)) throw new Error('请先用 profile-grid 保存该尺寸像素稿');
      for (let y = 0; y < size; y++) for (let x = size / 2; x < size; x++) {
        if (keep && x >= keep[0] && x <= keep[2] && y >= keep[1] && y <= keep[3]) continue;
        grid[y][x] = grid[y][size - 1 - x];
      }
      await atomicWrite(file, JSON.stringify(profile, null, 2) + '\n');
      console.log(`已镜像 ${id} 的 ${size} 像素稿，请重新预览。`);
      return;
    }

    if (command === 'profile-stroke') {
      const id = args._[1], color = Number(args.color), width = Number(args.width ?? 4);
      const points = String(args.points || '').split(';').map(p => p.split(',').map(Number));
      if (!/^\d+$/.test(id || '') || args.color === undefined || !Number.isInteger(color) || color < 0 || color >= palette.length || !Number.isFinite(width) || width <= 0 || width > 512 || points.length < 2 || points.some(p => p.length !== 2 || p.some(v => !Number.isFinite(v) || v < 0 || v > 512))) throw new Error('需要有效的序号、--points、--color 和 --width');
      const file = path.join(projectRoot, 'scripts/annotation_profiles', `${id}.json`);
      const profile = JSON.parse(await readFile(file, 'utf8'));
      profile.strokes = [...(profile.strokes || []), { points, color, width }];
      await atomicWrite(file, JSON.stringify(profile, null, 2) + '\n');
      console.log(`已追加 ${id} 细线，请重新预览。`);
      return;
    }

    if (command === 'profile-grid') {
      const id = args._[1], size = Number(args.size);
      if (!/^\d+$/.test(id || '') || ![24, 52, 78, 104].includes(size)) throw new Error('需要图片序号及 --size');
      const legend = {};
      for (const entry of String(args.legend || '').split(',')) {
        const match = entry.match(/^(.):(-?\d+)$/u);
        if (!match || Number(match[2]) < -1 || Number(match[2]) >= palette.length) throw new Error('无效的 --legend 字符:索引');
        legend[match[1]] = Number(match[2]);
      }
      const rows = String(args.rows || '').split('/');
      if (rows.length !== size || rows.some(row => [...row].length !== size || [...row].some(c => legend[c] === undefined))) throw new Error('像素稿行列数必须等于尺寸，字符必须在 legend 中定义');
      const file = path.join(projectRoot, 'scripts/annotation_profiles', `${id}.json`);
      const profile = JSON.parse(await readFile(file, 'utf8'));
      profile.sizes ??= {};
      profile.sizes[size] = { ...(profile.sizes[size] || {}), grid: rows.map(row => [...row].map(c => legend[c])) };
      await atomicWrite(file, JSON.stringify(profile, null, 2) + '\n');
      console.log(`已保存 ${id} 的 ${size}×${size} 手工像素稿，请重新预览。`);
      return;
    }

    if (command === 'profile-patch') {
      const id = args._[1];
      if (!/^\d+$/.test(id || '')) throw new Error('需要图片序号');
      const rect = String(args.rect || '').split(',').map(Number);
      if (rect.length !== 4 || !rect.every(n => Number.isFinite(n) && n >= 0 && n <= 512) || rect[0] > rect[2] || rect[1] > rect[3]) throw new Error('--rect 需要 x1,y1,x2,y2，范围 0..512');
      const color = Number(args.color), from = Number(args.from);
      if (![color, from].every(n => Number.isInteger(n) && n >= -1 && n < palette.length) || args.color === undefined || args.from === undefined) throw new Error('需要有效的 --from 和 --color 色板索引');
      const file = path.join(projectRoot, 'scripts/annotation_profiles', `${id}.json`);
      const profile = JSON.parse(await readFile(file, 'utf8'));
      profile.patches = [...(profile.patches || []), { rect, from, color }];
      await atomicWrite(file, JSON.stringify(profile, null, 2) + '\n');
      console.log(`已追加 ${id} 局部改色，请重新生成预览。`);
      return;
    }

    if (command === 'profile-set') {
      const id = args._[1];
      if (!/^\d+$/.test(id || '') || typeof args.colors !== 'string') throw new Error('需要图片序号和 --colors HEX:index,...');
      const entries = args.colors.split(',').map(entry => {
        const match = entry.trim().match(/^#([\da-f]{6}):(-?\d+)$/i);
        if (!match) throw new Error(`无效颜色: ${entry}`);
        const index = Number(match[2]);
        if (index < -1 || index >= palette.length) throw new Error('色板索引超出范围');
        return { rgb: [0, 2, 4].map(i => parseInt(match[1].slice(i, i + 2), 16)), index };
      });
      if (entries.length < 2 || entries[0].index !== -1 || entries.slice(1).some(e => e.index < 0)) throw new Error('第一色必须为 -1 背景，其他颜色必须对应色板');
      const profile = {
        rgb: entries.map(e => e.rgb), indices: entries.map(e => e.index),
        coverage: Number(args.coverage ?? .44), ink_coverage: Number(args['ink-coverage'] ?? .24),
        symmetry: Boolean(args.symmetry), outline: Boolean(args.outline),
      };
      if (args.ink !== undefined) profile.ink = Number(args.ink);
      if (args['enclosed-white'] !== undefined) profile.enclosed_white = Number(args['enclosed-white']);
      if (![profile.coverage, profile.ink_coverage].every(n => Number.isFinite(n) && n > 0 && n <= 1)) throw new Error('覆盖率必须大于 0 且不超过 1');
      if (profile.ink !== undefined && (!Number.isInteger(profile.ink) || profile.ink < 1 || profile.ink >= entries.length)) throw new Error('--ink 必须是非背景颜色的位置，从 0 开始');
      if (profile.enclosed_white !== undefined && (!Number.isInteger(profile.enclosed_white) || profile.enclosed_white < 0 || profile.enclosed_white >= palette.length)) throw new Error('--enclosed-white 必须是有效色板索引');
      const dir = path.join(projectRoot, 'scripts/annotation_profiles');
      await mkdir(dir, { recursive: true });
      await atomicWrite(path.join(dir, `${id}.json`), JSON.stringify(profile, null, 2) + '\n');
      console.log(`已保存 ${id} 配置；运行 recipe-preview ${id} 检查四种尺寸，再 recipe-apply ${id} 送审。`);
      return;
    }

    if (command === 'recipe-list' || command === 'recipe-preview' || command === 'recipe-apply') {
      const ids = args._.slice(1);
      if (command !== 'recipe-list' && (ids.length === 0 || ids.some(id => !/^\d+$/.test(id)))) {
        throw new Error(`用法: ${command} <图片序号> [更多序号] [--sizes 24,52,78,104]`);
      }
      const sizes = String(args.sizes || '24,52,78,104').split(',').map(s => s.trim());
      if (sizes.some(s => !['24', '52', '78', '104'].includes(s))) {
        throw new Error('尺寸只能从 24,52,78,104 中选择');
      }
      const python = process.env.PYTHON || 'python3';
      const recipeScript = path.join(projectRoot, 'scripts/pixel_annotation_recipes.py');
      const mode = command === 'recipe-list' ? 'list' : command === 'recipe-preview' ? 'preview' : 'apply';
      const pythonArgs = [recipeScript, mode, ...ids, '--sizes', ...sizes, '--data-dir', dataRoot];
      if (args.force) pythonArgs.push('--force');
      const result = spawnSync(python, pythonArgs, { cwd: projectRoot, stdio: 'inherit' });
      if (result.error) throw result.error;
      if (result.status !== 0) process.exit(result.status || 1);
      return;
    }

    if (command === 'list') {
      const sizeFilter = args.size ? String(args.size) : '';
      const statusFilter = args.status ? String(args.status) : '';
      const search = (args.search || '').trim().toLowerCase();
      const limit = Number(args.limit || 20);
      const offset = Number(args.offset || 0);
      const db = database();
      const counts = db.prepare(`SELECT count(*) AS total,
        sum(CASE WHEN status='pending' THEN 1 ELSE 0 END) AS pending,
        sum(CASE WHEN status='human_edited' THEN 1 ELSE 0 END) AS edited,
        sum(CASE WHEN status='qualified' THEN 1 ELSE 0 END) AS accepted FROM samples`).get();
      const filters = [];
      const values = [];
      if (sizeFilter) { filters.push('width = ?'); values.push(Number(sizeFilter)); }
      if (statusFilter && statusFilter !== 'all') { filters.push('status = ?'); values.push(statusFilter); }
      if (search) { filters.push('instr(lower(id), ?) > 0'); values.push(search); }
      const where = filters.length ? `WHERE ${filters.join(' AND ')}` : '';
      const matches = db.prepare(`SELECT count(*) AS total FROM samples ${where}`).get(...values).total;
      const page = db.prepare(`SELECT id, width, height, status, changed_pixels, model_version
        FROM samples ${where}
        ORDER BY CASE WHEN status='unqualified' THEN 0 ELSE 1 END, queue_order, sort_key
        LIMIT ? OFFSET ?`).all(...values, limit, offset);

      console.log(`\n📊 数据集统计: 总样本: ${counts.total} | 已完成: ${counts.accepted || 0} (已改: ${counts.edited || 0}, 通过: ${counts.accepted || 0}) | 待审核: ${counts.pending || 0}`);
      console.log(`🔍 筛选条件: 尺寸=${sizeFilter || '全部'}, 状态=${statusFilter || '全部'}, 匹配数=${matches}\n`);

      console.log('序号'.padEnd(6) + '样本 ID'.padEnd(16) + '尺寸'.padEnd(12) + '状态'.padEnd(10) + '已修改像素'.padEnd(14) + '模型版本');
      console.log('-'.repeat(70));

      page.forEach((r, idx) => {
        const no = String(offset + idx + 1).padStart(4, '0');
        const stLabel = ({ unmodified: '未修改', pending: '待审核', human_edited: '已人工修改', qualified: '合格', unqualified: '不合格' })[r.status] || '未修改';
        console.log(
          `${no}  ${r.id.padEnd(16)}${`${r.width}×${r.height}`.padEnd(12)}${stLabel.padEnd(10)}${String(r.changed_pixels || 0).padEnd(14)}${r.model_version || ''}`
        );
      });
      if (matches > offset + limit) {
        console.log(`\n... 还有 ${matches - offset - limit} 条样本未显示，使用 --offset ${offset + limit} 查看更多`);
      }
      return;
    }

    if (command === 'next') {
      const sizeFilter = args.size ? String(args.size) : '';
      const next = database().prepare(`SELECT id FROM samples
        WHERE (status='unqualified' OR (status='unmodified' AND has_corrected=0))
          AND (? = '' OR width = ?)
        ORDER BY CASE WHEN status='unqualified' THEN 0 ELSE 1 END, queue_order, sort_key
        LIMIT 1`).get(sizeFilter, Number(sizeFilter) || 0);
      if (next) {
        console.log(next.id);
        return;
      }
      console.error('没有找到符合条件的待审样本！');
      process.exit(1);
    }

    if (command === 'palette') {
      const query = (args._[1] || '').trim().toLowerCase();
      const filtered = !query ? palette : palette.filter(c =>
        c.code.toLowerCase().includes(query) || c.hex.toLowerCase().includes(query)
      );
      console.log(`\n🎨 MARD 色板查询 (${filtered.length} / ${palette.length}):`);
      console.log('索引'.padEnd(8) + 'MARD 色号'.padEnd(14) + 'HEX'.padEnd(12) + 'RGB');
      console.log('-'.repeat(45));
      filtered.slice(0, 50).forEach(c => {
        console.log(`#${String(c.index).padEnd(6)}${c.code.padEnd(14)}${c.hex.padEnd(12)}${c.rgb.join(', ')}`);
      });
      if (filtered.length > 50) console.log(`... 仅展示前 50 种颜色`);
      return;
    }

    if (command === 'show') {
      const id = args._[1];
      if (!id) throw new Error('请指定样本 ID，例如: node scripts/pixel_annotate.mjs show 8_24');
      const recFile = path.join(dataRoot, 'indices', `${id}.json`);
      const rec = JSON.parse(await readFile(recFile, 'utf8'));
      const pixels = rec.corrected_indices || rec.indices;

      console.log(`\n🖼️ 样本 ID: ${rec.id}`);
      console.log(`- 尺寸: ${rec.width} × ${rec.height}`);
      console.log(`- 状态: ${rec.status || 'unmodified'} (已修改: ${rec.changed_pixels || 0} 格)`);
      if (rec.review_reason) console.log(`- 上次不合格原因: ${rec.review_reason}`);
      console.log(`- 模型版本: ${rec.model_version}`);

      // Count colors
      const counts = new Map();
      for (const p of pixels) counts.set(p, (counts.get(p) || 0) + 1);
      const sorted = [...counts.entries()].sort((a, b) => b[1] - a[1]);

      console.log(`\n🎨 画布用色分布 (共 ${sorted.length} 种颜色):`);
      for (const [idx, count] of sorted.slice(0, 10)) {
        const pct = ((count / (rec.width * rec.height)) * 100).toFixed(1);
        console.log(`  ${colorDesc(idx).padEnd(28)} : ${count} 格 (${pct}%)`);
      }
      if (sorted.length > 10) console.log(`  ... 另有 ${sorted.length - 10} 种颜色`);

      const previewPath = args['preview-file'] || `/tmp/annot_${id}.png`;
      await generateSideBySidePreview(dataRoot, rec, previewPath);
      console.log(`\n✨ 已生成三栏对照图: ${previewPath}`);
      console.log(`   (01 原图 | 02 模型预测 | 03 纠错画布带坐标刻度)`);
      console.log(`👉 可直接在对话中查看或使用工具检查该图片。\n`);
      return;
    }

    if (command === 'diff') {
      const id = args._[1];
      if (!id) throw new Error('请指定样本 ID');
      const recFile = path.join(dataRoot, 'indices', `${id}.json`);
      const rec = JSON.parse(await readFile(recFile, 'utf8'));
      const orig = rec.indices;
      const curr = rec.corrected_indices || rec.indices;

      const diffs = [];
      for (let i = 0; i < orig.length; i++) {
        if (orig[i] !== curr[i]) {
          const x = i % rec.width, y = Math.floor(i / rec.width);
          diffs.push({ x, y, from: orig[i], to: curr[i] });
        }
      }
      console.log(`\n🔍 样本 ${id} 修改差异对比 (共 ${diffs.length} 处修改):`);
      diffs.slice(0, 30).forEach(d => {
        console.log(`  (${d.x}, ${d.y}): ${colorDesc(d.from)} -> ${colorDesc(d.to)}`);
      });
      if (diffs.length > 30) console.log(`  ... 另有 ${diffs.length - 30} 处修改`);
      return;
    }

    if (command === 'reset') {
      const id = args._[1];
      if (!id) throw new Error('请指定样本 ID');
      const recFile = path.join(dataRoot, 'indices', `${id}.json`);
      const rec = JSON.parse(await readFile(recFile, 'utf8'));
      rec.corrected_indices = [...rec.indices];
      rec.changed_pixels = 0;
      await atomicWrite(recFile, JSON.stringify(rec, null, 2));
      const previewPath = `/tmp/annot_${id}.png`;
      await generateSideBySidePreview(dataRoot, rec, previewPath);
      console.log(`\n🔄 样本 ${id} 画布已重置回原始模型预测结果！预览图: ${previewPath}`);
      return;
    }

    if (command === 'status') {
      const id = args._[1];
      const nextStatus = args._[2];
      if (!id || !nextStatus || !['pending', 'human_edited'].includes(nextStatus)) {
        throw new Error('用法: node scripts/pixel_annotate.mjs status <id> <pending|human_edited>');
      }
      const recFile = path.join(dataRoot, 'indices', `${id}.json`);
      const rec = JSON.parse(await readFile(recFile, 'utf8'));
      if (!rec.corrected_indices) throw new Error('请先保存纠错图');
      rec.status = nextStatus;

      const metaFile = path.join(dataRoot, 'meta', `${id}.json`);
      if (nextStatus === 'pending') {
        // A saved correction can remain pending review; keep its training metadata.
        try {
          const meta = JSON.parse(await readFile(metaFile, 'utf8'));
          meta.accepted_without_edit = false;
          await atomicWrite(metaFile, JSON.stringify(meta, null, 2));
        } catch (error) {
          if (error.code !== 'ENOENT') throw error;
        }
      } else {
        let meta;
        try {
          meta = JSON.parse(await readFile(metaFile, 'utf8'));
          meta.accepted_without_edit = false;
        } catch {
          meta = {
            id,
            source: `sources/${id}.png`,
            prediction: `predictions/${id}.png`,
            corrected: `corrected/${id}.png`,
            edit_mask: `edit_masks/${id}.png`,
            width: rec.width,
            height: rec.height,
            model_version: rec.model_version,
            palette: 'MARD',
            accepted_without_edit: false,
            changed_pixels: rec.changed_pixels || 0,
            timestamp: new Date().toISOString()
          };
        }
        await atomicWrite(metaFile, JSON.stringify(meta, null, 2));
      }

      await atomicWrite(recFile, JSON.stringify(rec, null, 2));
      console.log(`\n✅ 样本 ${id} 状态已修改为: ${nextStatus}`);
      return;
    }

    if (command === 'batch-clean') {
      const indicesDir = path.join(dataRoot, 'indices');
      const allFiles = (await readdir(indicesDir)).filter(f => f.endsWith('.json'));
      const allIds = allFiles.map(f => f.slice(0, -5)).sort((a, b) => a.localeCompare(b, 'en', { numeric: true }));

      const sizeFilter = args.size ? String(args.size) : '';
      const limit = Number(args.limit || 50);
      const doRemoveBg = args['remove-bg'] !== false;
      const doCleanFringe = Boolean(args['clean-fringe']);
      const doSave = Boolean(args.save);

      let processed = 0;
      console.log(`\n🚀 批量预标注/清洗开始 (上限 ${limit} 条, 尺寸=${sizeFilter || "全部"})...`);

      for (const id of allIds) {
        if (processed >= limit) break;
        const recFile = path.join(indicesDir, `${id}.json`);
        const rec = JSON.parse(await readFile(recFile, 'utf8'));
        if (sizeFilter && String(rec.width) !== sizeFilter) continue;
        if (rec.status && rec.status !== 'unmodified') continue;
        if (rec.corrected_indices && !args.force) continue;

        let pixels = [...(rec.corrected_indices || rec.indices)];
        let changed = false;

        if (doRemoveBg) {
          const res = removeBackground(pixels, rec.width, rec.height);
          if (res && res.clearedCount > 0) {
            pixels = res.pixels;
            changed = true;
          }
        }

        if (doCleanFringe) {
          const res = cleanColorFringe(pixels, rec.width, rec.height);
          if (res && (res.outlinePixels > 0 || res.clearedPixels > 0)) {
            pixels = res.pixels;
            changed = true;
          }
        }

        if (changed && doSave) {
          const diffCount = pixels.reduce((acc, val, i) => acc + Number(val !== rec.indices[i]), 0);
          const correctedPng = new PNG({ width: rec.width, height: rec.height });
          const maskPng = new PNG({ width: rec.width, height: rec.height });
          for (let i = 0; i < pixels.length; i++) {
            const p = i * 4;
            const colorIdx = pixels[i];
            if (colorIdx < 0) {
              correctedPng.data[p] = correctedPng.data[p + 1] = correctedPng.data[p + 2] = correctedPng.data[p + 3] = 0;
            } else {
              const rgb = palette[colorIdx].rgb;
              correctedPng.data[p] = rgb[0]; correctedPng.data[p + 1] = rgb[1]; correctedPng.data[p + 2] = rgb[2]; correctedPng.data[p + 3] = 255;
            }
            const isDiff = (pixels[i] !== rec.indices[i]);
            maskPng.data[p] = maskPng.data[p + 1] = maskPng.data[p + 2] = isDiff ? 255 : 0;
            maskPng.data[p + 3] = 255;
          }
          await atomicWrite(path.join(dataRoot, 'corrected', `${id}.png`), PNG.sync.write(correctedPng));
          await atomicWrite(path.join(dataRoot, 'edit_masks', `${id}.png`), PNG.sync.write(maskPng));

          const meta = {
            id,
            source: `sources/${id}.png`,
            prediction: `predictions/${id}.png`,
            corrected: `corrected/${id}.png`,
            edit_mask: `edit_masks/${id}.png`,
            width: rec.width,
            height: rec.height,
            model_version: rec.model_version,
            palette: 'MARD',
            accepted_without_edit: false,
            changed_pixels: diffCount,
            timestamp: new Date().toISOString()
          };
          await atomicWrite(path.join(dataRoot, 'meta', `${id}.json`), JSON.stringify(meta, null, 2));

          rec.status = 'pending';
          rec.annotation_source = 'ai';
          rec.changed_pixels = diffCount;
          rec.corrected_indices = pixels;
          await atomicWrite(recFile, JSON.stringify(rec, null, 2));

          console.log(`  [${processed + 1}/${limit}] ${id} (${rec.width}×${rec.height}) -> 已保存待审核标注 (${diffCount} 像素)`);
        }
        if (changed) {
          processed++;
          if (!doSave) console.log(`  [${processed}/${limit}] ${id} (${rec.width}×${rec.height}) -> 有可清理背景，未写入`);
        }
      }

      console.log(`\n✨ 批量预处理完成! 共发现 ${processed} 条候选${doSave ? '并保存为待审核标注' : '，未写入'}。\n`);
      return;
    }

    if (command === 'edit') {
      const id = args._[1];
      if (!id) throw new Error('请指定样本 ID');
      const recFile = path.join(dataRoot, 'indices', `${id}.json`);
      const rec = JSON.parse(await readFile(recFile, 'utf8'));
      const width = rec.width, height = rec.height;
      let pixels = [...(rec.corrected_indices || rec.indices)];
      const opsApplied = [];

      // Auto background removal
      if (args['remove-bg']) {
        const res = removeBackground(pixels, width, height);
        if (res) {
          pixels = res.pixels;
          opsApplied.push(`一键去背景 (去除 ${res.clearedCount} 个像素)`);
        }
      }

      // Fringe cleanup
      if (args['clean-fringe']) {
        const res = cleanColorFringe(pixels, width, height);
        if (res) {
          pixels = res.pixels;
          opsApplied.push(`净化彩边 (纯黑描边 ${res.outlinePixels} 格，清理杂色 ${res.clearedPixels} 格)`);
        }
      }

      // Replace color
      if (args.replace) {
        const [fromStr, toStr] = String(args.replace).split(':');
        const fromColor = resolveColor(fromStr);
        const toColor = resolveColor(toStr);
        let count = 0;
        pixels = pixels.map(p => {
          if (p === fromColor) { count++; return toColor; }
          return p;
        });
        opsApplied.push(`替换颜色: ${colorDesc(fromColor)} -> ${colorDesc(toColor)} (共 ${count} 格)`);
      }

      // Set individual pixels: --set 5,10:H07 6,10:T01 ...
      if (args.set) {
        const items = Array.isArray(args.set) ? args.set : [args.set];
        let count = 0;
        for (const item of items) {
          const parts = String(item).split(' ');
          for (const p of parts) {
            if (!p.includes(':')) continue;
            const [coord, cStr] = p.split(':');
            const [x, y] = coord.split(',').map(Number);
            if (x >= 0 && x < width && y >= 0 && y < height) {
              pixels[y * width + x] = resolveColor(cStr);
              count++;
            }
          }
        }
        opsApplied.push(`设置像素点: ${count} 处`);
      }

      // Erase pixels: --erase 5,10 6,10 ...
      if (args.erase) {
        const items = Array.isArray(args.erase) ? args.erase : [args.erase];
        let count = 0;
        for (const item of items) {
          const coords = String(item).split(' ');
          for (const c of coords) {
            const [x, y] = c.split(',').map(Number);
            if (x >= 0 && x < width && y >= 0 && y < height) {
              pixels[y * width + x] = -1;
              count++;
            }
          }
        }
        opsApplied.push(`擦除为透明: ${count} 处`);
      }

      // Draw line: --line x0,y0,x1,y1:color
      if (args.line) {
        const [coords, cStr] = String(args.line).split(':');
        const [x0, y0, x1, y1] = coords.split(',').map(Number);
        const col = resolveColor(cStr);
        pixels = drawLine(pixels, width, height, x0, y0, x1, y1, col);
        opsApplied.push(`绘制直线 (${x0},${y0}) -> (${x1},${y1}) 颜色: ${colorDesc(col)}`);
      }

      // Draw rect: --rect x0,y0,x1,y1:color
      if (args.rect) {
        const [coords, cStr] = String(args.rect).split(':');
        const [x0, y0, x1, y1] = coords.split(',').map(Number);
        const col = resolveColor(cStr);
        pixels = drawRect(pixels, width, height, x0, y0, x1, y1, col, false);
        opsApplied.push(`绘制矩形框 (${x0},${y0}) 到 (${x1},${y1}) 颜色: ${colorDesc(col)}`);
      }

      // Draw filled rect: --rect-fill x0,y0,x1,y1:color
      if (args['rect-fill']) {
        const [coords, cStr] = String(args['rect-fill']).split(':');
        const [x0, y0, x1, y1] = coords.split(',').map(Number);
        const col = resolveColor(cStr);
        pixels = drawRect(pixels, width, height, x0, y0, x1, y1, col, true);
        opsApplied.push(`填充矩形 (${x0},${y0}) 到 (${x1},${y1}) 颜色: ${colorDesc(col)}`);
      }

      // Flood fill: --fill x,y:color
      if (args.fill) {
        const [coord, cStr] = String(args.fill).split(':');
        const [x, y] = coord.split(',').map(Number);
        const col = resolveColor(cStr);
        pixels = floodFill(pixels, width, height, x, y, col);
        opsApplied.push(`区域油漆桶填充 (${x},${y}) 颜色: ${colorDesc(col)}`);
      }

      // Compute changes
      const changed = pixels.reduce((acc, val, i) => acc + Number(val !== rec.indices[i]), 0);
      rec.corrected_indices = pixels;
      rec.changed_pixels = changed;
      await atomicWrite(recFile, JSON.stringify(rec, null, 2));

      const previewPath = `/tmp/annot_${id}.png`;
      await generateSideBySidePreview(dataRoot, rec, previewPath);

      console.log(`\n🎨 样本 ${id} 编辑完成:`);
      opsApplied.forEach(op => console.log(`  ✓ ${op}`));
      console.log(`\n📊 距模型预测累计修改像素: ${changed} 格`);
      console.log(`🖼️ 更新后预览图: ${previewPath}`);
      return;
    }

    if (command === 'save') {
      const id = args._[1];
      if (!id) throw new Error('请指定样本 ID');
      const accept = Boolean(args.accept);
      const saveStatus = String(args.status || 'pending');
      if (!['pending', 'human_edited'].includes(saveStatus)) {
        throw new Error('save 的状态只能是 pending 或 human_edited');
      }
      const recFile = path.join(dataRoot, 'indices', `${id}.json`);
      const rec = JSON.parse(await readFile(recFile, 'utf8'));

      const edited = accept ? [...rec.indices] : (rec.corrected_indices || [...rec.indices]);
      const changed = edited.reduce((acc, val, i) => acc + Number(val !== rec.indices[i]), 0);
      if (accept && changed > 0) {
        console.log(`⚠️ --accept 模式会舍弃已进行的 ${changed} 处修改，以原始预测通过。`);
      }

      // Render corrected PNG
      const correctedPng = new PNG({ width: rec.width, height: rec.height });
      const maskPng = new PNG({ width: rec.width, height: rec.height });

      for (let i = 0; i < edited.length; i++) {
        const p = i * 4;
        const colorIdx = edited[i];
        if (colorIdx < 0) {
          correctedPng.data[p] = 0; correctedPng.data[p + 1] = 0; correctedPng.data[p + 2] = 0; correctedPng.data[p + 3] = 0;
        } else {
          const rgb = palette[colorIdx].rgb;
          correctedPng.data[p] = rgb[0]; correctedPng.data[p + 1] = rgb[1]; correctedPng.data[p + 2] = rgb[2]; correctedPng.data[p + 3] = 255;
        }

        const isChanged = (edited[i] !== rec.indices[i]);
        maskPng.data[p] = isChanged ? 255 : 0;
        maskPng.data[p + 1] = isChanged ? 255 : 0;
        maskPng.data[p + 2] = isChanged ? 255 : 0;
        maskPng.data[p + 3] = 255;
      }

      await atomicWrite(path.join(dataRoot, 'corrected', `${id}.png`), PNG.sync.write(correctedPng));
      await atomicWrite(path.join(dataRoot, 'edit_masks', `${id}.png`), PNG.sync.write(maskPng));

      const meta = {
        id,
        source: `sources/${id}.png`,
        prediction: `predictions/${id}.png`,
        corrected: `corrected/${id}.png`,
        edit_mask: `edit_masks/${id}.png`,
        width: rec.width,
        height: rec.height,
        model_version: rec.model_version,
        palette: 'MARD',
        accepted_without_edit: accept,
        changed_pixels: accept ? 0 : changed,
        timestamp: new Date().toISOString(),
        annotation_source: 'ai'
      };

      await atomicWrite(path.join(dataRoot, 'meta', `${id}.json`), JSON.stringify(meta, null, 2));

      rec.status = saveStatus;
      rec.annotation_source = 'ai';
      delete rec.reviewed_at;
      rec.changed_pixels = accept ? 0 : changed;
      rec.corrected_indices = edited;
      await atomicWrite(recFile, JSON.stringify(rec, null, 2));

      const previewPath = `/tmp/annot_${id}.png`;
      await generateSideBySidePreview(dataRoot, rec, previewPath);

      console.log(`\n💾 样本 ${id} 保存成功!`);
      console.log(`- 状态: ${rec.status}`);
      console.log(`- 修改像素: ${rec.changed_pixels} 格`);
      console.log(`- 纠错图: SQLite images/corrected/${id}`);
      console.log(`- 编辑 Mask: SQLite images/edit_masks/${id}`);
      console.log(`- 元数据: SQLite metadata/${id}`);
      console.log(`- 预览图: ${previewPath}\n`);
      return;
    }

    throw new Error(`未知命令: "${command}"。输入 node scripts/pixel_annotate.mjs help 查看使用说明。`);
  } catch (err) {
    console.error(`\n❌ 错误: ${err.message || err}\n`);
    process.exit(1);
  }
}

main();
