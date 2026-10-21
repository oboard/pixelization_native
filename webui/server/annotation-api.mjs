import { clientApi } from './annotation-client-api.mjs';
import { link, mkdir, mkdtemp, readFile, rename, rm, unlink, writeFile } from 'node:fs/promises';
import { execFile } from 'node:child_process';
import { promisify } from 'node:util';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { PNG } from 'pngjs';
import { getImage, getMeta, getSample, listReview, listReviewReasons, listSamples, nextAutoId, nextQueueOrder, putImage, putMeta, putSample, setQueueOrder, transaction } from './annotation-db.mjs';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const dataRoot = path.resolve(process.env.PIXEL_ANNOTATION_DATA_ROOT || path.join(root, 'data'));
const projectRoot = path.resolve(root, '..');
const runFile = promisify(execFile);
const predictionSizes = [24, 52, 78, 104];
const mapping = JSON.parse(await readFile(path.join(root, 'src/app/colorSystemMapping.json'), 'utf8'));
const palette = Object.entries(mapping).map(([hex, names]) => ({ hex, code: names.MARD }));
const safeId = /^[a-zA-Z0-9_-]{1,80}$/;
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

async function bodyBuffer(req) {
  const chunks = [];
  let size = 0;
  for await (const chunk of req) {
    size += chunk.length;
    if (size > 12_000_000) throw new Error('请求超过 12 MB');
    chunks.push(chunk);
  }
  return Buffer.concat(chunks);
}

async function body(req) { return JSON.parse((await bodyBuffer(req)).toString('utf8')); }

function binaryBody(buffer, magic, headerLength, sections) {
  if (buffer.length < headerLength || buffer.toString('ascii', 0, 4) !== magic || buffer.readUInt8(4) !== 1) {
    throw new Error('二进制请求格式无效');
  }
  const lengths = Array.from({ length: sections }, (_, index) => buffer.readUInt32LE(8 + index * 4));
  if (headerLength + lengths.reduce((sum, length) => sum + length, 0) !== buffer.length) throw new Error('二进制请求长度无效');
  let offset = headerLength;
  return lengths.map(length => { const section = buffer.subarray(offset, offset + length); offset += length; return section; });
}

function decodePng(dataUrl) {
  if (!Buffer.isBuffer(dataUrl) && (typeof dataUrl !== 'string' || !/^data:image\/png;base64,/.test(dataUrl))) throw new Error('请上传 PNG 图片');
  const png = PNG.sync.read(Buffer.isBuffer(dataUrl) ? dataUrl : Buffer.from(dataUrl.split(',')[1], 'base64'));
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
  await mkdir(path.join(dataRoot, 'sources'), { recursive: true });
}

function samplePaths(id) {
  return {
    source: `sources/${id}.png`, prediction: `predictions/${id}.png`,
    corrected: `corrected/${id}.png`, edit_mask: `edit_masks/${id}.png`,
  };
}

function requiredSample(id) {
  const record = getSample(id);
  if (record) return record;
  const error = new Error('样本不存在');
  error.status = 404;
  throw error;
}

function encodedSample(record, id) {
  const { indices, corrected_indices: corrected, ...details } = record;
  const metadata = Buffer.from(JSON.stringify({ ...details, status: sampleStatus(record), paths: samplePaths(id) }));
  const count = indices.length;
  const result = Buffer.allocUnsafe(16 + metadata.length + count * 2 * (corrected ? 2 : 1));
  result.write('PXAN', 0, 'ascii');
  result.writeUInt8(1, 4);
  result.writeUInt8(corrected ? 1 : 0, 5);
  result.writeUInt16LE(0, 6);
  result.writeUInt32LE(metadata.length, 8);
  result.writeUInt32LE(count, 12);
  metadata.copy(result, 16);
  let position = 16 + metadata.length;
  for (const value of indices) { result.writeInt16LE(value, position); position += 2; }
  if (corrected) for (const value of corrected) { result.writeInt16LE(value, position); position += 2; }
  return result;
}

