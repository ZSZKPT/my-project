import {readFile,writeFile,mkdir,rename} from 'node:fs/promises';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {chromium} from 'playwright';
import robotsParser from 'robots-parser';
import {allowedURL,publicProduct,productLink,mergeSnapshot,shortError,accessBarrier} from './core.mjs';
const here=path.dirname(fileURLToPath(import.meta.url)),root=path.resolve(here,'..'),output=path.join(root,'selection/data/latest.json');
const config=JSON.parse(await readFile(path.join(here,'targets.json'),'utf8'));
const now=new Date().toISOString(),date=new Intl.DateTimeFormat('en-CA',{timeZone:config.timezone,year:'numeric',month:'2-digit',day:'2-digit'}).format(new Date());
let previous={products:[],targets:[]};try{previous=JSON.parse(await readFile(output,'utf8'))}catch(error){if(error.code!=='ENOENT')throw error}
const browser=await chromium.launch({headless:true,...(process.env.CRAWLER_CHROMIUM?{executablePath:process.env.CRAWLER_CHROMIUM}:{})});
const observations=[],robotCache=new Map();
const pause=ms=>new Promise(r=>setTimeout(r,ms));
async function robots(context,target){const origin=new URL(target.url).origin;let record=robotCache.get(origin);if(!record){try{const r=await context.request.get(origin+'/robots.txt',{timeout:20000,failOnStatusCode:false,maxRedirects:3});if(r.status()===404)record={parser:robotsParser(origin+'/robots.txt','')};else if(r.ok())record={parser:robotsParser(origin+'/robots.txt',await r.text())};else record={error:true}}catch{record={error:true}}robotCache.set(origin,record)}if(record.error)return {status:'robots_unavailable',message:'无法确认 robots.txt 规则，本次未采集'};if(record.parser.isAllowed(target.url,'FeifanSelectionBot')===false||record.parser.isAllowed(target.url,'*')===false)return {status:'robots_disallowed',message:'robots.txt 不允许采集该目标，本次未采集'};return null}
async function collect(target){if(!allowedURL(target.url,target.platform))return {target,status:'invalid_target',message:'目标域名与平台不匹配'};const context=await browser.newContext({locale:'en-US',timezoneId:'America/New_York',viewport:{width:1440,height:1000},userAgent:'FeifanSelectionBot/1.0 (+https://github.com/ZSZKPT/my-project)'});try{const denied=await robots(context,target);if(denied)return {target,...denied};const page=await context.newPage();const response=await page.goto(target.url,{waitUntil:'domcontentloaded',timeout:35000});if(response&&response.status()>=400)return {target,status:'http_error',message:'目标返回 HTTP '+response.status()+'，未采集'};await pause(3500);if(!allowedURL(page.url(),target.platform))return {target,status:'redirected',message:'目标跳转至其他域名，已停止'};const text=await page.locator('body').innerText({timeout:12000});const blocked=accessBarrier(page.url(),text);if(blocked)return {target,status:blocked,message:blocked==='auth_required'?'目标需要登录，已停止':'目标出现验证或访问限制，已停止'};
 // Wait for ordinary page rendering; no login or challenge handling is attempted.
 const hrefPattern={Temu:'(?:-g-\\d+\\.html|goods_id=\\d+)',SHEIN:'-p-\\d+\\.html',LightInTheBox:'_p\\d+\\.html',Pinterest:'/pin/\\d+/'}[target.platform];
 await page.waitForFunction(pattern=>[...document.querySelectorAll('a[href]')].some(a=>new RegExp(pattern,'i').test(a.href)),hrefPattern,{timeout:15000}).catch(()=>{});
 const products=new Map();
 for(let scroll=0;scroll<=config.maxScrolls;scroll++){
  const rows=await page.evaluate(()=>[...document.querySelectorAll('a[href]')].filter(a=>a.getClientRects().length>0).slice(0,3000).map(a=>{const card=a.closest('[data-goods-id], [data-testid="product-card"], [data-test-id="pin"], [class*="product-card"], [class*="product-item"], [class*="goods-item"], article, li')||a;const img=a.querySelector('img')||card.querySelector('img');return {href:a.href,title:a.getAttribute('title')||a.getAttribute('aria-label')||img?.alt||a.innerText,alt:img?.alt||'',image:[img?.currentSrc,img?.src,img?.getAttribute('data-src'),img?.getAttribute('data-original')].find(src=>src&&/^https?:/i.test(src))||'',text:(card.innerText||'').slice(0,3000)}}));
  for(const row of rows){const p=publicProduct(row,target,date);if(p)products.set(p.productId,p);if(products.size>=config.maxProductsPerTarget)break}
  if(products.size>=config.maxProductsPerTarget||scroll===config.maxScrolls)break;
  await page.evaluate(()=>window.scrollBy(0,Math.max(800,window.innerHeight*.85)));await pause(2000);
 }
 if(!products.size){
  const diagnostics=await page.evaluate(()=>({title:document.title,path:location.origin+location.pathname,links:document.querySelectorAll('a[href]').length,images:document.querySelectorAll('img').length,bodyPreview:(document.body.innerText||'').replace(/\s+/g,' ').slice(0,350)}));
  return {target,status:'no_public_products',message:'等待页面加载后仍未识别到公开商品；不视为零商品',diagnostics};
 }
 return {target,status:'ok',message:'已采集公开可见结果，非全量店铺覆盖',products:[...products.values()],pagesVisited:1};
 }catch(error){return {target,status:'failed',message:shortError(error)}}finally{await context.close()}}
try{for(const target of config.targets){const result=await collect(target);observations.push(result);console.log(target.id,result.status,result.products?.length||0,result.message);await pause(2000)}}finally{await browser.close()}
const snapshot=mergeSnapshot(previous,observations,date,now);await mkdir(path.dirname(output),{recursive:true});const temp=output+'.tmp';await writeFile(temp,JSON.stringify(snapshot,null,2)+'\n');await rename(temp,output);
const successes=observations.filter(o=>o.status==='ok').length;console.log(`完成：${successes}/${observations.length} 个目标成功，累计 ${snapshot.products.length} 条真实记录`);
if(process.env.GITHUB_STEP_SUMMARY)await writeFile(process.env.GITHUB_STEP_SUMMARY,`## 每日选款采集\n\n${observations.map(o=>`- ${o.target.platform} / ${o.target.name}: **${o.status}** — ${o.message||''}`).join('\n')}\n\n成功 ${successes}/${observations.length}；原有商品不会因本次失败而删除。\n`,{flag:'a'});
// Non-zero communicates total collection failure; workflow still persists the status report.
if(!successes)process.exitCode=2;
