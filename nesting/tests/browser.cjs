const {chromium}=require(process.env.PLAYWRIGHT_MODULE||'playwright');
const fs=require('node:fs');const path=require('node:path');const assert=require('node:assert/strict');
const base=process.env.NESTING_URL||'http://127.0.0.1:8765';const out=process.env.NESTING_TEST_OUTPUT||'/tmp/buxu-paired-browser';
async function main(){
 fs.mkdirSync(out,{recursive:true});const browser=await chromium.launch({headless:true,executablePath:process.env.CHROMIUM_PATH||undefined,args:['--no-sandbox']});
 const page=await browser.newPage({viewport:{width:1512,height:1040},acceptDownloads:true});const errors=[];page.on('pageerror',e=>errors.push(e.message));
 try{
  await page.goto(base);assert.equal(await page.locator('#gap').inputValue(),'3');
  const fixture=path.join(__dirname,'fixtures','paired.jpg');
  await page.locator('#files').setInputFiles(fixture);assert.equal(await page.locator('#importDpi').inputValue(),'110');assert.equal(await page.locator('#importMode').inputValue(),'garment-pair');
  await page.locator('#confirmImport').click();await page.waitForFunction(()=>document.querySelectorAll('.piece-row').length===2);
  assert.equal(await page.locator('#pieceDialog').isVisible(),false);assert.match(await page.locator('#readyCount').textContent(),/1 文件 · 2 片/);
  await page.locator('#files').setInputFiles(fixture);await page.locator('#confirmImport').click();await page.waitForFunction(()=>document.querySelectorAll('.piece-row').length===4);
  await page.locator('#iterations').fill('2');await page.locator('#seconds').fill('10');await page.locator('#solve').click();
  await page.waitForFunction(()=>document.querySelector('#statusBadge').textContent==='复核通过',{}, {timeout:25000});
  assert.equal(await page.locator('#layout [data-key]').count(),4);
  await page.locator('#layout [data-key]').first().locator('path').first().click({force:true});
  await page.locator('#posY').fill('500');await page.locator('#posY').dispatchEvent('change');
  await page.waitForResponse(r=>r.url().endsWith('/api/validate'));
  await page.locator('#undo').click();await page.waitForFunction(()=>document.querySelector('#verifyStatus').textContent==='通过 ✓');
  await page.screenshot({path:path.join(out,'desktop-paired.png'),fullPage:true});
  const downloadProject=page.waitForEvent('download');await page.locator('#saveProject').click();const projectDownload=await downloadProject;const saved=path.join(out,'project.json');await projectDownload.saveAs(saved);
  const project=JSON.parse(fs.readFileSync(saved,'utf8'));assert.ok(project.pieces.every(p=>p.confirmed&&p.verticalOnly&&p.dpi[0]===110));
  for(const gid of new Set(project.pieces.map(p=>p.sourceGroup))){const ids=project.pieces.filter(p=>p.sourceGroup===gid).map(p=>p.id);const pos=project.placements.filter(p=>ids.includes(p.pieceId));assert.equal(pos[0].x,pos[1].x);assert.equal(pos[0].y,pos[1].y);assert.ok(project.pieces.filter(p=>p.sourceGroup===gid).every(p=>p.fixedPair));assert.equal(pos[0].angle,pos[1].angle)}
  await page.locator('#export').click();const downloaded=page.waitForEvent('download');await page.locator('#exportJpg').click();const jpg=await downloaded;await jpg.saveAs(path.join(out,'production-110dpi.jpg'));assert.match(jpg.suggestedFilename(),/\.jpg$/);assert.ok(fs.statSync(path.join(out,'production-110dpi.jpg')).size>1000);
  await page.locator('#exportDialog .close-dialog').click();await page.locator('#projectFile').setInputFiles(saved);await page.waitForFunction(()=>document.querySelector('#toast').textContent.includes('项目已打开'));
  await page.setViewportSize({width:390,height:844});assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true);
  assert.deepEqual(errors,[]);console.log('Paired browser QA passed: 110DPI defaults, no per-piece confirmation, repeated file groups, vertical edit/undo, grouped X/angle, production JPG download, project restore, mobile.');
 }catch(error){await page.screenshot({path:path.join(out,'failure.png'),fullPage:true});throw error}finally{await browser.close()}
}
main().catch(error=>{console.error(error);process.exitCode=1});
