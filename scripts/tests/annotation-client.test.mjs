import { test } from 'node:test';
import assert from 'node:assert/strict';
import { createServer } from 'node:http';
import { mkdtemp, mkdir, readFile, writeFile, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { execFile } from 'node:child_process';
import { promisify } from 'node:util';

const run = promisify(execFile);
const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..');
const temporary = await mkdtemp(path.join(tmpdir(), 'annotation-client-test-'));
process.env.PIXEL_ANNOTATION_DATA_ROOT = path.join(temporary, 'server-data');
process.env.PIXEL_ANNOTATION_PROFILES_ROOT = path.join(temporary, 'profiles');
process.env.PIXEL_ANNOTATION_TOKEN = 'test-token';
const { annotationApi } = await import('../../webui/server/annotation-api.mjs');
const { putSample, putImage, getSample, getImage, getMeta } = await import('../../webui/server/annotation-db.mjs');
const { PNG } = await import('../../webui/node_modules/pngjs/lib/png.js');
const server = createServer(async (req,res) => { if (!await annotationApi(req,res)) {res.writeHead(404);res.end();} });
await new Promise(resolve => server.listen(0,'127.0.0.1',resolve));
const url = `http://127.0.0.1:${server.address().port}`;
const env = { ...process.env, PIXEL_ANNOTATION_SERVER:url, PYTHON:process.env.PYTHON || path.join(root,'.venv/bin/python') };
async function cli(...args) {
  return run(process.execPath, [path.join(root,'scripts/pixel_annotate.mjs'), ...args,
    '--data-dir', path.join(temporary,'node-no-data')], { env, maxBuffer:2_000_000 });
}
async function request(resource, value, token='test-token') {
  const response = await fetch(`${url}/api/annotation/client/${resource}`, {
    headers:{ Authorization:`Bearer ${token}`, 'Content-Type':'application/json' },
    method:value ? 'PUT':'GET', body:value ? JSON.stringify(value):undefined });
  return { status:response.status, value:await response.json() };
}
try {
  await mkdir(path.join(temporary,'server-data/sources'),{recursive:true});
  for (const size of [24,52,78,104]) {
    const id = `999999_${size}`;
    const png = new PNG({width:size,height:size});
    png.data.fill(255);
    putSample({id,width:size,height:size,model_version:'fixture',status:'unmodified',indices:Array(size*size).fill(184)});
    putImage(id,'predictions',PNG.sync.write(png));
    await writeFile(path.join(temporary,`server-data/sources/${id}.png`),PNG.sync.write(png));
  }
  await test('CLI client retains queue, editing, save, export and recipes over HTTP', async () => {
    assert.equal((await request('palette',undefined,'wrong')).status,401);
    assert.match((await cli('list','--size','24')).stdout,/999999_24/);
    assert.equal((await cli('next','--size','24')).stdout.trim(),'999999_24');
    await cli('show','999999_24','--preview-file',path.join(temporary,'show.png'));
    await cli('edit','999999_24','--set','1,1:189');
    assert.equal(getSample('999999_24').corrected_indices[25],189);
    await cli('diff','999999_24');
    await cli('save','999999_24');
    assert.equal(getSample('999999_24').status,'pending');
    assert.equal(getMeta('999999_24').changed_pixels,1);
    const mask = PNG.sync.read(Buffer.from(getImage('999999_24','edit_masks')));
    assert.equal(mask.data[25*4],255);
    const output = path.join(temporary,'export.png');
    await cli('export','999999_24','--output',output);
    assert.deepEqual(await readFile(output),Buffer.from(getImage('999999_24','corrected')));
    await cli('status','999999_24','human_edited');
    assert.equal(getSample('999999_24').status,'human_edited');
    await cli('reset','999999_24');
    await cli('batch-clean','--size','52','--limit','1');
    await cli('profile-set','999999','--colors','#FFFFFF:-1,#000000:189');
    await cli('profile-tune','999999','--coverage','0.5');
    // Existing profiles can still be explicitly replaced by profile-set.
    await cli('profile-set','999999','--colors','#FFFFFF:-1,#000000:189');
    assert.match((await cli('recipe-list')).stdout,/999999/);
    await cli('recipe-preview','999999','--sizes','52');
    await cli('recipe-apply','999999','--sizes','52');
    assert.equal(getSample('999999_52').status,'pending');
    assert.equal(getSample('999999_52').annotation_source,'ai');
    await cli('recipe-preview','999999','--sizes','24,52,78,104');
    await cli('recipe-apply','999999','--sizes','24,52,78,104','--force');
    for (const size of [24,52,78,104]) assert.equal(getSample(`999999_${size}`).status,'pending');
    await cli('profile-tune','999999','--coverage','0.6');
    await assert.rejects(cli('recipe-apply','999999','--sizes','24,52,78,104','--force'), /Preview is stale/);
    await assert.rejects(readFile(path.join(temporary,'node-no-data/annotation.sqlite3')));
  });
  await test('stale nodes cannot overwrite a sample or shared profile', async () => {
    const old = (await request('resources/indices/999999_78')).value;
    const record = JSON.parse(Buffer.from(old.content,'base64'));
    record.corrected_indices = record.indices; record.status = 'human_edited';
    const update = { expected_revision:old.revision, writes:[{kind:'indices',content:Buffer.from(JSON.stringify(record)).toString('base64')}] };
    assert.equal((await request('samples/999999_78',update)).status,200);
    assert.equal((await request('samples/999999_78',update)).status,409);
    const profile = (await request('resources/profiles/999999')).value;
    const content = Buffer.from('{"rgb":[],"indices":[]}').toString('base64');
    assert.equal((await request('resources/profiles/999999',{content,expected_revision:profile.revision})).status,200);
    assert.equal((await request('resources/profiles/999999',{content,expected_revision:profile.revision})).status,409);
    const fresh = (await request('resources/indices/999999_78')).value;
    const before = Buffer.from(getImage('999999_78','predictions'));
    const bad = {...record,width:99};
    const invalid = await request('samples/999999_78',{expected_revision:fresh.revision,writes:[
      {kind:'indices',content:Buffer.from(JSON.stringify(bad)).toString('base64')}]});
    assert.equal(invalid.status,400);
    assert.deepEqual(Buffer.from(getImage('999999_78','predictions')),before);
  });
} finally {
  server.closeAllConnections();
  await new Promise(resolve => server.close(resolve));
  await rm(temporary,{recursive:true,force:true});
}
