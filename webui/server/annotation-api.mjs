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
const statuses = new Set(['unmodified', 'pending', 'human_edited', 'qualified', 'unqualified']);
const reviewable = new Set(['pending', 'human_edited']);
const reviewed = new Set(['qualified', 'unqualified']);
function sampleStatus(record) {
  if (statuses.has(record.status)) return record.status;
  if (record.status === 'accepted') return 'qualified';
  if (record.status === 'edited') return record.annotation_source === 'human' ? 'human_edited' : 'pending';
  return record.corrected_indices ? 'pending' : 'unmodified';
}
function reviewHistory(record) {
  if (Array.isArray(record.review_history) && record.review_history.length) return record.review_history;
  const status = sampleStatus(record);
  return reviewed.has(status) ? [{ from: null, to: status,
    reason: record.review_reason || '', timestamp: record.reviewed_at || null }] : [];
}

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
    if (segments[2] === 'review' && (segments.length === 3 || segments[3] === 'history') && req.method === 'GET') {
      const historyMode = segments[3] === 'history';
      const size = url.searchParams.get('size') || '';
      if (size && !['24', '52', '78', '104'].includes(size)) throw new Error('无效的尺寸筛选');
      const names = (await readdir(path.join(dataRoot, 'corrected'))).filter(name => name.endsWith('.png'));
      const records = await Promise.all(names.map(async name => {
        const id = name.slice(0, -4);
        if (!safeId.test(id)) return null;
        const record = JSON.parse(await readFile(path.join(dataRoot, 'indices', `${id}.json`), 'utf8'));
        const status = sampleStatus(record);
        const history = reviewHistory(record);
        if (!(historyMode ? history.length > 0 : reviewable.has(status)) || !record.corrected_indices || (size && record.width !== Number(size))) return null;
        return { id, width: record.width, height: record.height, model_version: record.model_version,
          status, changed_pixels: record.changed_pixels || 0,
          reviewed_at: record.reviewed_at || null, review_reason: record.review_reason || '',
          review_history: historyMode ? history : undefined };
      }));
      const items = records.filter(Boolean).sort((a, b) => historyMode
        ? (b.reviewed_at || '').localeCompare(a.reviewed_at || '') || a.id.localeCompare(b.id, 'en', { numeric: true })
        : a.id.localeCompare(b.id, 'en', { numeric: true }));
      const offset = Math.max(0, Number.parseInt(url.searchParams.get('offset') || '0', 10) || 0);
      const limit = Math.max(1, Math.min(100, Number.parseInt(url.searchParams.get('limit') || '40', 10) || 40));
      json(res, 200, { items: items.slice(offset, offset + limit), total: items.length, offset, limit }); return true;
    }
    if (segments[2] === 'samples' && segments.length === 3 && req.method === 'GET') {
      const allIds = (await readdir(path.join(dataRoot, 'indices')))
        .filter(name => name.endsWith('.json')).map(name => name.slice(0, -5))
        .sort((a, b) => a.localeCompare(b, 'en', { numeric: true }));
      const query = (url.searchParams.get('q') || '').trim().toLowerCase().slice(0, 80);
      const size = url.searchParams.get('size') || '';
      if (size && !['24', '52', '78', '104'].includes(size)) throw new Error('无效的尺寸筛选');
      const namedSize = /^\d+_(24|52|78|104)$/;
      const matchingIds = query ? allIds.filter(id => id.toLowerCase().includes(query)) : allIds;
      const filteredIds = !size ? matchingIds : (await Promise.all(matchingIds.map(async id => {
        const match = id.match(namedSize);
        if (match) return match[1] === size ? id : null;
        const record = JSON.parse(await readFile(path.join(dataRoot, 'indices', `${id}.json`), 'utf8'));
        return record.width === Number(size) && record.height === Number(size) ? id : null;
      }))).filter(Boolean);
      // A rejected sample must be visible before untouched work, even when
      // it would otherwise be buried on a later page of the virtual list.
      const correctedNames = (await readdir(path.join(dataRoot, 'corrected')))
        .filter(name => name.endsWith('.png'));
      const rejectedIds = new Set((await Promise.all(correctedNames.map(async name => {
        const id = name.slice(0, -4);
        const record = JSON.parse(await readFile(path.join(dataRoot, 'indices', `${id}.json`), 'utf8'));
        return sampleStatus(record) === 'unqualified' ? id : null;
      }))).filter(Boolean));
      const ids = [...filteredIds.filter(id => rejectedIds.has(id)),
        ...filteredIds.filter(id => !rejectedIds.has(id))];
      const offset = Math.max(0, Number.parseInt(url.searchParams.get('offset') || '0', 10) || 0);
      const limit = Math.max(1, Math.min(200, Number.parseInt(url.searchParams.get('limit') || '100', 10) || 100));
      const pageIds = ids.slice(offset, offset + limit);
      const samples = await Promise.all(pageIds.map(async id => {
        const record = JSON.parse(await readFile(path.join(dataRoot, 'indices', `${id}.json`), 'utf8'));
        return { id, width: record.width, height: record.height, model_version: record.model_version,
          status: sampleStatus(record), changed_pixels: record.changed_pixels || 0 };
      }));
      const completed = (await Promise.all((await readdir(path.join(dataRoot, 'meta')))
        .filter(name => name.endsWith('.json')).map(async name => {
          const record = JSON.parse(await readFile(path.join(dataRoot, 'indices', name), 'utf8'));
          return sampleStatus(record) === 'qualified';
        }))).filter(Boolean).length;
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
        indices: indicesFromPng(prediction), status: 'unmodified', changed_pixels: 0 };
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
      json(res, 200, { ...record, status: sampleStatus(record), paths: samplePaths(id) }); return true;
    }
    if (segments[2] === 'samples' && safeId.test(id || '') && segments[4] === 'review' && req.method === 'POST') {
      const input = await body(req);
      if (!['qualified', 'unqualified', 'pending'].includes(input.status)) throw new Error('无效的审核结果');
      const reason = String(input.reason || '').trim().slice(0, 500);
      if (input.status === 'unqualified' && !reason) throw new Error('请填写不合格原因');
      const file = path.join(dataRoot, 'indices', `${id}.json`);
      const record = JSON.parse(await readFile(file, 'utf8'));
      const previous = sampleStatus(record);
      if (!(reviewable.has(previous) || reviewed.has(previous)) || !record.corrected_indices) throw new Error('这张图当前不可审核');
      if (input.status === 'pending' && !reviewed.has(previous)) throw new Error('只有已审核图片可以撤回');
      if (input.expected_status && input.expected_status !== previous) {
        const conflict = new Error('样本状态已被其他操作修改，请刷新后重试');
        conflict.status = 409;
        throw conflict;
      }
      if (previous === input.status) throw new Error('审核结果没有变化');
      const history = reviewHistory(record);
      record.status = input.status;
      record.reviewed_at = new Date().toISOString();
      record.review_history = [...history, { from: previous, to: input.status,
        reason: input.status === 'unqualified' ? reason : input.status === 'pending' ? '撤回审核' : '', timestamp: record.reviewed_at }];
      if (input.status === 'unqualified') record.review_reason = reason;
      else delete record.review_reason;
      await atomicWrite(file, JSON.stringify(record, null, 2));
      const metaFile = path.join(dataRoot, 'meta', `${id}.json`);
      let meta;
      try { meta = JSON.parse(await readFile(metaFile, 'utf8')); }
      catch (error) {
        if (error.code !== 'ENOENT') throw error;
        meta = { id, ...samplePaths(id), width: record.width, height: record.height,
          model_version: record.model_version, palette: 'MARD', accepted_without_edit: false,
          changed_pixels: record.changed_pixels || 0, timestamp: new Date().toISOString() };
      }
      meta.review_status = input.status;
      meta.reviewed_at = record.reviewed_at;
      meta.review_history = record.review_history;
      if (input.status === 'unqualified') meta.review_reason = reason;
      else delete meta.review_reason;
      await atomicWrite(metaFile, JSON.stringify(meta, null, 2));
      json(res, 200, { id, status: input.status }); return true;
    }
    if (segments[2] === 'samples' && safeId.test(id || '') && segments[4] === 'status' && req.method === 'POST') {
      const input = await body(req);
      const nextStatus = input.status;
      if (!['pending', 'human_edited'].includes(nextStatus)) throw new Error('请通过最终审核页面设置审核结果');
      const file = path.join(dataRoot, 'indices', `${id}.json`);
      const record = JSON.parse(await readFile(file, 'utf8'));
      if (!record.corrected_indices) throw new Error('请先保存纠错图，再送审核');
      if (reviewed.has(sampleStatus(record))) throw new Error('请在最终审核页更正或撤回审核结果');
      record.status = nextStatus;
      const metaFile = path.join(dataRoot, 'meta', `${id}.json`);
      {
        let meta;
        try {
          meta = JSON.parse(await readFile(metaFile, 'utf8'));
          meta.accepted_without_edit = false;
        } catch {
          const paths = samplePaths(id);
          meta = { id, ...paths, width: record.width, height: record.height,
            model_version: record.model_version, palette: 'MARD',
            accepted_without_edit: false,
            changed_pixels: record.changed_pixels || 0, timestamp: new Date().toISOString() };
        }
        await atomicWrite(metaFile, JSON.stringify(meta, null, 2));
      }
      await atomicWrite(file, JSON.stringify(record, null, 2));
      json(res, 200, { success: true, id, status: nextStatus }); return true;
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
      record.status = input.accept ? 'pending' : 'human_edited';
      record.annotation_source = input.accept ? 'human_accept' : 'human';
      record.changed_pixels = changed;
      delete record.reviewed_at;
      meta.annotation_source = record.annotation_source;
      delete meta.review_status;
      delete meta.reviewed_at;
      await atomicWrite(path.join(dataRoot, 'meta', `${id}.json`), JSON.stringify(meta, null, 2));
      record.corrected_indices = [...edited];
      await atomicWrite(file, JSON.stringify(record, null, 2));
      json(res, 200, meta); return true;
    }
    json(res, 404, { error: '接口不存在' }); return true;
  } catch (error) {
    json(res, error.status || (error.code === 'ENOENT' ? 404 : 400), { error: error.message || '请求失败' });
    return true;
  }
}
