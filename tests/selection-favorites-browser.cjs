/* Real selection UI and content-bridge script; Chrome runtime/download is mocked.
   This cloud browser disallows unpacked extensions by administrator policy. */
const {chromium}=require(process.env.PLAYWRIGHT_MODULE||'playwright');
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
(async()=>{
 const root=path.resolve(__dirname,'..');
 const browser=await chromium.launch({headless:true,executablePath:process.env.CHROMIUM_PATH||undefined,args:['--no-sandbox']});
 const context=await browser.newContext();
 try{
  await context.route('https://zszkpt.github.io/my-project/**',route=>{const url=new URL(route.request().url());const relative=url.pathname.replace('/my-project/','')||'index.html';const file=path.join(root,'selection',relative);if(!fs.existsSync(file))return route.fulfill({status:404,body:'not found'});return route.fulfill({path:file,contentType:relative.endsWith('.js')?'text/javascript':'text/html'})});
  await context.addInitScript(()=>{
   if(location.origin!=='https://zszkpt.github.io')return;
   window.__favoriteCalls=[];window.chrome=window.chrome||{};
   window.chrome.runtime={sendMessage:async message=>{window.__favoriteCalls.push(message);return {ok:true,message:`已启动 1 张下载；收藏${message.products.length}条`}}};
   const base={platform:'Pinterest',site:'US',firstSeen:'2020-01-01',url:'https://www.pinterest.com/pin/1/',notes:'keep my note'};
   localStorage.setItem('feifan-selection-v1',JSON.stringify({products:[
    {...base,productId:'fav-a',title:'personal favorite',favorite:true,image:'https://images.example.test/favorite.png'},
    {...base,productId:'fav-copy',title:'duplicate image favorite',favorite:true,image:'https://images.example.test/favorite.png'},
    {...base,productId:'public-high',title:'public saves only',favorite:false,saves:999999,image:'https://images.example.test/public.png'},
    {...base,productId:'demo',title:'demo favorite',favorite:true,demo:true,image:'https://images.example.test/demo.png'}
   ]}));
  });
  const page=await context.newPage();const errors=[];page.on('pageerror',e=>errors.push(e.message));
  await page.goto('https://zszkpt.github.io/my-project/');
  await page.locator('#downloadFavoritesBtn').click();assert.match(await page.locator('#toast').textContent(),/更新采集扩展/);
  await page.addScriptTag({path:path.join(root,'browser-collector/selection-bridge.js')});
  await page.waitForFunction(()=>document.querySelector('#favoriteDownloadStatus').textContent.includes('扩展已连接'));
  await page.locator('#downloadFavoritesBtn').click();await page.waitForFunction(()=>document.querySelector('#toast').textContent.includes('已启动 1 张下载'));
  let calls=await page.evaluate(()=>window.__favoriteCalls);assert.equal(calls.length,1);assert.equal(calls[0].type,'downloadFavorites');assert.equal(calls[0].products.length,2);assert.ok(calls[0].products.every(p=>p.favorite&&!p.demo));assert.ok(calls[0].products.every(p=>p.image==='https://images.example.test/favorite.png'));
  const saved=await page.evaluate(()=>JSON.parse(localStorage.getItem('feifan-selection-v1')));assert.equal(saved.products.find(p=>p.productId==='fav-a').notes,'keep my note');
  await page.getByLabel('选择 personal favorite',{exact:true}).check();await page.locator('#downloadFavoritesBtn').click();await page.waitForFunction(()=>document.querySelector('#toast').textContent.includes('收藏1条'));
  calls=await page.evaluate(()=>window.__favoriteCalls);assert.equal(calls.length,2);assert.equal(calls[1].products[0].productId,'fav-a');
  await page.getByLabel('选择 personal favorite',{exact:true}).uncheck();
  await page.locator('#results article').filter({hasText:'personal favorite'}).locator('[data-action="favorite"]').click();
  await page.locator('#downloadFavoritesBtn').click();await page.waitForFunction(()=>window.__favoriteCalls.length===3);
  calls=await page.evaluate(()=>window.__favoriteCalls);assert.equal(calls[2].products.length,1);assert.equal(calls[2].products[0].productId,'fav-copy');
  assert.deepEqual(errors,[]);console.log('Favorites UI passed: missing-extension guidance, real bridge request/result, personal stars only, checked subset, unfavorite applied immediately, notes preserved. chrome.runtime is mocked.');
 }finally{await context.close();await browser.close()}
})().catch(e=>{console.error(e);process.exitCode=1});
