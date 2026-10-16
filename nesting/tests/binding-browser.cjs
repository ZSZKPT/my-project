const {chromium}=require(process.env.PLAYWRIGHT_MODULE||'playwright');
const assert=require('node:assert/strict');const path=require('node:path');const fs=require('node:fs');
(async()=>{
 const browser=await chromium.launch({headless:true,executablePath:process.env.CHROMIUM_PATH,args:['--no-sandbox']});
 const page=await browser.newPage({acceptDownloads:true});const errors=[];page.on('pageerror',e=>errors.push(e.message));
 await page.addInitScript(()=>{window.calls=[];window.bindingMode='ok';window.pywebview={api:{
  choose_binding_folder:async(recursive)=>{calls.push({method:'choose',recursive});return {folder:'D:/包边条',files:[{id:'strip',name:'paired-包边条.jpg'}]}},
  match_binding_files:async(requests,rule)=>{
   calls.push({method:'match',requests,rule});const result={matches:[],missing:[],ambiguous:[],requested:requests.length,rule};
   for(const r of requests){if(window.bindingMode==='missing'){result.missing.push(r)}else if(window.bindingMode==='ambiguous'){result.ambiguous.push({...r,candidates:[{relativePath:'one/paired-包边条.jpg'},{relativePath:'two/paired-包边条.jpg'}]})}else result.matches.push({...r,file:{id:'strip',relativePath:'paired/paired-包边条.jpg'}})}return result;
  },
  copy_binding_files:async(requests,rule,quantities)=>{calls.push({method:'copy',requests,rule,quantities});return {saved:true,count:Object.values(quantities).reduce((a,b)=>a+b,0),folder:'D:/输出/布序包边条-测试'}}
 }}});
 async function projectFile(name){const event=page.waitForEvent('download');await page.locator('#saveProject').click();await (await event).saveAs(name);return JSON.parse(fs.readFileSync(name))}
 try{
  await page.goto(process.env.NESTING_URL);const fixture=path.join(__dirname,'fixtures','paired.jpg');
  for(let i=1;i<=2;i++){await page.locator('#files').setInputFiles(fixture);await page.locator('#confirmImport').click();await page.waitForFunction(n=>document.querySelectorAll('.piece-row').length===n,i*2)}
  assert.equal(await page.locator('#layout [data-key]').count(),0);
  assert.match(await page.locator('#bindingStatsTotal').textContent(),/包边条2张/);
  const quantity=page.locator('#bindingStatsRows input');assert.equal(await quantity.count(),1);
  await quantity.fill('5');await quantity.dispatchEvent('change');
  assert.match(await page.locator('#bindingStatsTotal').textContent(),/包边条5张/);
  const before=await projectFile('/tmp/buxu-before-binding.json');
  await page.locator('#binding').click();assert.equal(await page.locator('#bindingRule').inputValue(),'style-folder');
  await page.locator('#bindingChoose').click();await page.waitForFunction(()=>!document.querySelector('#bindingCopy').disabled);
  assert.match(await page.locator('#bindingSummary').textContent(),/2个.*计划复制5张.*匹配2个/);
  assert.equal(await page.locator('#bindingAdd').count(),0);
  await page.locator('#bindingCopy').click();await page.waitForFunction(()=>document.querySelector('#bindingSummary').textContent.includes('已复制5张'));
  const copied=await page.evaluate(()=>calls.find(c=>c.method==='copy'));assert.equal(copied.requests.length,2);assert.deepEqual(copied.quantities,{PAIRED:5});
  assert.notEqual(copied.requests[0].id,copied.requests[1].id);assert.equal(copied.requests[0].filename,'paired.jpg');
  assert.deepEqual(Object.keys(copied.requests[0]).sort(),['filename','id']);
  await page.locator('#bindingDialog .close-dialog').click();const after=await projectFile('/tmp/buxu-after-binding.json');assert.deepEqual(after,before);assert.equal(after.placements.length,0);assert.equal(after.pieces.length,4);
  await page.locator('#projectFile').setInputFiles('/tmp/buxu-after-binding.json');await page.waitForFunction(()=>document.querySelector('#toast').textContent.includes('项目已打开'));assert.equal(await page.locator('#bindingStatsRows input').inputValue(),'5');
  await page.locator('#binding').click();await page.evaluate(()=>window.bindingMode='missing');await page.locator('#bindingRule').selectOption('exact');await page.waitForFunction(()=>document.querySelector('#bindingSummary').textContent.includes('未找到2个'));assert.equal(await page.locator('#bindingCopy').isDisabled(),true);
  await page.evaluate(()=>window.bindingMode='ambiguous');await page.locator('#bindingRule').selectOption('style-folder');await page.waitForFunction(()=>document.querySelector('#bindingSummary').textContent.includes('重名待处理2个'));assert.equal(await page.locator('#bindingCopy').isDisabled(),true);
  await page.locator('#bindingDialog .close-dialog').click();await page.locator('#bindingStatsRows input').fill('0');await page.locator('#bindingStatsRows input').dispatchEvent('change');await page.evaluate(()=>window.bindingMode='ok');await page.locator('#binding').click();assert.equal(await page.locator('#bindingCopy').isDisabled(),true);
  assert.deepEqual(errors,[]);console.log('Binding UI passed: two split source groups yield exactly two requests; pre-nesting copy with style quantity 5; persisted quantities; unchanged materials and empty layout; missing/ambiguous blocked.');
 }finally{await browser.close()}
})().catch(e=>{console.error(e);process.exitCode=1});
