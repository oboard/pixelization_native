import { readFile, readdir } from 'node:fs/promises';
import path from 'node:path';
import { createHash, timingSafeEqual } from 'node:crypto';
import { PNG } from 'pngjs';
import { clientQueue, clientNext, getSample, putSample, getMeta, putMeta, getImage, putImage,
  getAsset, putAsset, transaction } from './annotation-db.mjs';

const revision = content => content == null ? null : createHash('sha256').update(content).digest('hex');
const encode = content => Buffer.from(JSON.stringify(content));
const fail = (message, status = 400) => { throw Object.assign(new Error(message), { status }); };
const sampleKinds = new Set(['indices', 'meta', 'corrected', 'edit_masks']);
const validId = /^[a-zA-Z0-9_-]{1,80}$/;

export async function clientApi(req, res, { url, dataRoot, projectRoot, palette, body, json }) {
  if (!url.pathname.startsWith('/api/annotation/client/')) return false;
  const token = process.env.PIXEL_ANNOTATION_TOKEN;
  if (token) {
    const supplied = Buffer.from(req.headers.authorization || '');
    const expected = Buffer.from(`Bearer ${token}`);
    if (supplied.length !== expected.length || !timingSafeEqual(supplied, expected)) fail('客户端凭据无效', 401);
  }
  const parts = url.pathname.slice('/api/annotation/client/'.length).split('/').map(decodeURIComponent);
  const [route, kind, id] = parts;
  const profiles = path.resolve(process.env.PIXEL_ANNOTATION_PROFILES_ROOT || path.join(projectRoot, 'scripts/annotation_profiles'));
  const send = value => { json(res, 200, value); return true; };
  const current = (type, sampleId) => type === 'indices' ? getSample(sampleId) : getMeta(sampleId);
  const recordRevision = sampleId => revision(encode(getSample(sampleId)));
  const validPixels = (values, count) => Array.isArray(values) && values.length === count &&
    values.every(v => Number.isInteger(v) && v >= -1 && v < palette.length);
  if (route === 'palette' && req.method === 'GET') return send(palette);
  if (route === 'queue' && req.method === 'GET') {
    const params = url.searchParams;
    return send(clientQueue({ size: params.get('size') || '', status: params.get('status') || '',
      query: (params.get('q') || '').slice(0,80), offset: Math.max(0, parseInt(params.get('offset')) || 0),
      limit: Math.max(1, Math.min(200, parseInt(params.get('limit')) || 20)) }));
  }
  if (route === 'next' && req.method === 'GET') return send({ item: clientNext(url.searchParams.get('size') || '') });
  if (route === 'profiles' && req.method === 'GET') {
    const names = await readdir(profiles).catch(() => []);
    return send({ ids: names.filter(name => /^\d+\.json$/.test(name)).map(name => name.slice(0,-5)) });
  }
  if (route === 'resources' && parts.length === 3 && validId.test(id || '')) {
    if (kind === 'profiles' && !/^\d+$/.test(id)) fail('配方 ID 无效');
    let content;
    if (kind === 'profiles') content = await readFile(path.join(profiles, `${id}.json`)).catch(e => { if(e.code !== 'ENOENT') throw e; return null; });
    else if (kind === 'sources') content = await readFile(path.join(dataRoot, 'sources', `${id}.png`)).catch(e => { if(e.code !== 'ENOENT') throw e; return null; });
    else if (['indices', 'meta'].includes(kind)) { const value = current(kind,id); content = value == null ? null : encode(value); }
    else if (['predictions','corrected','edit_masks'].includes(kind)) content = getImage(id,kind);
    else fail('资源类型无效');
    if (req.method === 'GET') {
      if (content == null) fail('资源不存在',404);
      return send({ content: Buffer.from(content).toString('base64'), revision: revision(content) });
    }
    if (req.method === 'PUT' && kind === 'profiles') {
      const input = await body(req);
      const bytes = Buffer.from(input.content || '', 'base64');
      const profile = JSON.parse(bytes.toString());
      if (!profile || typeof profile !== 'object' || Array.isArray(profile)) fail('配方无效');
      // No await between checking and writing: serialize updates within this process.
      const { readFileSync, mkdirSync, writeFileSync, renameSync } = await import('node:fs');
      const file = path.join(profiles, `${id}.json`);
      const actual = (() => { try { return readFileSync(file); } catch(e) { if(e.code !== 'ENOENT') throw e; return null; } })();
      if (input.expected_revision !== revision(actual)) fail('配方已被其他节点修改，请重新读取',409);
      mkdirSync(profiles, { recursive:true });
      writeFileSync(`${file}.tmp`,bytes); renameSync(`${file}.tmp`,file);
      return send({ revision: revision(bytes) });
    }
  }
  if (route === 'assets' && parts.length === 1) {
    const name = url.searchParams.get('name') || '';
    if (!/^reviews\/recipes\/[\w-]+\.(png|json)$/.test(name)) fail('预览资源名称无效');
    if (req.method === 'GET') {
      const bytes = getAsset(name); if (!bytes) fail('预览不存在',404);
      return send({ content: Buffer.from(bytes).toString('base64') });
    }
    if (req.method === 'PUT') { const input = await body(req); putAsset(name, Buffer.from(input.content,'base64')); return send({ success:true }); }
  }
  if (route === 'samples' && parts.length === 2 && validId.test(kind || '') && req.method === 'PUT') {
    const sampleId = kind;
    const input = await body(req);
    if (!Array.isArray(input.writes) || !input.writes.length || input.writes.length > 8) fail('提交内容无效');
    const writes = input.writes.map(w => {
      if (!sampleKinds.has(w.kind)) fail('不能修改此资源');
      const bytes = Buffer.from(w.content || '', 'base64');
      return { kind:w.kind, bytes, value:['indices','meta'].includes(w.kind) ? JSON.parse(bytes.toString()) : null };
    });
    transaction(() => {
      const original = getSample(sampleId); if (!original) fail('样本不存在',404);
      if (input.expected_revision !== recordRevision(sampleId)) fail('样本已被其他节点修改，请重新读取后处理',409);
      const record = writes.find(w=>w.kind === 'indices')?.value;
      if (!record || record.id !== sampleId || record.width !== original.width || record.height !== original.height ||
        record.model_version !== original.model_version || JSON.stringify(record.indices) !== JSON.stringify(original.indices) ||
        !['unmodified','pending','human_edited','qualified','unqualified'].includes(record.status) ||
        (record.corrected_indices && !validPixels(record.corrected_indices, original.width*original.height))) fail('样本数据无效');
      if (['qualified','unqualified'].includes(record.status) && record.status !== original.status) fail('CLI 不能作最终审核');
      for (const w of writes) {
        if (w.kind === 'indices') putSample(record);
        else if (w.kind === 'meta') {
          if (w.value.id !== sampleId || w.value.width !== original.width || w.value.height !== original.height) fail('元数据无效');
          putMeta(sampleId,w.value);
        } else {
          const png = PNG.sync.read(w.bytes);
          if (png.width !== original.width || png.height !== original.height) fail('图片尺寸无效');
          putImage(sampleId,w.kind,w.bytes);
        }
      }
    });
    return send({ revision:recordRevision(sampleId) });
  }
  fail('客户端接口不存在',404);
}
