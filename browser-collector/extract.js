// Runs only in the user's ordinary tab. Never reads cookies, passwords or account settings.
export function readVisible(platform) {
 const url=location.href,text=document.body?.innerText||'';
 if(/\/risk\/challenge|\/captcha\b|\/challenge\b/i.test(url)||/verify (?:that )?you are human|complete the captcha|unusual traffic|安全验证|验证码|访问受限/i.test(text))return {status:'verification_required',message:'页面出现验证，请在浏览器中手动处理后重试',products:[]};
 if(/\/auth\/|\/login\b|\/signin\b|login\.html/i.test(url))return {status:'auth_required',message:'请先在浏览器中登录平台',products:[]};
 if(platform==='Pinterest'&&!/^\/(?:homefeed\/?)?$/.test(location.pathname))return {status:'wrong_page',message:'Pinterest 请打开首页推荐，而不是搜索、画板或单张 Pin 页面',products:[]};
 const site=platform==='SHEIN'&&location.hostname.startsWith('us.')?'US':'当前浏览器地区';
 const hosts={Temu:'temu.com',SHEIN:'shein.com',LightInTheBox:'lightinthebox.com',Pinterest:'pinterest.com'};
 const count=(s,kind)=>{const label={sales:'sold|sales|已售|售出',likes:'likes?|点赞',saves:'saves?|收藏',reviews:'reviews?|comments?|条评论|评价|评论'}[kind];const m=s.match(new RegExp('([\\d][\\d,]*(?:\\.\\d+)?\\s*[kKmM万]?\\+?)\\s*(?:'+label+')','i'));return {value:m&&/^\d[\d,]*$/.test(m[1].trim())?Number(m[1].trim().replaceAll(',','')):null,text:m?.[0]||''}};
 function colorInfo(scope){
  if(platform==='Pinterest')return {colorCount:null,colorCountExact:false,colors:[]};
  const group=scope.querySelector('[data-testid="color-options"],[data-testid="color-selector"],[class*="color-list"],[class*="colorList"],[class*="color-select"],[class*="colorSelect"],[class*="product-intro__color"],[aria-label="Color"],[aria-label="颜色"]')||scope;
  const text=(group.innerText||'').replace(/\s+/g,' ');const explicit=text.match(/(?:^|[^\d.+])(\d+)\s*(?:colors?\b|colours?\b|种颜色|个颜色|色可选)/i)||text.match(/(?:颜色|配色)\s*[:：]?\s*(\d+)\s*(?:种|款|色)/);
  const selector='[data-color-name],[data-color-id],[data-color],[data-testid*="color-swatch"],[data-test-id="color-swatch"],[class*="color-swatch"],[class*="colorSwatch"]';const choices=new Map();let index=0;for(const el of group.querySelectorAll(selector)){if(!el.getClientRects().length||el.querySelector(selector))continue;const label=(el.getAttribute('data-color-name')||el.getAttribute('data-color')||el.getAttribute('title')||el.getAttribute('aria-label')||'').trim();if(/^(?:more|更多|\+?\d+)(?: colors?)?$/i.test(label))continue;const key=(label||el.getAttribute('data-color-id')||'visible-option-'+index++).toLowerCase();choices.set(key,label||'未命名颜色选项')}
  const total=explicit?Number(explicit[1]):null;const exact=Number.isSafeInteger(total)&&total>=1&&total>=choices.size;return {colorCount:exact?total:choices.size>=2?choices.size:null,colorCountExact:exact,colors:[...choices.values()]};
 }
 function reviewInfo(scope,content){const labelled=count(content,'reviews');const reversed=content.match(/(?:reviews?|comments?|评价|评论)\s*[:：]?\s*[（(]\s*([\d,]+)\s*[)）]/i);if(labelled.value===null&&reversed&&/^\d[\d,]*$/.test(reversed[1])){labelled.value=Number(reversed[1].replaceAll(',',''));labelled.text=reversed[0]}if(labelled.value!==null)return {reviews:labelled.value,reviewsText:labelled.text};const el=[...scope.querySelectorAll('[data-review-count],[data-testid="review-count"],[class*="review-count"],[class*="reviewCount"]')].find(el=>el.getClientRects().length);const raw=(el?.getAttribute('data-review-count')||el?.innerText||'').trim();const plain=raw.replace(/[(),\s]/g,'');const n=/^\d+$/.test(plain)&&Number.isSafeInteger(Number(plain))?Number(plain):null;return {reviews:n,reviewsText:raw||labelled.text}}
 const rows=new Map();
 function add(href,node,card,preferredImage){
  if(!node.getClientRects().length)return;let u;try{u=new URL(href,location.href)}catch{return}
  if(u.hostname!==hosts[platform]&&!u.hostname.endsWith('.'+hosts[platform]))return;
  const productId=platform==='Pinterest'?u.pathname.match(/^\/pin\/(?:[^/?#]+--)?(\d+)\/?$/)?.[1]:platform==='Temu'?u.searchParams.get('goods_id')||u.pathname.match(/-g-(\d+)\.html/)?.[1]:platform==='SHEIN'?u.pathname.match(/-p-(\d+)\.html/i)?.[1]:u.pathname.match(/_p(\d+)\.html/i)?.[1];
  if(!productId)return;
  card=card||node.closest('[data-test-id="pin"],[data-test-id="pinWrapper"],[data-test-pin-id],[data-goods-id],[class*="product-card"],[class*="product-item"],[class*="goods-item"],article,li')||node;
  const img=preferredImage||node.querySelector('img')||card.querySelector('img');if(!img)return;
  const srcset=(img.getAttribute('srcset')||img.getAttribute('data-srcset')||'').split(',').map(x=>x.trim().split(/\s+/)[0]).reverse();
  const image=[img.currentSrc,img.src,img.getAttribute('data-src'),img.getAttribute('data-original'),...srcset].find(x=>x&&/^https?:/i.test(x));if(!image)return;
  const title=([img.alt,node.getAttribute('title'),node.getAttribute('aria-label'),node.innerText,platform==='Pinterest'?'Pinterest 首页推荐 '+productId:''].map(value=>String(value||'').replace(/\s+/g,' ').trim()).find(Boolean)||'').slice(0,500);if(!title)return;
  u.hash='';for(const key of [...u.searchParams.keys()])if(key!=='goods_id')u.searchParams.delete(key);
  const content=(card.innerText||'').slice(0,2000),sales=count(content,'sales'),likes=count(content,'likes'),saves=count(content,'saves'),reviews=count(content,'reviews');
  rows.set(productId,{platform,site,productId,title,url:u.href,image,store:platform==='Pinterest'?'我的首页推荐':'当前页面',sales:platform==='Pinterest'?null:sales.value,salesText:platform==='Pinterest'?'':sales.text,likes:likes.value,likesText:likes.text,saves:saves.value,savesText:saves.text,...reviewInfo(card,content),...colorInfo(card),tags:platform==='Pinterest'?['首页推荐']:[],seamless:'未核验',source:'browser',demo:false});
 }
 for(const a of document.querySelectorAll('a[href]'))add(a.href,a);
 if(platform!=='Pinterest'){const detail=document.querySelector('[data-testid="product-detail"],[data-test-id="product-detail"],[class*="product-intro"],[id="productDetail"]');if(detail){const img=detail.querySelector('[class*="gallery"] img,[class*="Gallery"] img,[data-testid="product-image"] img')||detail.querySelector('img');if(img)add(location.href,detail,detail,img)}}
 if(platform==='Pinterest')for(const card of document.querySelectorAll('[data-test-pin-id],[data-pin-id]')){const id=card.getAttribute('data-test-pin-id')||card.getAttribute('data-pin-id');if(/^\d+$/.test(id||''))add('https://www.pinterest.com/pin/'+id+'/',card,card)}
 return {status:rows.size?'ok':'no_public_products',message:rows.size?'已读取当前已加载内容':`未识别到图片：页面有 ${document.querySelectorAll('img').length} 张图片、${document.querySelectorAll('a[href]').length} 个链接、${document.querySelectorAll('[data-test-id="pin"]').length} 个Pin卡片。请确认已登录并尝试自动滚动加载；不是零商品结论`,products:[...rows.values()]};
}
