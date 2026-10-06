// Run with jsdom available on NODE_PATH: node tests/test_admin_observers.cjs
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { execFileSync } = require('node:child_process');
const { JSDOM } = require('jsdom');
const wait = ms => new Promise(resolve => setTimeout(resolve, ms));
const root = path.resolve(__dirname, '..');
const dom = new JSDOM(`<!doctype html><body>
<form id="upload-form"><h2>Upload</h2><label for="asset-file">File</label><input id="asset-file" type="file"><div class="asset-actions"></div></form>
<div id="asset-list"><table><tbody><tr><td><span>Web</span></td><td>Clip</td><td>video</td><td>Details</td><td><button data-edit-asset="clip">Edit</button></td></tr></tbody></table></div>
<div id="playlist-list"><section class="panel"><form data-add-item="playlist"><select name="asset_id"><option value="image">Image (image)</option><option value="clip">Clip (video)</option></select><input name="duration_seconds" value="15"></form>
<table class="table"><thead><tr><th>Pos</th><th>Asset</th><th>Duration</th></tr></thead><tbody><tr><td>0</td><td>Clip</td><td><input data-item-duration="playlist:item" value="15"></td></tr></tbody></table></section></div>
</body>`, { runScripts:'outside-only', pretendToBeVisual:true });
const w = dom.window;
w.eval(`window.state={assets:[{id:'clip',name:'Clip',type:'video',display_mode:'fit',video_muted:true,video_loop:false},{id:'image',name:'Image',type:'image'}]};function escapeHtml(v){return String(v);}`);
let mutations=0;
const observer=new w.MutationObserver(records=>{mutations+=records.length;});
observer.observe(w.document.body,{childList:true,subtree:true});
for(const file of ['video-ui.js','playlist-timer.js']) {
  const code=process.env.PI_UI_BASE_REF
    ? execFileSync('git',['show',`${process.env.PI_UI_BASE_REF}:static/${file}`],{cwd:root,encoding:'utf8'})
    : fs.readFileSync(path.join(root,'static',file),'utf8');
  w.eval(code);
}
async function settles(label) {
  await wait(250);
  const before=mutations;
  await wait(150);
  assert.equal(mutations,before,`${label}: DOM kept changing without user input`);
}
(async()=>{
  await settles('Initial render');
  const doc=w.document,select=doc.querySelector('select[name="asset_id"]');
  select.value='clip';select.dispatchEvent(new w.Event('change'));
  await settles('Select video');
  assert.equal(doc.querySelector('input[name="duration_seconds"]').disabled,true);
  assert.equal(doc.querySelector('[data-video-auto-duration]').value,'15');
  select.value='image';select.dispatchEvent(new w.Event('change'));
  await settles('Select image');
  assert.equal(doc.querySelector('input[name="duration_seconds"]').disabled,false);
  assert.equal(doc.querySelector('[data-video-auto-duration]'),null);
  // A fresh API render must enhance once and then settle again.
  doc.querySelector('#asset-list tbody').innerHTML='<tr data-editing-asset="clip"><td>Web</td><td>Clip</td><td>video</td><td>Details</td><td><button data-save-asset="clip">Save</button></td></tr>';
  await settles('Edit video');
  assert.equal(doc.querySelectorAll('[data-video-settings]').length,1);
  console.log('PASS: observers settle after render, video/image selection and editing');
})().catch(error=>{console.error(error.message);process.exitCode=1;}).finally(()=>{observer.disconnect();w.close();});
