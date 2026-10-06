const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
const root=path.resolve(__dirname,'..');
class Element {
  constructor(tag){this.tag=tag;this.listeners={};this.style={};this.readyState=0;this.currentTime=0;this.duration=10;this.ended=false;}
  addEventListener(event,fn){(this.listeners[event]||=[]).push(fn);}
  emit(event){for(const fn of this.listeners[event]||[])fn();}
  pause(){}load(){}remove(){}removeAttribute(){}play(){return Promise.resolve();}
}
let timeouts=new Map(),serial=0,lastVideo,domWrites=0,nextResponse;
const stage={innerHTML:'existing',replaceChildren(){domWrites++;},appendChild(e){domWrites++;if(e.tag==='video')lastVideo=e;}};
const context={console,AbortSignal,document:{querySelector:()=>stage,createElement:tag=>new Element(tag)},window:{location:{hostname:'admin.example'},addEventListener(){},open(){return null;}},setInterval(){return ++serial;},clearInterval(){},setTimeout(fn,ms){const id=++serial;timeouts.set(id,{fn,ms});return id;},clearTimeout(id){timeouts.delete(id);},fetch:async url=>{
  if(url==='/api/player/info')return new Promise(()=>{});
  if(nextResponse instanceof Error)throw nextResponse;
  return {ok:true,json:async()=>nextResponse};
},startPdfPlayback(){return()=>{};}};
vm.createContext(context);vm.runInContext(fs.readFileSync(root+'/static/player.js','utf8'),context);
const run=code=>vm.runInContext(code,context);
(async()=>{
  run('bootSplashUntil=0');
  nextResponse={state:'playing',playlist:{id:'p'},items:[{id:'i',asset_id:'a',asset_type:'video',enabled:true,duration_seconds:5,media_url:'/media/a',asset_video_muted:true}]};
  await run('loadPlaylist()');
  assert.ok(lastVideo);const before=domWrites;
  nextResponse=new Error('API unavailable');await run('loadPlaylist()');
  assert.equal(domWrites,before,'Failed refresh must preserve current media');
  assert.equal(run('items.length'),1);
  const deadline=[...timeouts.values()].find(t=>t.ms===30000);
  assert.ok(deadline,'Video startup timeout must exist');deadline.fn();
  assert.ok([...timeouts.values()].some(t=>t.ms===2000),'Startup failure must schedule next item');
  run('playCurrent()');const previous=lastVideo;
  const lateError=()=>previous.emit('error');
  run("items=[{asset_type:'pdf',asset_id:'pdf',duration_seconds:10}];index=0;playCurrent()");
  const beforeLate=domWrites;lateError();assert.equal(domWrites,beforeLate,'Late video error must not replace newer PDF');
  run('items=[];advance()');assert.equal(run('index'),0,'Empty playlist must not produce NaN');
  console.log('PASS: playlist outage continuity, video startup timeout, late callback protection');
})().catch(e=>{console.error(e);process.exitCode=1;});
