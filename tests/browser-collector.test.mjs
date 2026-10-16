import test from 'node:test';
import assert from 'node:assert/strict';
const state={},alarms=[],downloads=[];let onMessage;const downloadListeners=[];const onDownloadChanged=event=>downloadListeners.forEach(f=>f(event));
let captureSequence=null,stopOnAdvance=false;
let capture={status:'ok',message:'已采集',products:[{platform:'Pinterest',site:'当前浏览器地区',productId:'1',title:'wallpaper',url:'https://www.pinterest.com/pin/1/',image:'https://i.pinimg.com/1.jpg',sales:null,likes:null,saves:100}]};
globalThis.chrome={
 runtime:{async sendMessage(message){return message.type==='buildZip'?{ok:true,url:'blob:chrome-extension://test-extension/archive',count:1,failed:0}:{ok:true}},id:'test-extension',onMessage:{addListener:f=>onMessage=f},onStartup:{addListener(){}},onInstalled:{addListener(){}}},
 storage:{local:{async get(keys){if(typeof keys==='string')return {[keys]:structuredClone(state[keys])};return Object.fromEntries(keys.map(k=>[k,structuredClone(state[k])]))},async set(data){Object.assign(state,structuredClone(data))}}},
 alarms:{onAlarm:{addListener(){}},async clear(){alarms.length=0},async create(name,options){alarms.push({name,...options})}},
 tabs:{async query(query){return query.active?[{id:1,url:'https://www.pinterest.com/'}]:[]}},
 permissions:{async contains(){return true}},offscreen:{async hasDocument(){return false},async createDocument(options){assert.deepEqual(options.reasons,['BLOBS'])}},
 downloads:{async search(){return []},onChanged:{addListener:f=>downloadListeners.push(f)},async download(options){downloads.push(options);return downloads.length}},
 scripting:{async executeScript(options){if(options.func.name==='readVisible')return [{result:structuredClone(captureSequence?.shift()||capture)}];if(stopOnAdvance){stopOnAdvance=false;onMessage({type:'stopCapture'},{id:'test-extension'},()=>{})}return [{result:'scroll'}]}}
};
await import('../browser-collector/background.js');
const send=(type,extra={})=>new Promise(resolve=>onMessage({...extra,type,targetIds:['pinterest-home']},{id:'test-extension'},resolve));
test('browser collection checkpoints baseline and later new recommendations without discarding old pins',async()=>{
 assert.equal((await send('capture')).ok,true);assert.equal(state.products.length,1);assert.equal(state.products[0].baseline,true);
 capture.products=[{...capture.products[0],productId:'2',url:'https://www.pinterest.com/pin/2/'}];await send('capture');assert.equal(state.products.length,2);assert.equal(state.products[1].baseline,false);
 capture={status:'verification_required',message:'需要验证',products:[]};await send('capture');assert.equal(state.products.length,2);assert.equal(state.reports[0].status,'verification_required');
});
test('daily scheduling is local, at 09:00 China time, and can be disabled',async()=>{
 await send('enable');assert.equal(state.enabled,true);assert.equal(alarms.length,1);assert.equal(alarms[0].periodInMinutes,1440);assert.ok(alarms[0].when>Date.now());assert.equal(new Intl.DateTimeFormat('en-GB',{timeZone:'Asia/Shanghai',hour:'2-digit',minute:'2-digit'}).format(new Date(alarms[0].when)),'09:00');await send('disable');assert.equal(state.enabled,false);assert.equal(alarms.length,0);
});

test('strict like threshold excludes equality, unknown likes and high save counts; completed downloads are reused',async()=>{
 state.products=[{platform:'Pinterest',productId:'high',likes:101,saves:null,image:'https://i.pinimg.com/high.jpg'},{platform:'Pinterest',productId:'equal',likes:100,image:'https://i.pinimg.com/equal.jpg'},{platform:'Pinterest',productId:'unknown',likes:null,saves:9999,image:'https://i.pinimg.com/unknown.jpg'}];
 const preview=await send('likePreview',{minLikes:100});assert.match(preview.message,/1 张可下载/);
 await send('downloadLikes',{minLikes:100});assert.equal(downloads.length,1);assert.match(downloads[0].filename,/点赞大于100/);assert.equal(downloads[0].url,'https://i.pinimg.com/high.jpg');
 onDownloadChanged({id:1,state:{current:'complete'}});await new Promise(r=>setTimeout(r,5));
 assert.equal(state.downloadRecords['https://i.pinimg.com/high.jpg'].status,'complete');await send('downloadLikes',{minLikes:100});assert.equal(downloads.length,1);
 assert.equal((await send('downloadLikes',{minLikes:-1})).ok,false);
});
test('AND requires both counts; OR accepts either known passing count and treats unknown separately',async()=>{
 state.products=[
 {likes:120,saves:5,image:'https://i.pinimg.com/a.jpg'},
 {likes:null,saves:600,image:'https://i.pinimg.com/b.jpg'},
 {likes:150,saves:700,image:'https://i.pinimg.com/c.jpg'},
 {likes:100,saves:500,image:'https://i.pinimg.com/equal.jpg'},
 {likes:null,saves:null,image:'https://i.pinimg.com/unknown.jpg'}];
 const and=await send('likePreview',{criteria:{likes:100,saves:500,operator:'and'}});assert.match(and.message,/1 张可下载/);
 const or=await send('likePreview',{criteria:{likes:100,saves:500,operator:'or'}});assert.match(or.message,/3 张可下载/);
 const saves=await send('likePreview',{criteria:{likes:null,saves:500,operator:'and'}});assert.match(saves.message,/2 张可下载/);
 assert.equal((await send('likePreview',{criteria:{likes:null,saves:null,operator:'and'}})).ok,false);
});

test('automatic loading checkpoints each round, deduplicates and respects the image cap',async()=>{
 state.products=[];const product=id=>({platform:'Pinterest',site:'当前浏览器地区',productId:id,title:'pin '+id,url:'https://www.pinterest.com/pin/'+id+'/',image:'https://i.pinimg.com/'+id+'.jpg',likes:150,saves:200});
 captureSequence=[{status:'ok',products:[product('1')]},{status:'ok',products:[product('1'),product('2')]}];
 const result=await send('captureAuto',{rounds:5,maxImages:2});assert.equal(result.ok,true);assert.equal(state.products.length,2);assert.ok(state.products.every(p=>p.baseline===true));assert.equal(state.captureProgress.running,false);
});
test('stop request retains the completed round and ends automatic scrolling',async()=>{
 state.products=[];captureSequence=[{status:'ok',products:[{platform:'Pinterest',site:'当前浏览器地区',productId:'3',image:'https://i.pinimg.com/3.jpg'}]}];stopOnAdvance=true;
 const result=await send('captureAuto',{rounds:5,maxImages:50});assert.match(result.message,/已停止/);assert.equal(state.products.length,1);assert.equal(state.running,false);captureSequence=null;
});

test('ZIP action supports all captured images with unknown metrics and records actual download completion',async()=>{
 state.products=[{platform:'Pinterest',productId:'zip',image:'https://i.pinimg.com/zip.jpg',likes:null,saves:null}];
 const result=await send('downloadZip',{scope:'all'});assert.equal(result.ok,true);assert.match(downloads.at(-1).filename,/全部已采集.*\.zip$/);assert.equal(state.zipProgress.status,'downloading');const id=state.zipDownload.id;
 onDownloadChanged({id,state:{current:'complete'}});await new Promise(r=>setTimeout(r,10));assert.equal(state.zipProgress.status,'complete');
});
