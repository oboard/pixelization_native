import { mkdir, readFile, readdir, rename, writeFile } from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { PNG } from 'pngjs';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const dataRoot = path.join(root, 'data');
const mapping = JSON.parse(await readFile(path.join(root, 'src/app/colorSystemMapping.json'), 'utf8'));
const palette = Object.entries(mapping).map(([hex, names]) => ({ hex, code: names.MARD }));
const safeId = /^[a-zA-Z0-9_-]{1,80}$/;
const folders = ['sources', 'predictions', 'corrected', 'edit_masks', 'meta', 'indices'];

function json(res, status, value) {
  res.writeHead(status, { 'Content-Type': 'application/json; charset=utf-8', 'Cache-Control': 'no-store' });
  res.end(JSON.stringify(value));
}

async function body(req) {
  const chunks = [];
  let size = 0;
  for await (const chunk of req) {
    size += chunk.length;
    if (size > 12_000_000) throw new Error('请求超过 12 MB');
    chunks.push(chunk);
  }
  return JSON.parse(Buffer.concat(chunks).toString('utf8'));
}

function decodePng(dataUrl) {
  if (typeof dataUrl !== 'string' || !/^data:image\/png;base64,/.test(dataUrl)) throw new Error('请上传 PNG 图片');
  const png = PNG.sync.read(Buffer.from(dataUrl.split(',')[1], 'base64'));
  if (!png.width || !png.height || png.width > 256 || png.height > 256) throw new Error('预测图尺寸需在 1–256 逻辑像素内');
  return png;
}

function nearest(r, g, b) {
  let best = 0;
  let distance = Infinity;
  for (let i = 0; i < palette.length; i++) {
    const hex = palette[i].hex;
    const dr = r - parseInt(hex.slice(1, 3), 16);
    const dg = g - parseInt(hex.slice(3, 5), 16);
    const db = b - parseInt(hex.slice(5, 7), 16);
    const d = dr * dr + dg * dg + db * db;
    if (d < distance) { distance = d; best = i; }
  }
  return best;
}

function indicesFromPng(png) {
  const indices = [];
  for (let i = 0; i < png.width * png.height; i++) {
    const p = i * 4;
    indices.push(png.data[p + 3] < 128 ? -1 : nearest(png.data[p], png.data[p + 1], png.data[p + 2]));
  }
  return indices;
}

function renderedPng(width, height, indices, mask = false, baseline = []) {
  const png = new PNG({ width, height });
  for (let i = 0; i < indices.length; i++) {
    const p = i * 4;
    if (mask) {
      const changed = indices[i] !== baseline[i];
      png.data[p] = png.data[p + 1] = png.data[p + 2] = changed ? 255 : 0;
      png.data[p + 3] = 255;
    } else if (indices[i] === -1) {
      png.data[p] = png.data[p + 1] = png.data[p + 2] = 0;
      png.data[p + 3] = 0;
    } else {
      const hex = palette[indices[i]].hex;
      png.data[p] = parseInt(hex.slice(1, 3), 16);
      png.data[p + 1] = parseInt(hex.slice(3, 5), 16);
      png.data[p + 2] = parseInt(hex.slice(5, 7), 16);
      png.data[p + 3] = 255;
    }
  }
  return PNG.sync.write(png);
}

async function atomicWrite(file, content) {
  const temporary = `${file}.${process.pid}.tmp`;
  await writeFile(temporary, content);
  await rename(temporary, file);
}

async function ensureFolders() {
  await Promise.all(folders.map(folder => mkdir(path.join(dataRoot, folder), { recursive: true })));
}

function samplePaths(id) {
  return {
    source: `sources/${id}.png`, prediction: `predictions/${id}.png`,
    corrected: `corrected/${id}.png`, edit_mask: `edit_masks/${id}.png`,
  };
}

