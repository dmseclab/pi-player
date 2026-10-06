const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
const source=fs.readFileSync(path.resolve(__dirname,'../static/pdf-player.js'),'utf8').replace('import("/static/vendor/pdfjs/legacy/build/pdf.mjs")','mockPdfLibrary()');
async function scenario(pages,once) {
  let timers=new Map(),id=0,renders=0,ready=0,complete=0,destroyed=0,pageReports=[];
  const canvas=()=>({style:{},getContext(){return {};}});
  const stage={clientWidth:800,clientHeight:600,replaceChildren(){}};
  const pdf={numPages:pages,getPage:async()=>({getViewport:({scale})=>({width:300*scale,height:200*scale}),render(){renders++;return {promise:Promise.resolve(),cancel(){}};},cleanup(){}})};
  const context={console,window:{devicePixelRatio:1},document:{createElement:canvas},setTimeout(fn,ms){const key=++id;timers.set(key,{fn,ms});return key;},clearTimeout(key){timers.delete(key);},mockPdfLibrary:async()=>({GlobalWorkerOptions:{},getDocument:()=>({promise:Promise.resolve(pdf),destroy:async()=>{destroyed++;}})})};
  vm.createContext(context);vm.runInContext(source,context);
  const stop=context.startPdfPlayback({media_url:'/pdf',asset_pdf_page_seconds:2,asset_pdf_play_once:once},stage,()=>ready++,e=>{throw e;},()=>complete++,page=>pageReports.push(page));
  const flush=async()=>{for(let i=0;i<12;i++)await Promise.resolve();};await flush();
  assert.equal(ready,1);assert.equal(renders,1);
  for(let i=0;i<pages;i++){
    const pair=[...timers.entries()].find(([,t])=>t.ms===2000);
    if(!pair)break;timers.delete(pair[0]);pair[1].fn();await flush();
  }
  if(once){assert.equal(renders,pages);assert.equal(complete,1);assert.deepEqual(pageReports,Array.from({length:pages},(_,i)=>i+1));}
  else if(pages===1){assert.equal(renders,1);assert.equal(complete,0);}
  stop();await flush();assert.equal(destroyed,1);assert.equal(timers.size,0);
}
(async()=>{await scenario(1,false);await scenario(1,true);await scenario(3,true);await scenario(3,false);console.log('PASS: single-page render once, multi-page once/loop, timer cleanup');})().catch(e=>{console.error(e);process.exitCode=1});
