import { createServer } from 'node:http';
import { readFile } from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { annotationApi } from './annotation-api.mjs';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const port = Number(process.env.PORT || 4173);
const contentTypes = { '.html': 'text/html; charset=utf-8', '.js': 'text/javascript', '.css': 'text/css', '.svg': 'image/svg+xml', '.png': 'image/png' };

createServer(async (req, res) => {
  if (await annotationApi(req, res)) return;
  const url = new URL(req.url, 'http://localhost');
  const pathname = decodeURIComponent(url.pathname);
  const file = path.resolve(root, 'dist', `.${pathname}`);
  if (!file.startsWith(path.join(root, 'dist') + path.sep)) { res.writeHead(403); res.end(); return; }
  try {
    const data = await readFile(file);
    res.writeHead(200, { 'Content-Type': contentTypes[path.extname(file)] || 'application/octet-stream' });
    res.end(data);
  } catch {
    const html = await readFile(path.join(root, 'dist/index.html'));
    res.writeHead(200, { 'Content-Type': 'text/html; charset=utf-8' }); res.end(html);
  }
}).listen(port, () => console.log(`Annotation web UI: http://localhost:${port}/`));