export async function annotationApi(req, res) {
  const url = new URL(req.url, 'http://localhost');
  if (!url.pathname.startsWith('/api/annotation/')) return false;
  try {
    await ensureFolders();
    const segments = url.pathname.split('/').filter(Boolean);
    if (segments[2] === 'palette' && req.method === 'GET') return json(res, 200, palette) || true;
    if (segments[2] === 'samples' && segments.length === 3 && req.method === 'GET') {
      const allIds = (await readdir(path.join(dataRoot, 'indices')))
        .filter(name => name.endsWith('.json')).map(name => name.slice(0, -5))
        .sort((a, b) => a.localeCompare(b, 'en', { numeric: true }));
      const query = (url.searchParams.get('q') || '').trim().toLowerCase().slice(0, 80);
      const size = url.searchParams.get('size') || '';
      if (size && !['24', '52', '78', '104'].includes(size)) throw new Error('无效的尺寸筛选');
      const namedSize = /^\d+_(24|52|78|104)$/;
      const matchingIds = query ? allIds.filter(id => id.toLowerCase().includes(query)) : allIds;
      const ids = !size ? matchingIds : (await Promise.all(matchingIds.map(async id => {
        const match = id.match(namedSize);
        if (match) return match[1] === size ? id : null;
        const record = JSON.parse(await readFile(path.join(dataRoot, 'indices', `${id}.json`), 'utf8'));
        return record.width === Number(size) && record.height === Number(size) ? id : null;
      }))).filter(Boolean);
      const offset = Math.max(0, Number.parseInt(url.searchParams.get('offset') || '0', 10) || 0);
      const limit = Math.max(1, Math.min(200, Number.parseInt(url.searchParams.get('limit') || '100', 10) || 100));
      const pageIds = ids.slice(offset, offset + limit);
      const samples = await Promise.all(pageIds.map(async id => {
        const record = JSON.parse(await readFile(path.join(dataRoot, 'indices', `${id}.json`), 'utf8'));
        return { id, width: record.width, height: record.height, model_version: record.model_version,
          status: record.status || 'pending', changed_pixels: record.changed_pixels || 0 };
      }));
      const completed = (await readdir(path.join(dataRoot, 'meta'))).filter(name => name.endsWith('.json')).length;
      json(res, 200, { items: samples, total: ids.length, all_total: allIds.length, completed, offset, limit }); return true;
    }
    if (segments[2] === 'samples' && segments.length === 3 && req.method === 'POST') {
      const input = await body(req);
      const id = String(input.id || '').trim();
      if (!safeId.test(id)) throw new Error('样本 ID 仅可使用字母、数字、下划线和连字符');
      const sourceData = input.source;
      if (typeof sourceData !== 'string' || !/^data:image\/png;base64,/.test(sourceData)) throw new Error('原图必须是 PNG');
      const sourceBuffer = Buffer.from(sourceData.split(',')[1], 'base64');
      PNG.sync.read(sourceBuffer);
      const prediction = decodePng(input.prediction);
      const recordFile = path.join(dataRoot, 'indices', `${id}.json`);
      try { await readFile(recordFile); json(res, 409, { error: '样本 ID 已存在' }); return true; } catch (error) { if (error.code !== 'ENOENT') throw error; }
      const record = { id, width: prediction.width, height: prediction.height,
        model_version: String(input.model_version || 'unknown').slice(0, 100),
        indices: indicesFromPng(prediction), status: 'pending', changed_pixels: 0 };
      await atomicWrite(path.join(dataRoot, 'sources', `${id}.png`), sourceBuffer);
      await atomicWrite(path.join(dataRoot, 'predictions', `${id}.png`), PNG.sync.write(prediction));
      await atomicWrite(recordFile, JSON.stringify(record, null, 2));
      json(res, 201, { id }); return true;
    }
    const id = segments[3];
    if (segments[2] === 'samples' && safeId.test(id || '') && segments[4] === 'image' && req.method === 'GET') {
      const kind = url.searchParams.get('kind');
      if (!['sources', 'predictions', 'corrected', 'edit_masks'].includes(kind)) throw new Error('无效图片类型');
      const png = await readFile(path.join(dataRoot, kind, `${id}.png`));
      res.writeHead(200, { 'Content-Type': 'image/png', 'Cache-Control': 'no-store' }); res.end(png); return true;
    }
    if (segments[2] === 'samples' && safeId.test(id || '') && segments.length === 4 && req.method === 'GET') {
      const record = JSON.parse(await readFile(path.join(dataRoot, 'indices', `${id}.json`), 'utf8'));
      json(res, 200, { ...record, paths: samplePaths(id) }); return true;
    }
    if (segments[2] === 'samples' && safeId.test(id || '') && segments[4] === 'save' && req.method === 'POST') {
      const input = await body(req);
      const file = path.join(dataRoot, 'indices', `${id}.json`);
      const record = JSON.parse(await readFile(file, 'utf8'));
      const edited = input.accept ? record.indices : input.indices;
      if (!Array.isArray(edited) || edited.length !== record.width * record.height ||
          edited.some(value => !Number.isInteger(value) || value < -1 || value >= palette.length)) throw new Error('像素索引无效');
      const changed = edited.reduce((total, value, i) => total + Number(value !== record.indices[i]), 0);
      if (input.accept && changed) throw new Error('直接通过不能包含修改');
      const paths = samplePaths(id);
      await atomicWrite(path.join(dataRoot, paths.corrected), renderedPng(record.width, record.height, edited));
      await atomicWrite(path.join(dataRoot, paths.edit_mask), renderedPng(record.width, record.height, edited, true, record.indices));
      const meta = { id, ...paths, width: record.width, height: record.height,
        model_version: record.model_version, palette: 'MARD', accepted_without_edit: Boolean(input.accept),
        changed_pixels: changed, timestamp: new Date().toISOString() };
      await atomicWrite(path.join(dataRoot, 'meta', `${id}.json`), JSON.stringify(meta, null, 2));
      record.status = input.accept ? 'accepted' : 'edited'; record.changed_pixels = changed;
      record.corrected_indices = [...edited];
      await atomicWrite(file, JSON.stringify(record, null, 2));
      json(res, 200, meta); return true;
    }
    json(res, 404, { error: '接口不存在' }); return true;
  } catch (error) {
    json(res, error.code === 'ENOENT' ? 404 : 400, { error: error.message || '请求失败' });
    return true;
  }
}
