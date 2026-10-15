import {createHash} from 'node:crypto';
export const PLATFORM_HOSTS={Temu:['temu.com'],SHEIN:['shein.com'],LightInTheBox:['lightinthebox.com'],Pinterest:['pinterest.com']};
export function safeURL(value,base){try{const u=new URL(value,base);return ['http:','https:'].includes(u.protocol)?u:null}catch{return null}}
export function allowedURL(value,platform){const u=safeURL(value);return !!u&&PLATFORM_HOSTS[platform]?.some(host=>u.hostname===host||u.hostname.endsWith('.'+host))}
export function productLink(value,target){const u=safeURL(value,target.url);if(!u||!allowedURL(u.href,target.platform))return null;let id;
 if(target.platform==='Temu')id=u.searchParams.get('goods_id')||u.pathname.match(/-g-(\d+)\.html/)?.[1];
 if(target.platform==='SHEIN')id=u.pathname.match(/-p-(\d+)\.html/i)?.[1];
 if(target.platform==='LightInTheBox')id=u.pathname.match(/_p(\d+)\.html/i)?.[1];
 if(target.platform==='Pinterest')id=u.pathname.match(/^\/pin\/(\d+)\/?$/)?.[1];
 if(!id||!/^\d+$/.test(id))return null;
 u.hash='';for(const key of [...u.searchParams.keys()])if(key!=='goods_id')u.searchParams.delete(key);
 return {productId:id,url:u.href};
}
export function metric(text,kind){const token='([\\d][\\d,]*(?:\\.\\d+)?\\s*[kKmMbB万亿]?\\+?)';const suffix={sales:'(?:sold|sales|已售|售出|件已售)',reviews:'(?:reviews?|条评论|评价)',likes:'(?:likes?|点赞)',saves:'(?:saves?|收藏)'}[kind];if(!suffix)return {value:null,text:''};const match=String(text).match(new RegExp(token+'\\s*'+suffix,'i'));if(!match)return {value:null,text:''};const raw=match[1].trim(),plain=raw.replaceAll(',','');return {value:/^\d+$/.test(plain)&&Number.isSafeInteger(Number(plain))?Number(plain):null,text:match[0].trim()}}
export function publicProduct(raw,target,date){const link=productLink(raw.href,target);if(!link)return null;const title=String(raw.title||raw.alt||'').replace(/\s+/g,' ').trim().slice(0,500);const image=safeURL(raw.image,target.url);if(!title||!image)return null;const sales=metric(raw.text,'sales'),reviews=metric(raw.text,'reviews'),likes=metric(raw.text,'likes'),saves=metric(raw.text,'saves');return {...link,platform:target.platform,site:target.site,store:target.name,title,image:image.href,firstSeen:date,lastSeen:date,sales:target.platform==='Pinterest'?null:sales.value,salesText:target.platform==='Pinterest'?'':sales.text,salesEvidence:target.platform!=='Pinterest'&&!!sales.text&&parseFloat(sales.text.replaceAll(',',''))>0,reviews:reviews.value,likes:likes.value,likesText:likes.text,saves:saves.value,savesText:saves.text,price:String(raw.price||'').slice(0,80),tags:target.keyword?[target.keyword]:[],seamless:'未核验',demo:false,source:'daily',targetIds:[target.id]}}
export const identity=p=>JSON.stringify([p.platform,p.site,p.productId]);
export function mergeSnapshot(previous,observations,date,now){const map=new Map((previous.products||[]).map(p=>[identity(p),structuredClone(p)])),prevTargets=new Map((previous.targets||[]).map(t=>[t.id,t]));const reports=[];for(const o of observations){const old=prevTargets.get(o.target.id)||{};const baseline=!old.lastSuccess;const report={...o.target,status:o.status,message:o.message||'',lastAttempt:now,lastSuccess:old.lastSuccess||null,count:0,added:0,coverage:'limited_visible_results',pagesVisited:o.pagesVisited||0,...(o.diagnostics?{diagnostics:o.diagnostics}:{})};if(o.status==='ok'){for(const product of o.products){const k=identity(product),existing=map.get(k);const entry={...product,baseline:existing?.baseline??baseline,firstSeen:existing?.firstSeen||date,targetIds:[...new Set([...(existing?.targetIds||[]),o.target.id])]};entry.history=[...(existing?.history||[]).filter(h=>h.date!==date),{date,sales:product.sales,salesText:product.salesText,reviews:product.reviews,likes:product.likes,saves:product.saves,likesText:product.likesText,savesText:product.savesText}].slice(-90);if(!existing)report.added++;map.set(k,entry)}report.count=o.products.length;report.lastSuccess=now}reports.push(report)}return {version:1,generatedAt:now,timezone:'Asia/Shanghai',schedule:'每日北京时间 09:00，GitHub 调度可能延迟',coverage:'每个目标最多4次滚动、120条公开可见结果；不是整店完整抓取',products:[...map.values()],targets:reports}}
export function shortError(error){const message=String(error?.message||error);if(/timeout/i.test(message))return '访问超时，保留上次成功数据';if(/net::|ENOTFOUND|ECONN|fetch failed/i.test(message))return '网络访问失败，保留上次成功数据';return '采集未完成，保留上次成功数据'}
export function digest(value){return createHash('sha256').update(JSON.stringify(value)).digest('hex')}

export function accessBarrier(url,text=''){
 if(/\/risk\/challenge|\/captcha\b|\/challenge\b/i.test(url)||/verify (?:that )?you are human|unusual traffic|access denied|complete the captcha|验证您|安全验证|访问受限|验证码/i.test(text))return 'verification_required';
 if(/\/auth\/|\/login\b|\/signin\b|passport|login\.html/i.test(url))return 'auth_required';
 return null;
}
