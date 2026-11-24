const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
const root=path.resolve(__dirname,'..');
function fixture(origin,fragment=''){
  const storage=new Map(), sockets=[];
  class Socket {
    constructor(url){this.url=url;this.readyState=1;this.sent=[];sockets.push(this);}
    send(s){this.sent.push(JSON.parse(s));}
    close(){this.readyState=3;}
    message(data){this.onmessage({data:JSON.stringify(data)});}
  }
  const ctx={window:{location:{origin,hash:fragment}},URLSearchParams,
    sessionStorage:{getItem:k=>storage.get(k),setItem:(k,v)=>storage.set(k,v)},
    history:{replaceState(){}},WebSocket:Socket,setTimeout,clearTimeout,setInterval,clearInterval};
  vm.createContext(ctx);vm.runInContext(fs.readFileSync(root+'/static/mpv-lab.js','utf8'),ctx);
  return {lab:vm.runInContext('mpvLab',ctx),sockets};
}
(async()=>{
  const token='a'.repeat(64), item={id:'item',asset_type:'video',asset_video_muted:true,
    asset_video_loop:false,asset_display_mode:'fit',asset_mime_type:'video/mp4',asset_size_bytes:42};
  assert.equal(fixture('http://example.com','#mpv-lab='+token).lab.enabled(),false);
  assert.equal(fixture('http://127.0.0.1:8000').lab.enabled(),false);
  const {lab,sockets}=fixture('http://127.0.0.1:8000','#mpv-lab='+token);
  assert.equal(lab.enabled(),true);assert.equal(lab.supports(item),true);
  assert.equal(lab.supports({...item,asset_video_loop:true}),false);
  assert.equal(lab.supports({...item,asset_video_muted:false}),false);
  assert.equal(lab.supports({...item,asset_display_mode:'fill'}),false);
  let state;const playing=lab.play(item,s=>state=s);
  const ws=sockets[0];ws.onopen();assert.equal(ws.sent[0].item_id,'item');
  ws.message({state:'playing'});assert.equal(state,'playing');
  ws.message({state:'completed',clean:true});assert.equal((await playing).clean,true);
  const pending=lab.play(item,()=>{});sockets[1].onopen();lab.stop();
  assert.equal((await pending).clean,false);assert.equal(sockets[1].sent[1].action,'stop');
  const checking=lab.clean();sockets[2].onopen();sockets[2].message({state:'clean',clean:true});
  assert.equal(await checking,true);
  console.log('PASS: local-only opt-in, profile eligibility, terminal state, cancellation and cleanup');
})().catch(e=>{console.error(e);process.exitCode=1});
