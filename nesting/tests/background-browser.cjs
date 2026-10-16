const {chromium}=require(process.env.PLAYWRIGHT_MODULE||'playwright');
const assert=require('node:assert/strict');
(async()=>{
 const browser=await chromium.launch({headless:true,executablePath:process.env.CHROMIUM_PATH,args:['--no-sandbox']});
 const page=await browser.newPage();
 await page.addInitScript(()=>{window.calls=[];window.finished=false;window.cancelled=false;window.pywebview={api:{
  choose_export:async(name)=>{calls.push('choose');return {job:'test'}},
  start_export:async(key,path,body)=>{calls.push('start');return {started:true}},
  export_status:async()=>({state:window.cancelled?'cancelled':window.finished?'done':'running',percent:50,message:'后台生成中'}),
  cancel_export:async()=>{window.cancelled=true;return {cancelled:true}}
 }}});
 try{
  await page.goto(process.env.NESTING_URL);await page.locator('#emptyDemo').click();await page.locator('#solve').click();
  await page.waitForFunction(()=>document.querySelector('#statusBadge').textContent==='复核通过');
  await page.evaluate(()=>{project.placements[0].y=3000;result.stats.length=4000;renderCanvas()});
  assert.equal(await page.locator('#layout [data-key]').count(),4);
  assert.ok(Number((await page.locator('#layout').getAttribute('viewBox')).split(' ')[3])>4000);
  await page.locator('#export').click();await page.locator('#exportJpg').click();await page.waitForFunction(()=>calls.includes('start'));
  assert.deepEqual(await page.evaluate(()=>calls),['choose','start']);
  assert.equal(await page.locator('#cancelExport').isVisible(),true);
  await page.locator('#cancelExport').click();await page.waitForFunction(()=>!document.querySelector('#exportJpg').disabled);
  await page.evaluate(()=>{window.cancelled=false;window.finished=false});await page.locator('#exportJpg').click();
  await page.locator('#exportDialog .close-dialog').click();assert.equal(await page.locator('#exportDialog').isVisible(),false);
  await page.locator('#zoomIn').click();await page.evaluate(()=>window.finished=true);
  await page.waitForFunction(()=>!document.querySelector('#exportJpg').disabled);
  console.log('Full layout, choose-first background export, cancellation and responsive closed-dialog UI passed');
 }finally{await browser.close()}
})().catch(e=>{console.error(e);process.exitCode=1});