async function importWithGeneratedPredictions(id, sourcePng) {
  if (id && predictionSizes.some(size => getSample(`${id}_${size}`))) {
    const conflict = new Error('四种尺寸中已有同名样本');
    conflict.status = 409;
    throw conflict;
  }
  const temporary = await mkdtemp(path.join(tmpdir(), 'pixel-review-import-'));
  const sourcePath = path.join(temporary, 'source.png');
  const linked = [];
  try {
    await writeFile(sourcePath, sourcePng);
    const python = process.env.PIXEL_ANNOTATION_PYTHON || path.join(projectRoot, '.venv/bin/python');
    await runFile(python, [path.join(projectRoot, 'scripts/seed_annotation_samples.py'),
      '--predict-source', sourcePath, '--prediction-dir', temporary],
      { cwd: projectRoot, timeout: 300_000, maxBuffer: 1024 * 1024 });
    const predictions = await Promise.all(predictionSizes.map(async size => {
      const png = await readFile(path.join(temporary, `${size}.png`));
      const decoded = decodePng(png);
      if (decoded.width !== size || decoded.height !== size) throw new Error(`模型生成的 ${size} 像素预测尺寸无效`);
      return { png, decoded, size };
    }));
    const baseId = id || nextAutoId();
    const ids = predictionSizes.map(size => `${baseId}_${size}`);
    if (ids.some(sampleId => getSample(sampleId))) throw new Error('样本 ID 已存在');
    for (const sampleId of ids) {
      const target = path.join(dataRoot, 'sources', `${sampleId}.png`);
      await link(sourcePath, target);
      linked.push(target);
    }
    transaction(() => {
      if (ids.some(sampleId => getSample(sampleId))) throw new Error('样本 ID 已存在');
      let order = nextQueueOrder();
      for (let index = 0; index < ids.length; index++) {
        const { png, decoded, size } = predictions[index];
        const sampleId = ids[index];
        putImage(sampleId, 'predictions', png);
        putSample({ id: sampleId, width: size, height: size,
          model_version: 'python-test-pro-mps', indices: indicesFromPng(decoded),
          status: 'unmodified', changed_pixels: 0 });
        setQueueOrder(sampleId, order++);
      }
    });
    return { baseId, ids };
  } catch (error) {
    await Promise.all(linked.map(target => unlink(target).catch(() => {})));
    throw error;
  } finally {
    await rm(temporary, { recursive: true, force: true });
  }
}

