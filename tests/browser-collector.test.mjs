import test from 'node:test';
import assert from 'node:assert/strict';
const state={},alarms=[];let onMessage;
let capture={status:'ok',message:'已采集',products:[{platform:'Pinterest',site:'当前浏览器地区',productId:'1',title:'wallpaper',url:'https://www.pinterest.com/pin/1/',image:'https://i.pinimg.com/1.jpg',sales:null,likes:null,saves:100}]};
globalThis.chrome={
 runtime:{id:'test-extension',onMessage:{addListener:f=>onMessage=f},onStartup:{addListener(){}},onInstalled:{addListener(){}}},
 storage:{local:{async get(keys){if(typeof keys==='string')return {[keys]:structuredClone(state[keys])};return Object.fromEntries(keys.map(k=>[k,structuredClone(state[k])]))},async set(data){Object.assign(state,structuredClone(data))}}},
 alarms:{onAlarm:{addListener(){}},async clear(){alarms.length=0},async create(name,options){alarms.push({name,...options})}},
 tabs:{async query(query){return query.active?[{id:1,url:'https://www.pinterest.com/'}]:[]}},
 scripting:{async executeScript(){return [{result:structuredClone(capture)}]}}
};
await import('../browser-collector/background.js');
const send=type=>new Promise(resolve=>onMessage({type,targetIds:['pinterest-home']},{id:'test-extension'},resolve));
test('browser collection checkpoints baseline and later new recommendations without discarding old pins',async()=>{
 assert.equal((await send('capture')).ok,true);assert.equal(state.products.length,1);assert.equal(state.products[0].baseline,true);
 capture.products=[{...capture.products[0],productId:'2',url:'https://www.pinterest.com/pin/2/'}];await send('capture');assert.equal(state.products.length,2);assert.equal(state.products[1].baseline,false);
 capture={status:'verification_required',message:'需要验证',products:[]};await send('capture');assert.equal(state.products.length,2);assert.equal(state.reports[0].status,'verification_required');
});
test('daily scheduling is local, at 09:00 China time, and can be disabled',async()=>{
 await send('enable');assert.equal(state.enabled,true);assert.equal(alarms.length,1);assert.equal(alarms[0].periodInMinutes,1440);assert.ok(alarms[0].when>Date.now());assert.equal(new Intl.DateTimeFormat('en-GB',{timeZone:'Asia/Shanghai',hour:'2-digit',minute:'2-digit'}).format(new Date(alarms[0].when)),'09:00');await send('disable');assert.equal(state.enabled,false);assert.equal(alarms.length,0);
});
