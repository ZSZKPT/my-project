/* Same-origin public feed; local review decisions always take priority. */
'use strict';
const feedStatusNames={stopped:'已停止',wrong_page:'请打开正确的首页',ok:'采集成功',robots_disallowed:'站点规则不允许',robots_unavailable:'采集规则暂不可查',auth_required:'需要登录',verification_required:'需要验证',http_error:'访问被拒绝',no_public_products:'未识别公开商品',redirected:'页面跳转',failed:'采集失败',invalid_target:'目标无效'};
function renderFeedTargets(data){if(!data.targets?.length)return;$('#targetList').innerHTML=data.targets.map(t=>`<article class="target"><span class="pill">${escape(feedStatusNames[t.status]||'等待采集')}</span><h3 style="margin-top:16px">${escape(t.platform)}</h3><p>${escape(t.name||'')}</p><p>站点请求：${escape(t.site||'未知')}<br>最近成功：${escape(t.lastSuccess?new Date(t.lastSuccess).toLocaleString('zh-CN',{timeZone:'Asia/Shanghai'}):'尚无')}<br>本次识别：${Number(t.count)||0} 条</p><p>${escape(t.message||'')}</p><a href="${escape(safeURL(t.url))}" target="_blank" rel="noopener noreferrer">打开目标页面 ↗</a></article>`).join('')}
function syncFeed(){toast('请点击 Chrome 扩展中的“同步在线表格”；本页不会启动云端匿名采集')}
$('#refreshFeed').onclick=syncFeed;
// Explicit transfer from the installed extension to this same browser's selection page.
window.addEventListener('message',event=>{
 if(event.source!==window||event.origin!==location.origin||event.data?.type!=='FEIFAN_BROWSER_CAPTURE')return;
 try{
  const data=event.data.payload;if(data?.mode!=='browser'||!Array.isArray(data.products))throw Error('浏览器采集格式无效');
  today=dateKey();const incoming=data.products.map(p=>normalize({...p,source:'browser'}));
  const map=new Map(state.products.filter(p=>!p.demo).map(p=>[identity(p),p]));
  for(const p of incoming){const old=map.get(identity(p));map.set(identity(p),old?{...p,id:old.id,favorite:old.favorite,notes:old.notes,status:old.status,rating:old.rating}:p)}
  state.products=[...map.values()];localStorage.setItem('feifan-browser-mode','1');
  feedReport={summary:`浏览器采集模式 · 最近同步 ${new Date().toLocaleString('zh-CN',{timeZone:'Asia/Shanghai'})} · ${incoming.length} 条记录。Pinterest 来源为你的首页推荐，数据仅保存在当前浏览器。`};
  persist();render();$('#targetList').innerHTML=(data.reports||[]).slice(0,12).map(t=>`<article class="target"><span class="pill">${escape(feedStatusNames[t.status]||t.status)}</span><h3>${escape(t.platform)}</h3><p>${escape(t.message)}</p><p>${Number(t.count)||0} 条 · ${escape(t.time)}</p></article>`).join('');toast('已接收浏览器采集，保留已有选款备注和收藏');
 }catch(error){toast('浏览器采集导入失败：'+error.message)}
});
{feedReport={summary:'浏览器采集模式 · 请通过 Chrome 扩展采集并同步；Pinterest 使用你的首页推荐。数据仅保存在当前浏览器。'};render()}