export async function annotationApi(req, res) {
  const url = new URL(req.url, 'http://localhost');
  if (!url.pathname.startsWith('/api/annotation/')) return false;
  try {
    if (await clientApi(req, res, { url, dataRoot, projectRoot, palette, body, json })) return true;
    await ensureFolders();
    const segments = url.pathname.split('/').filter(Boolean);
    if (segments[2] === 'palette' && req.method === 'GET') return json(res, 200, palette) || true;
    if (segments[2] === 'review' && segments[3] === 'reasons' && segments.length === 4 && req.method === 'GET') {
      json(res, 200, listReviewReasons()); return true;
    }
    if (segments[2] === 'review' && (segments.length === 3 || segments[3] === 'history') && req.method === 'GET') {
      const historyMode = segments[3] === 'history';
      const size = url.searchParams.get('size') || '';
      if (size && !['24', '52', '78', '104'].includes(size)) throw new Error('无效的尺寸筛选');
      const offset = Math.max(0, Number.parseInt(url.searchParams.get('offset') || '0', 10) || 0);
      const limit = Math.max(1, Math.min(100, Number.parseInt(url.searchParams.get('limit') || '40', 10) || 40));
      json(res, 200, listReview({ offset, limit, size, historyMode })); return true;
    }
    if (segments[2] === 'samples' && segments.length === 3 && req.method === 'GET') {
      const query = (url.searchParams.get('q') || '').trim().toLowerCase().slice(0, 80);
      const size = url.searchParams.get('size') || '';
      if (size && !['24', '52', '78', '104'].includes(size)) throw new Error('无效的尺寸筛选');
      const offset = Math.max(0, Number.parseInt(url.searchParams.get('offset') || '0', 10) || 0);
      const limit = Math.max(1, Math.min(200, Number.parseInt(url.searchParams.get('limit') || '100', 10) || 100));
      json(res, 200, listSamples({ offset, limit, query, size })); return true;
    }
    if (segments[2] === 'samples' && segments.length === 3 && req.method === 'POST') {
      const binary = req.headers['content-type']?.startsWith('application/vnd.pixel-review.import');
      let submitted, sourcePng, predicted;
      if (binary) {
        const [metadata, source, prediction] = binaryBody(await bodyBuffer(req), 'PXIM', 20, 3);
        submitted = JSON.parse(metadata.toString('utf8'));
        sourcePng = source;
        predicted = prediction.length ? decodePng(prediction) : null;
      } else {
        submitted = await body(req);
        if (typeof submitted.source !== 'string' || !/^data:image\/png;base64,/.test(submitted.source)) throw new Error('原图必须是 PNG');
        sourcePng = Buffer.from(submitted.source.split(',')[1], 'base64');
        predicted = submitted.prediction ? decodePng(submitted.prediction) : null;
      }
      const requestedId = String(submitted.id || '').trim();
      if (requestedId && !safeId.test(requestedId)) throw new Error('样本 ID 仅可使用字母、数字、下划线和连字符');
      PNG.sync.read(sourcePng);
      if (!predicted) {
        const { baseId, ids } = await importWithGeneratedPredictions(requestedId, sourcePng);
        json(res, 201, { id: ids[0], base_id: baseId, ids }); return true;
      }
      const id = requestedId || nextAutoId();
      if (getSample(id)) { json(res, 409, { error: '样本 ID 已存在' }); return true; }
      const record = { id, width: predicted.width, height: predicted.height,
        model_version: String(submitted.model_version || 'unknown').slice(0, 100),
        indices: indicesFromPng(predicted), status: 'unmodified', changed_pixels: 0 };
      await atomicWrite(path.join(dataRoot, 'sources', `${id}.png`), sourcePng);
      transaction(() => {
        putImage(id, 'predictions', PNG.sync.write(predicted));
        putSample(record);
        setQueueOrder(id, nextQueueOrder());
      });
      json(res, 201, { id }); return true;
    }
    const id = segments[3];
    if (segments[2] === 'samples' && safeId.test(id || '') && segments[4] === 'image' && req.method === 'GET') {
      const kind = url.searchParams.get('kind');
      if (!['sources', 'predictions', 'corrected', 'edit_masks'].includes(kind)) throw new Error('无效图片类型');
      const png = kind === 'sources' ? await readFile(path.join(dataRoot, kind, `${id}.png`)) : getImage(id, kind);
      if (!png) { json(res, 404, { error: '图片不存在' }); return true; }
      res.writeHead(200, { 'Content-Type': 'image/png', 'Cache-Control': 'no-store' }); res.end(png); return true;
    }
    if (segments[2] === 'samples' && safeId.test(id || '') && segments.length === 4 && req.method === 'GET') {
      const record = requiredSample(id);
      if (url.searchParams.get('format') === 'binary') {
        res.writeHead(200, { 'Content-Type': 'application/vnd.pixel-review.sample', 'Cache-Control': 'no-store' });
        res.end(encodedSample(record, id)); return true;
      }
      json(res, 200, { ...record, status: sampleStatus(record), paths: samplePaths(id) }); return true;
    }
    if (segments[2] === 'samples' && safeId.test(id || '') && segments[4] === 'review' && req.method === 'POST') {
      const input = await body(req);
      if (!['qualified', 'unqualified', 'pending'].includes(input.status)) throw new Error('无效的审核结果');
      const reason = String(input.reason || '').trim().slice(0, 500);
      if (input.status === 'unqualified' && !reason) throw new Error('请填写不合格原因');
      const record = requiredSample(id);
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
      const meta = getMeta(id) || { id, ...samplePaths(id), width: record.width, height: record.height,
          model_version: record.model_version, palette: 'MARD', accepted_without_edit: false,
          changed_pixels: record.changed_pixels || 0, timestamp: new Date().toISOString() };
      meta.review_status = input.status;
      meta.reviewed_at = record.reviewed_at;
      meta.review_history = record.review_history;
      if (input.status === 'unqualified') meta.review_reason = reason;
      else delete meta.review_reason;
      transaction(() => { putSample(record); putMeta(id, meta); });
      json(res, 200, { id, status: input.status }); return true;
    }
    if (segments[2] === 'samples' && safeId.test(id || '') && segments[4] === 'status' && req.method === 'POST') {
      const input = await body(req);
      const nextStatus = input.status;
      if (!['pending', 'human_edited'].includes(nextStatus)) throw new Error('请通过最终审核页面设置审核结果');
      const record = requiredSample(id);
      if (!record.corrected_indices) throw new Error('请先保存纠错图，再送审核');
      if (reviewed.has(sampleStatus(record))) throw new Error('请在最终审核页更正或撤回审核结果');
      record.status = nextStatus;
      const meta = getMeta(id) || { id, ...samplePaths(id), width: record.width, height: record.height,
        model_version: record.model_version, palette: 'MARD', changed_pixels: record.changed_pixels || 0,
        timestamp: new Date().toISOString() };
      meta.accepted_without_edit = false;
      transaction(() => { putSample(record); putMeta(id, meta); });
      json(res, 200, { success: true, id, status: nextStatus }); return true;
    }
    if (segments[2] === 'samples' && safeId.test(id || '') && segments[4] === 'save' && req.method === 'POST') {
      let input;
      if (req.headers['content-type']?.startsWith('application/vnd.pixel-review.save')) {
        const bytes = await bodyBuffer(req);
        const [pixels] = binaryBody(bytes, 'PXSV', 12, 1);
        if (pixels.length % 2) throw new Error('像素数据长度无效');
        input = { accept: Boolean(bytes.readUInt8(5) & 1),
          indices: Array.from({ length: pixels.length / 2 }, (_, index) => pixels.readInt16LE(index * 2)) };
      } else input = await body(req);
      const record = requiredSample(id);
      const edited = input.accept ? record.indices : input.indices;
      if (!Array.isArray(edited) || edited.length !== record.width * record.height ||
          edited.some(value => !Number.isInteger(value) || value < -1 || value >= palette.length)) throw new Error('像素索引无效');
      const changed = edited.reduce((total, value, i) => total + Number(value !== record.indices[i]), 0);
      if (input.accept && changed) throw new Error('直接通过不能包含修改');
      const paths = samplePaths(id);
      const correctedPng = renderedPng(record.width, record.height, edited);
      const maskPng = renderedPng(record.width, record.height, edited, true, record.indices);
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
      record.corrected_indices = [...edited];
      transaction(() => {
        putImage(id, 'corrected', correctedPng);
        putImage(id, 'edit_masks', maskPng);
        putSample(record);
        putMeta(id, meta);
      });
      json(res, 200, meta); return true;
    }
    json(res, 404, { error: '接口不存在' }); return true;
  } catch (error) {
    json(res, error.status || (error.code === 'ENOENT' ? 404 : 400), { error: error.message || '请求失败' });
    return true;
  }
}
