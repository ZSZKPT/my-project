// Runs in the user's ordinary tab, isolated world. Never reads cookies or credentials.
export function readVisible(platform) {
 const url=location.href, text=(document.body?.innerText||'');
 if(/\/risk\/challenge|\/captcha\b|\/challenge\b/i.test(url)||/verify (?:that )?you are human|complete the captcha|unusual traffic|安全验证|验证码|访问受限/i.test(text))return {status:'verification_required',message:'页面出现验证，请在浏览器中手动处理后重试',products:[]};
 if(/\/auth\/|\/login\b|\/signin\b|login\.html/i.test(url))return {status:'auth_required',message:'请先在浏览器中登录平台',products:[]};
 if(platform==='Pinterest'&&!/^\/(?:homefeed\/?)?$/.test(location.pathname))return {status:'wrong_page',message:'Pinterest 请打开首页推荐，而不是搜索、画板或单张 Pin 页面',products:[]};
 const site=platform==='SHEIN'&&location.hostname.startsWith('us.')?'US':'当前浏览器地区';
 const valid=src=>{try{const u=new URL(src,location.href);return /^https?:$/.test(u.protocol)?u.href:''}catch{return ''}};
 const count=(s,kind)=>{const label={sales:'sold|sales|已售|售出',likes:'likes?|点赞',saves:'saves?|收藏',reviews:'reviews?|条评论|评价'}[kind];const m=s.match(new RegExp('([\\d][\\d,]*(?:\\.\\d+)?\\s*[kKmM万]?\\+?)\\s*(?:'+label+')','i'));return {value:m&&/^\d[\d,]*$/.test(m[1].trim())?Number(m[1].trim().replaceAll(',','')):null,text:m?.[0]||''}};
 const rows=new Map();
 for(const a of document.querySelectorAll('a[href]')){
  if(!a.getClientRects().length)continue;
  let u;try{u=new URL(a.href)}catch{continue}
  const hosts={Temu:'temu.com',SHEIN:'shein.com',LightInTheBox:'lightinthebox.com',Pinterest:'pinterest.com'};
  if(u.hostname!==hosts[platform]&&!u.hostname.endsWith('.'+hosts[platform]))continue;
  const productId=platform==='Pinterest'?u.pathname.match(/^\/pin\/(\d+)\/?$/)?.[1]:platform==='Temu'?u.searchParams.get('goods_id')||u.pathname.match(/-g-(\d+)\.html/)?.[1]:platform==='SHEIN'?u.pathname.match(/-p-(\d+)\.html/i)?.[1]:u.pathname.match(/_p(\d+)\.html/i)?.[1];
  if(!productId)continue;
  const card=a.closest('[data-test-id="pin"], [data-goods-id], [class*="product-card"], [class*="product-item"], [class*="goods-item"], article, li')||a;
  const img=a.querySelector('img')||card.querySelector('img');if(!img)continue;
  const image=[img.currentSrc,img.src,img.getAttribute('data-src'),img.getAttribute('data-original')].find(x=>x&&/^https?:/i.test(x));
  const title=(a.getAttribute('title')||a.getAttribute('aria-label')||img.alt||a.innerText||'').replace(/\s+/g,' ').trim().slice(0,500);if(!image||!title)continue;
  u.hash='';for(const key of [...u.searchParams.keys()])if(key!=='goods_id')u.searchParams.delete(key);
  const content=(card.innerText||'').slice(0,2000),sales=count(content,'sales'),likes=count(content,'likes'),saves=count(content,'saves'),reviews=count(content,'reviews');
  rows.set(productId,{platform,site,productId,title,url:u.href,image:valid(image),store:platform==='Pinterest'?'我的首页推荐':'当前页面',sales:platform==='Pinterest'?null:sales.value,salesText:platform==='Pinterest'?'':sales.text,likes:likes.value,likesText:likes.text,saves:saves.value,savesText:saves.text,reviews:reviews.value,tags:platform==='Pinterest'?['首页推荐']:[],seamless:'未核验',source:'browser',demo:false});
 }
 return {status:rows.size?'ok':'no_public_products',message:rows.size?'已读取当前已加载内容':'未识别到图片，请确认页面加载完成；不是零商品结论',products:[...rows.values()]};
}
