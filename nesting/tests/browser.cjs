/* Run against the local service. Uses installed Chromium if supplied. */
const {chromium}=require(process.env.PLAYWRIGHT_MODULE||'playwright');
const fs=require('node:fs');
const path=require('node:path');
const assert=require('node:assert/strict');
const base=process.env.NESTING_URL||'http://127.0.0.1:8765';
const out=process.env.NESTING_TEST_OUTPUT||'/tmp/buxu-browser';
async function main(){
 fs.mkdirSync(out,{recursive:true});
 const browser=await chromium.launch({headless:true,executablePath:process.env.CHROMIUM_PATH||undefined,args:['--no-sandbox']});
 const page=await browser.newPage({viewport:{width:1512,height:1040},acceptDownloads:true});
 const errors=[];page.on('pageerror',e=>errors.push(e.message));
 try{
  await page.goto(base);await page.getByRole('heading',{name:'让每一寸面料，更有价值。'}).waitFor();
  assert.equal(await page.locator('#gap').inputValue(),'3');
  await page.locator('#emptyDemo').click();await page.locator('.piece-row').first().waitFor();assert.equal(await page.locator('.piece-row').count(),4);
  await page.locator('#seconds').fill('10');await page.locator('#iterations').fill('5');
  await page.locator('#solve').click();await page.waitForFunction(()=>document.querySelector('#statusBadge').textContent==='复核通过',{},{timeout:25000});
  assert.match(await page.locator('#verifyStatus').textContent(),/通过/);
  const groups=page.locator('#layout [data-key]');assert.equal(await groups.count(),4);
  await groups.first().click({position:{x:30,y:20},force:true});
  await page.locator('#lock').click();assert.equal(await page.locator('#lock').textContent(),'解除锁定');
  await page.locator('#solve').click();await page.waitForFunction(()=>!document.querySelector('#stop').hidden,{},{timeout:3000});
  await page.locator('#stop').click();await page.waitForFunction(()=>document.querySelector('#stop').hidden,{},{timeout:20000});
  assert.equal(await page.locator('#lock').textContent(),'解除锁定');
  await page.locator('#lock').click();
  // Drag outside the width: conflicts must appear before pointerup.
  const box=await groups.first().boundingBox();await page.mouse.move(box.x+20,box.y+20);await page.mouse.down();await page.mouse.move(box.x-80,box.y+20,{steps:6});
  await page.waitForFunction(()=>document.querySelector('#verifyStatus').textContent==='存在问题');await page.mouse.up();
  await page.locator('#undo').click();await page.waitForFunction(()=>document.querySelector('#verifyStatus').textContent==='通过 ✓');
  // Deliberately invalidate a manual position, then undo it.
  await page.locator('#posX').fill('-1000');await page.locator('#posX').dispatchEvent('change');
  await page.waitForFunction(()=>document.querySelector('#verifyStatus').textContent==='存在问题');
  await page.locator('#undo').click();await page.waitForFunction(()=>document.querySelector('#verifyStatus').textContent==='通过 ✓');
  await page.screenshot({path:path.join(out,'desktop.png'),fullPage:true});
  const projectDownload=page.waitForEvent('download');await page.locator('#saveProject').click();const dl=await projectDownload;const projectFile=path.join(out,'roundtrip.nest.json');await dl.saveAs(projectFile);
  await page.locator('#export').click();
  const svgDownload=page.waitForEvent('download');await page.locator('#exportSvg').click();const svg=await svgDownload;await svg.saveAs(path.join(out,'production.svg'));
  const svgText=fs.readFileSync(path.join(out,'production.svg'),'utf8');assert.match(svgText,/1580\.000000000mm/);assert.match(svgText,/rotate\(180\)/);
  const zipDownload=page.waitForEvent('download');await page.locator('#exportZip').click();const zip=await zipDownload;await zip.saveAs(path.join(out,'production.zip'));assert.ok(fs.statSync(path.join(out,'production.zip')).size>1000);
  const pngDownload=page.waitForEvent('download');await page.locator('#exportPng').click();const png=await pngDownload;await png.saveAs(path.join(out,'preview.png'));
  await page.locator('#exportDialog .close-dialog').click();
  await page.locator('#projectFile').setInputFiles(projectFile);await page.waitForFunction(()=>document.querySelector('#toast').textContent.includes('项目已打开'));
  // JPEG, no quantity setup; two same-named files remain two instances.
  const fixture=path.join(__dirname,'fixtures','sample.jpg');
  await page.locator('#files').setInputFiles([fixture]);await page.locator('#importDpi').fill('100');await page.locator('#confirmImport').click();await page.locator('#pieceDialog').waitFor();
  await page.locator('#pieceConfirmed').check();await page.locator('#savePiece').click();assert.equal(await page.locator('.piece-row').count(),5);
  await page.locator('#files').setInputFiles([fixture]);await page.locator('#confirmImport').click();await page.locator('#pieceDialog').waitFor();await page.locator('#pieceConfirmed').check();await page.locator('#savePiece').click();assert.equal(await page.locator('.piece-row').count(),6);
  await page.locator('#files').setInputFiles([fixture]);await page.locator('#importDpi').fill('');await page.locator('#confirmImport').click();await page.locator('#pieceDialog').waitFor();
  assert.equal(await page.locator('#pieceWidth').inputValue(),'');await page.locator('#pieceConfirmed').check();await page.locator('#savePiece').click();assert.equal(await page.locator('#pieceDialog').isVisible(),true);
  await page.locator('#pieceWidth').fill('127');await page.locator('#pieceHeight').fill('152.4');await page.locator('#pieceConfirmed').check();await page.locator('#savePiece').click();assert.equal(await page.locator('.piece-row').count(),7);
  const fragmented=path.join(__dirname,'fixtures','fragmented.jpg');
  await page.locator('#files').setInputFiles([fragmented]);await page.locator('#importDpi').fill('100');
  page.once('dialog',dialog=>dialog.accept('2'));await page.locator('#confirmImport').click();await page.locator('#pieceDialog').waitFor();
  assert.match(await page.locator('#contourSource').textContent(),/保守凸包/);await page.locator('#pieceConfirmed').check();await page.locator('#savePiece').click();assert.equal(await page.locator('.piece-row').count(),8);
  await page.setViewportSize({width:390,height:844});await page.screenshot({path:path.join(out,'mobile.png'),fullPage:true});
  assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true);
  assert.deepEqual(errors,[]);console.log('Browser QA passed: layout, locks, stop, conflicts, undo, SVG/ZIP/PNG, project roundtrip, JPEG repeated files, missing-DPI block, fragmented-JPEG hull recovery, mobile; no page errors.');
 }finally{await browser.close()}
}
main().catch(e=>{console.error(e);process.exitCode=1});
