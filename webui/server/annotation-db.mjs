import { DatabaseSync } from 'node:sqlite';
import { deflateSync, inflateSync } from 'node:zlib';
import { existsSync, mkdirSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const dataRoot = path.resolve(process.env.PIXEL_ANNOTATION_DATA_ROOT || path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', 'data'));
mkdirSync(dataRoot, { recursive: true });
const databasePath = path.join(dataRoot, 'annotation.sqlite3');
if (!existsSync(databasePath) && existsSync(path.join(dataRoot, 'indices'))) {
  throw new Error('检测到旧版标注数据；请先运行 scripts/migrate_annotation_sqlite.py');
}
const db = new DatabaseSync(databasePath);
db.exec('PRAGMA journal_mode = WAL; PRAGMA synchronous = NORMAL; PRAGMA busy_timeout = 5000;');
db.exec(`
  CREATE TABLE IF NOT EXISTS samples (
    id TEXT PRIMARY KEY, sort_key TEXT NOT NULL, width INTEGER NOT NULL,
    height INTEGER NOT NULL, model_version TEXT NOT NULL, status TEXT NOT NULL,
    changed_pixels INTEGER NOT NULL DEFAULT 0, reviewed_at TEXT,
    review_reason TEXT, review_history TEXT, history_count INTEGER NOT NULL DEFAULT 0,
    has_corrected INTEGER NOT NULL DEFAULT 0, has_meta INTEGER NOT NULL DEFAULT 0,
    queue_order INTEGER NOT NULL DEFAULT 0,
    record BLOB NOT NULL
  );
  CREATE INDEX IF NOT EXISTS samples_sort ON samples(sort_key);
  CREATE INDEX IF NOT EXISTS samples_review ON samples(status, has_corrected, sort_key);
  CREATE INDEX IF NOT EXISTS samples_history ON samples(history_count, reviewed_at);
  CREATE INDEX IF NOT EXISTS samples_size ON samples(width, sort_key);
  CREATE TABLE IF NOT EXISTS images (
    id TEXT NOT NULL, kind TEXT NOT NULL, png BLOB NOT NULL,
    PRIMARY KEY (id, kind)
  );
  CREATE TABLE IF NOT EXISTS metadata (
    id TEXT PRIMARY KEY, json TEXT NOT NULL
  );
  CREATE TABLE IF NOT EXISTS assets (
    path TEXT PRIMARY KEY, content BLOB NOT NULL
  );
`);
if (!db.prepare('PRAGMA table_info(samples)').all().some(column => column.name === 'queue_order')) {
  db.exec('ALTER TABLE samples ADD COLUMN queue_order INTEGER NOT NULL DEFAULT 0');
}

const sampleStatus = record => {
  if (['unmodified', 'pending', 'human_edited', 'qualified', 'unqualified'].includes(record.status)) return record.status;
  if (record.status === 'accepted') return 'qualified';
  if (record.status === 'edited') return record.annotation_source === 'human' ? 'human_edited' : 'pending';
  return record.corrected_indices ? 'pending' : 'unmodified';
};

const reviewHistory = record => {
  if (Array.isArray(record.review_history) && record.review_history.length) return record.review_history;
  const status = sampleStatus(record);
  return ['qualified', 'unqualified'].includes(status)
    ? [{ from: null, to: status, reason: record.review_reason || '', timestamp: record.reviewed_at || null }]
    : [];
};

const sortKey = id => id.replace(/\d+/g, number => number.padStart(12, '0'));
const insertSample = db.prepare(`
  INSERT INTO samples (id, sort_key, width, height, model_version, status, changed_pixels,
    reviewed_at, review_reason, review_history, history_count, has_corrected, has_meta, record)
  VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, COALESCE((SELECT has_meta FROM samples WHERE id = ?), 0), ?)
  ON CONFLICT(id) DO UPDATE SET
    sort_key=excluded.sort_key, width=excluded.width, height=excluded.height,
    model_version=excluded.model_version, status=excluded.status,
    changed_pixels=excluded.changed_pixels, reviewed_at=excluded.reviewed_at,
    review_reason=excluded.review_reason, review_history=excluded.review_history,
    history_count=excluded.history_count, has_corrected=excluded.has_corrected,
    record=excluded.record
`);
const selectSample = db.prepare('SELECT record FROM samples WHERE id = ?');
const insertImage = db.prepare('INSERT INTO images (id, kind, png) VALUES (?, ?, ?) ON CONFLICT(id, kind) DO UPDATE SET png=excluded.png');
const selectImage = db.prepare('SELECT png FROM images WHERE id = ? AND kind = ?');
const insertMeta = db.prepare('INSERT INTO metadata (id, json) VALUES (?, ?) ON CONFLICT(id) DO UPDATE SET json=excluded.json');
const selectMeta = db.prepare('SELECT json FROM metadata WHERE id = ?');
const markMeta = db.prepare('UPDATE samples SET has_meta = 1 WHERE id = ?');

export function getSample(id) {
  const row = selectSample.get(id);
  if (!row) return null;
  return JSON.parse(inflateSync(row.record).toString('utf8'));
}

export function putSample(record) {
  const history = reviewHistory(record);
  insertSample.run(record.id, sortKey(record.id), record.width, record.height,
    record.model_version, sampleStatus(record), record.changed_pixels || 0,
    record.reviewed_at || null, record.review_reason || null,
    JSON.stringify(history), history.length, Number(Boolean(record.corrected_indices)),
    record.id, deflateSync(JSON.stringify(record), { level: 1 }));
}

export function getImage(id, kind) { return selectImage.get(id, kind)?.png || null; }
export function putImage(id, kind, png) { insertImage.run(id, kind, png); }
export function getMeta(id) {
  const row = selectMeta.get(id);
  return row ? JSON.parse(row.json) : null;
}
export function putMeta(id, meta) {
  insertMeta.run(id, JSON.stringify(meta));
  markMeta.run(id);
}

export function transaction(work) {
  db.exec('BEGIN IMMEDIATE');
  try {
    const result = work();
    db.exec('COMMIT');
    return result;
  } catch (error) {
    db.exec('ROLLBACK');
    throw error;
  }
}

export function nextQueueOrder() {
  return db.prepare('SELECT coalesce(max(queue_order), 0) + 1 AS next FROM samples').get().next;
}

export function nextAutoId() {
  let highest = 0;
  for (const { id } of db.prepare("SELECT id FROM samples WHERE id GLOB '[0-9]*'").all()) {
    const match = /^(\d+)(?:_(?:24|52|78|104))?$/.exec(id);
    if (match) highest = Math.max(highest, Number(match[1]));
  }
  return String(highest + 1);
}

export function setQueueOrder(id, order) {
  db.prepare('UPDATE samples SET queue_order = ? WHERE id = ?').run(order, id);
}

export function listSamples({ offset, limit, query, size }) {
  const where = ['(? = \'\' OR instr(lower(id), ?) > 0)', '(? = \'\' OR width = ?)'];
  const args = [query, query.toLowerCase(), size, Number(size) || 0];
  const condition = where.join(' AND ');
  const total = db.prepare(`SELECT count(*) AS n FROM samples WHERE ${condition}`).get(...args).n;
  const items = db.prepare(`SELECT id, width, height, model_version, status, changed_pixels
    FROM samples WHERE ${condition}
    ORDER BY CASE WHEN status = 'unqualified' AND has_corrected = 1 THEN 0 ELSE 1 END, queue_order, sort_key
    LIMIT ? OFFSET ?`).all(...args, limit, offset);
  const allTotal = db.prepare('SELECT count(*) AS n FROM samples').get().n;
  const completed = db.prepare("SELECT count(*) AS n FROM samples WHERE status = 'qualified' AND has_meta = 1").get().n;
  return { items, total, all_total: allTotal, completed, offset, limit };
}

export function listReview({ offset, limit, size, historyMode }) {
  const condition = historyMode
    ? 'history_count > 0 AND has_corrected = 1 AND (? = \'\' OR width = ?)'
    : "status IN ('pending', 'human_edited') AND has_corrected = 1 AND (? = '' OR width = ?)";
  const args = [size, Number(size) || 0];
  const total = db.prepare(`SELECT count(*) AS n FROM samples WHERE ${condition}`).get(...args).n;
  const rows = db.prepare(`SELECT id, width, height, model_version, status, changed_pixels,
    reviewed_at, review_reason, review_history FROM samples WHERE ${condition}
    ORDER BY ${historyMode ? 'coalesce(reviewed_at, \'\') DESC, ' : ''}sort_key
    LIMIT ? OFFSET ?`).all(...args, limit, offset);
  const items = rows.map(row => ({ ...row, review_history: historyMode ? JSON.parse(row.review_history || '[]') : undefined }));
  return { items, total, offset, limit };
}
