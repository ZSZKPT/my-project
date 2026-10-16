const {chromium}=require(process.env.PLAYWRIGHT_MODULE||'playwright');
const assert=require('node:assert/strict');
(async()=>{
 const browser=await chromium.launch({headless:true,executablePath:process.env.CHROMIUM_PATH||undefined,args:['--no-sandbox']});
 const page=await browser.newPage();const errors=[];let browserDownloads=0,exportRequests=0;
 page.on('pageerror',e=>errors.push(e.message));page.on('download',()=>browserDownloads++);page.on('request',r=>{if(r.url().includes('/api/export/'))exportRequests++});
 await page.addInitScript(()=>{window.__nativeCalls=[];window.__nativeMode='save';window.pywebview={api:{
  save_data:async(encoded,name)=>{window.__nativeCalls.push({method:'save_data',encoded,name});return {saved:true,filename:name}},
  export_file:async(path,body,name)=>{window.__nativeCalls.push({method:'export_file',path,body,name});return window.__nativeMode==='cancel'?{cancelled:true}:window.__nativeMode==='error'?{error:'native test error'}:{saved:true,filename:name}}
 }}});
 try{
  await page.goto(process.env.NESTING_URL||'http://127.0.0.1:8765');await page.locator('#emptyDemo').click();await page.locator('#solve').click();
  await page.waitForFunction(()=>document.querySelector('#statusBadge').textContent==='复核通过',{}, {timeout:30000});
  await page.locator('#saveProject').click();await page.waitForFunction(()=>window.__nativeCalls.some(c=>c.method==='save_data'));
  const project=await page.evaluate(()=>window.__nativeCalls.find(c=>c.method==='save_data'));
  assert.equal(JSON.parse(Buffer.from(project.encoded,'base64').toString('utf8')).pieces.length,4);
  await page.locator('#export').click();await page.locator('#exportJpg').click();
  await page.waitForFunction(()=>window.__nativeCalls.some(c=>c.path==='/api/export/jpg'));
  const call=await page.evaluate(()=>window.__nativeCalls.find(c=>c.path==='/api/export/jpg'));
  assert.equal(call.body.project.placements.length,4);assert.ok(call.name.endsWith('.jpg'));
  await page.evaluate(()=>window.__nativeMode='cancel');await page.locator('#exportJpg').click();await page.waitForFunction(()=>document.querySelector('#toast').textContent==='已取消保存');
  await page.evaluate(()=>window.__nativeMode='error');await page.locator('#exportJpg').click();await page.waitForFunction(()=>document.querySelector('#toast').textContent==='native test error');
  assert.equal(browserDownloads,0);assert.equal(exportRequests,0);assert.deepEqual(errors,[]);
  console.log('Native JS integration passed: native project save, direct export bridge, cancellation, error reporting; zero browser downloads or export HTTP transfers.');
 }finally{await browser.close()}
})().catch(error=>{console.error(error);process.exitCode=1});
