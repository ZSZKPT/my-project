let state;
const $ = id => document.getElementById(id);
const escape = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
function notice(text) { $('notice').textContent = text; $('notice').style.display = 'block'; clearTimeout(notice.timer); notice.timer = setTimeout(() => $('notice').style.display = 'none', 6500); }
async function request(path, body) {
  const r = await fetch(path, body === undefined ? {} : {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(body)});
  const data = await r.json(); if (!r.ok) throw new Error(data.error || '请求失败'); return data;
}
async function refresh() {
  const chosen = $('templateSelect').value;
  state = await request('/api/state');
  $('templateCount').textContent = state.templates.length; $('imageCount').textContent = state.images.length; $('draftCount').textContent = state.drafts.length;
  $('imageRoot').textContent = state.image_root;
  $('templates').innerHTML = state.templates.map(t => `<div class="card"><strong>${escape(t.name)}</strong><p class="muted">${escape(t.body.category)} · ${t.body.variants.length} 个尺码</p><details><summary>查看模板</summary><pre>${escape(JSON.stringify(t.body,null,2))}</pre></details></div>`).join('') || '<div class="empty">先保存第一个产品模板</div>';
  $('templateSelect').innerHTML = '<option value="">选择产品模板</option>' + state.templates.map(t => `<option value="${escape(t.id)}">${escape(t.name)}</option>`).join(''); $('templateSelect').value = chosen;
  $('nameTable').innerHTML = state.images.length ? `<table><thead><tr><th>文件夹货号 / SKC</th><th>印花名称</th></tr></thead><tbody>${state.images.map((g,i)=>`<tr><td>${escape(g.sku)}</td><td><input class="printName" data-index="${i}" value="${escape(g.print_name)}" placeholder="例如：爱心花朵"></td></tr>`).join('')}</tbody></table>` : '<p class="muted">先将商品图片放入图片目录</p>';
  $('images').innerHTML = state.images.map((g,i) => `<div class="card"><img loading="lazy" src="/image?path=${encodeURIComponent(g.images[0])}" alt="${escape(g.sku)}"><label><input type="checkbox" class="skuCheck" value="${i}">${escape(g.sku)}</label><span class="muted">${g.images.length} 张图片</span></div>`).join('') || '<div class="empty">将图片放入上述目录后，点击刷新图片</div>';
  $('drafts').innerHTML = state.drafts.length ? `<table><thead><tr><th>货号 / 标题</th><th>尺码</th><th>状态</th><th>操作</th></tr></thead><tbody>${state.drafts.map(d => `<tr><td>${escape(d.sku)}<br><span class="muted">${escape(d.body.title)}</span><details><summary>查看草稿</summary><pre>${escape(JSON.stringify(d.body,null,2))}</pre></details></td><td>${d.body.variants.length}</td><td>草稿</td><td><button class="submit" data-id="${escape(d.id)}">尝试提交</button></td></tr>`).join('')}</tbody></table>` : '<div class="empty">选择货号和模板，生成商品草稿</div>';
  $('tasks').innerHTML = state.tasks.map(t => `<div class="card"><strong>阻塞 · ${escape(t.created_at)} UTC</strong><p>${escape(t.message)}</p><span class="muted">草稿 ${escape(t.draft_id)}</span></div>`).join('') || '<div class="empty">暂无上架任务</div>';
}
$('templateForm').onsubmit = async event => {
  event.preventDefault(); const button = event.submitter; button.disabled = true;
  try { const data = Object.fromEntries(new FormData(event.target)); data.variants = data.variants.trim().split('\n').map(line => { const values = line.split(',').map(s => s.trim()); if(values.length !== 3 || !/^\d+$/.test(values[2])) throw new Error('每行填写尺码、价格、整数库存'); return {size:values[0],price:Number(values[1]),stock:Number(values[2])}; }); await request('/api/templates',data); await refresh(); notice('模板已保存'); } catch(e) { notice(e.message); } finally {button.disabled = false;}
};
$('refresh').onclick = () => refresh().catch(e=>notice(e.message));
$('selectAll').onclick = () => { const checks = [...document.querySelectorAll('.skuCheck')]; const all = checks.every(c=>c.checked); checks.forEach(c=>c.checked=!all); };
$('generate').onclick = async () => { const button = $('generate'); button.disabled = true; try { const skus = [...document.querySelectorAll('.skuCheck:checked')].map(c=>state.images[Number(c.value)].sku); const result = await request('/api/generate',{template_id:$('templateSelect').value,skus}); await refresh(); notice(`已生成 ${result.created} 个草稿，跳过 ${result.skipped} 个重复货号`); } catch(e) {notice(e.message);} finally{button.disabled=false;} };
$('drafts').onclick = async event => {const button=event.target.closest('.submit'); if(!button)return; button.disabled=true; try {await request('/api/submit',{draft_id:button.dataset.id});} catch(e){notice(e.message);} finally{await refresh();}};
refresh().catch(e=>notice(e.message));

$('saveNames').onclick = async () => { try { const entries = [...document.querySelectorAll('.printName')].filter(input=>input.value.trim()).map(input=>({sku:state.images[Number(input.dataset.index)].sku,name:input.value.trim()})); const result=await request('/api/print-names',{entries}); notice(`已保存 ${result.saved} 个印花名称`); } catch(e){notice(e.message);} };
