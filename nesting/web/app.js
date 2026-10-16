const $=id=>document.getElementById(id), NS='http://www.w3.org/2000/svg';
const settingKeys=['width','left','right','gap','head','tail','seconds','iterations','seed'];
let project={version:1,unit:'mm',pieces:[],placements:[],settings:{}}, result=null, selected=null, editing=null, draft=null, jobId=null, busy=false, zoom=1, pendingFiles=[], past=[], future=[], revision=0;
function toast(message){$('toast').textContent=message;$('toast').classList.add('show');clearTimeout(toast.timer);toast.timer=setTimeout(()=>$('toast').classList.remove('show'),6000)}
function guarded(fn){return async(...args)=>{try{await fn(...args)}catch(e){toast(e.message||String(e))}}}
async function api(path,body){const response=await fetch(path,{method:body===undefined?'GET':'POST',headers:body===undefined?{}:{'Content-Type':'application/json'},body:body===undefined?undefined:JSON.stringify(body)});if(!response.ok){const error=await response.json();const failure=Error(error.error||'请求失败');failure.details=error;throw failure}return response.json()}
const el=(tag,attrs={},text)=>{const n=document.createElementNS(NS,tag);Object.entries(attrs).forEach(([k,v])=>n.setAttribute(k,v));if(text!==undefined)n.textContent=text;return n};
function pathOf(contours){return contours.map(r=>'M'+r.map(p=>p.join(',')).join(' L')+' Z').join(' ')}
function centroid(contours){let area=0,cx=0,cy=0;for(const ring of contours){let a=0,x=0,y=0;for(let i=0;i<ring.length;i++){const p=ring[i],q=ring[(i+1)%ring.length],cross=p[0]*q[1]-q[0]*p[1];a+=cross;x+=(p[0]+q[0])*cross;y+=(p[1]+q[1])*cross}if(Math.abs(a)>1e-10){const weight=Math.abs(a);area+=weight;cx+=x/(3*a)*weight;cy+=y/(3*a)*weight}}return area?[cx/area,cy/area]:contours[0][0]}
function getSettings(){return Object.fromEntries(settingKeys.map(k=>[k,Number($(k).value)]))}
function syncSettings(){for(const p of project.pieces)if(p.verticalOnly)p.fixedPair=true;project.settings=getSettings();$('effectiveWidth').textContent=`${(project.settings.width-project.settings.left-project.settings.right).toFixed(1)} mm`}
function loadSettings(){settingKeys.forEach(k=>{if(project.settings[k]!==undefined)$(k).value=project.settings[k]});syncSettings()}
function invalidate(clear=true){revision++;result=null;if(clear){project.placements=[];past=[];future=[];selected=null}render()}
function remember(){past.push(structuredClone(project.placements));if(past.length>25)past.shift();future=[];revision++}
function findPiece(pid){return project.pieces.find(p=>p.id===pid)}
function picked(){return project.placements.find(p=>p.key===selected)}
function familyOf(piece){return piece?.verticalOnly?project.pieces.filter(p=>p.sourceGroup===piece.sourceGroup):[piece]}
function familyPlacements(piece){const ids=new Set(familyOf(piece).map(p=>p.id));return project.placements.filter(p=>ids.has(p.pieceId))}

function updateInspector(){const p=picked();$('inspector').hidden=!p;if(!p)return;const piece=findPiece(p.pieceId);$('selectedName').textContent=piece?.name||p.key;$('posX').value=p.x.toFixed(2);$('posY').value=p.y.toFixed(2);$('lock').textContent=p.locked?'解除锁定':'锁定位置';$('rotate').disabled=busy||familyPlacements(piece).some(p=>p.locked)||familyOf(piece).some(p=>!p.allow180);$('rotate').textContent=piece.verticalOnly?'整组旋转180°':'旋转180°';$('lock').disabled=busy;$('posX').disabled=busy||familyPlacements(piece).some(p=>p.locked);$('posY').disabled=busy||familyPlacements(piece).some(p=>p.locked)}
function renderList(){const list=$('pieceList');list.replaceChildren();$('pieceCount').textContent=project.pieces.length;const ready=project.pieces.filter(p=>p.confirmed&&p.dimensionConfirmed).length;$('readyCount').textContent=`${new Set(project.pieces.map(p=>p.sourceGroup||p.id)).size} 文件 · ${project.pieces.length} 片自动导入`;
 for(const piece of project.pieces){const row=document.createElement('div');row.className='piece-row'+(picked()?.pieceId===piece.id?' active':'');const img=document.createElement('img');img.className='thumb';img.src=piece.source;img.alt='';const info=document.createElement('div');info.className='piece-info';const title=document.createElement('strong');title.textContent=piece.name;const size=document.createElement('small');size.textContent=piece.dimensionConfirmed?`${piece.width.toFixed(1)} × ${piece.height.toFixed(1)} mm`:'待填写实际尺寸';const tag=document.createElement('span');tag.className='tiny-tag'+(piece.confirmed&&piece.dimensionConfirmed?'':' pending');tag.textContent=piece.confirmed&&piece.dimensionConfirmed?piece.verticalOnly?'原图整组固定 · 标签保留':'自动导入 · 1片':'待填写尺寸 · 1片';info.append(title,size,tag);row.append(img,info);row.addEventListener('click',()=>{if(busy)return;openPiece(piece.id)});list.append(row)}
}
function renderCanvas(){const svg=$('layout');svg.replaceChildren();$('emptyState').hidden=project.placements.length>0;if(!project.placements.length){svg.style.width='';return}const s=project.settings;const actualLength=result?.stats?.length||Math.max(...project.placements.map(p=>p.y+(findPiece(p.pieceId)?.height||0)+s.tail),10);const length=actualLength;const pad=45,W=s.width+2*pad,H=length+2*pad;
 svg.setAttribute('viewBox',`${-pad} ${-pad} ${W} ${H}`);svg.style.width=`${zoom*100}%`;svg.style.height='auto';svg.setAttribute('width',W);svg.setAttribute('height',H);
 const defs=el('defs');const grid=el('pattern',{id:'grid',width:100,height:100,patternUnits:'userSpaceOnUse'});grid.append(el('path',{d:'M 100 0 L 0 0 0 100',fill:'none',stroke:'#e4e8df','stroke-width':1}));defs.append(grid);svg.append(defs);
 svg.append(el('rect',{x:0,y:0,width:s.width,height:length,fill:'#fffdf8'}),el('rect',{x:0,y:0,width:s.width,height:length,fill:'url(#grid)'}));
 for(const [x,w] of [[0,s.left],[s.width-s.right,s.right]])svg.append(el('rect',{x,y:0,width:w,height:length,fill:'#dfe8dc'}));
 if(s.head)svg.append(el('rect',{x:0,y:0,width:s.width,height:s.head,fill:'#eee8d6',opacity:.6}));
 if(s.tail)svg.append(el('rect',{x:0,y:length-s.tail,width:s.width,height:s.tail,fill:'#eee8d6',opacity:.6}));
 svg.append(el('rect',{x:s.left,y:s.head,width:s.width-s.left-s.right,height:Math.max(0,length-s.head-s.tail),fill:'none',stroke:'#9bad94','stroke-width':1.2,'stroke-dasharray':'7 6'}));
 for(let x=0;x<=s.width;x+=200)svg.append(el('text',{x,y:-14,'font-size':16,fill:'#9aa38e','text-anchor':'middle'},x));
 for(let y=0;y<=length;y+=200)svg.append(el('text',{x:-15,y:y+5,'font-size':15,fill:'#9aa38e','text-anchor':'end'},y));
 const bad=new Set((result?.errors||[]).flatMap(e=>e.keys));
 project.placements.forEach((p,i)=>{const piece=findPiece(p.pieceId);if(!piece)return;const yValues=piece.contours.flat().map(point=>p.y+(p.angle===180?piece.height-point[1]:point[1]));if(Math.min(...yValues)>length)return;const transform=`translate(${p.x} ${p.y})`+(p.angle===180?` translate(${piece.width} ${piece.height}) rotate(180)`:'');const group=el('g',{transform,'data-key':p.key,style:busy?'cursor:default':'cursor:grab'});const color=bad.has(p.key)?'#c4664e':(selected===p.key?'#28654a':'#71977c');
 const mask=el('mask',{id:`m${i}`,maskUnits:'userSpaceOnUse',x:-100,y:-100,width:piece.width+200,height:piece.height+200});mask.append(el('path',{d:pathOf(piece.contours),fill:'white',stroke:'white','stroke-width':2*((piece.bleed||0)+(piece.contourTolerance||0)),'stroke-linejoin':'round'}));defs.append(mask);
 group.append(el('path',{d:pathOf(piece.contours),fill:['#e1ead7','#ecddc4','#d6e2df','#e7d4ca'][i%4],stroke:color,'stroke-width':1}));
 if($('showArt').checked)group.append(el('image',{href:piece.source,width:piece.width,height:piece.height,preserveAspectRatio:'none',mask:`url(#m${i})`,'pointer-events':'none'}));
 if(piece.bleed)group.append(el('path',{d:pathOf(piece.contours),fill:'none',stroke:color,'stroke-width':2*piece.bleed,'stroke-opacity':.15,'pointer-events':'none'}));
 group.append(el('path',{d:pathOf(piece.contours),fill:'transparent',stroke:color,'stroke-width':selected===p.key?2:1,'vector-effect':'non-scaling-stroke'}));
 svg.append(group);
 if($('showLabels').checked){const center=centroid(piece.contours);const tx=p.x+(p.angle===180?piece.width-center[0]:center[0]),ty=p.y+(p.angle===180?piece.height-center[1]:center[1]);const text=el('text',{x:tx,y:ty,'font-size':18,'text-anchor':'middle',fill:'#244c3a',stroke:'#fffdf8','stroke-width':4,'paint-order':'stroke','pointer-events':'none'},`${piece.name}${p.locked?' 🔒':''} · ${p.angle}°`);svg.append(text)}
 });
}
function renderStats(){const stats=result?.stats,total=project.pieces.length;$('lengthMetric').innerHTML=stats?`${(stats.length/1000).toFixed(3)}<small> m</small>`:'—<small> m</small>';$('utilMetric').innerHTML=stats?`${(stats.effectiveUtilization*100).toFixed(1)}<small> %</small>`:'—<small> %</small>';$('countMetric').innerHTML=`${project.placements.length} <small>/ ${total} 片</small>`;
 const base=result?.comparison?.[0]?.length;const saving=stats&&base?100*(base-stats.length)/base:null;$('savingMetric').innerHTML=saving===null?'—<small> %</small>':`${saving.toFixed(1)}<small> %</small>`;
 $('verifyStatus').textContent=result?(result.valid?'通过 ✓':'存在问题'):'未复核';$('statusBadge').textContent=busy?'正在寻找更优方案':(result?.valid?'复核通过':project.pieces.length?'待排料 / 核对':'等待导入');$('statusBadge').classList.toggle('running',busy);
 $('resultMessage').textContent=stats?`全图预览，可向下滚动查看所有裁片 · 有效门幅 ${stats.effectiveWidth.toFixed(1)} mm · 完整门幅利用率 ${(stats.fullUtilization*100).toFixed(1)}% · 净面积 ${(stats.netArea/1e6).toFixed(3)} m² · 出血/保守余量占用 ${((stats.occupiedArea-stats.netArea)/1e6).toFixed(3)} m² · 面积下界 ${(stats.areaLowerBound/1000).toFixed(3)} m（仅供参考）${result.seconds!==undefined?` · 已计算 ${result.seconds.toFixed(2)} s / ${result.iterations} 轮${result.gridRounds?` + ${result.gridRounds}轮整组换位`:''} · ${result.phase||'搜索'} · 已保留${result.acceptedMoves||0}次改善${result.timedOut?'，达到时间上限':''}${result.stopped?'，已停止':''}`:''}`:'默认110 DPI、轮廓净间距3 mm；左右双片保持原始相对位置、整组排料，原图标签随片打印。';
 $('errorList').replaceChildren();for(const error of (result?.errors||[]).slice(0,8)){const line=document.createElement('div');line.className='error-line';line.textContent=`${error.message}：${error.keys.map(k=>findPiece(k.split('::')[0])?.name||k).slice(0,5).join('、')}`;$('errorList').append(line)}
 $('comparison').replaceChildren();for(const item of result?.comparison||[]){const card=document.createElement('div');card.textContent=item.label;const number=document.createElement('strong');number.textContent=`${(item.length/1000).toFixed(3)} m`;const text=document.createElement('span');text.textContent=`利用率 ${(item.effectiveUtilization*100).toFixed(1)}% · ${item.seconds.toFixed(2)} s`;card.append(number,text);$('comparison').append(card)}
 $('solve').disabled=busy||!total;$('stop').hidden=!busy;$('stop').disabled=!jobId;['importBtn','importLink','demo','openProject','saveProject','export','validateBtn','emptyDemo','binding'].forEach(k=>$(k).disabled=busy);settingKeys.forEach(k=>$(k).disabled=busy);$('mode').disabled=busy;$('undo').disabled=busy||!past.length;$('redo').disabled=busy||!future.length;
}
function render(){renderList();renderCanvas();renderStats();updateInspector()}
async function check(){syncSettings();const rev=++revision;const current=await api('/api/validate',project);if(rev!==revision)return current;const previous=result;result={...current,...(previous?.comparison?{comparison:previous.comparison,seconds:previous.seconds,iterations:previous.iterations,timedOut:previous.timedOut,stopped:previous.stopped,phase:previous.phase,acceptedMoves:previous.acceptedMoves,gridRounds:previous.gridRounds}:{})};render();return current}
async function recheck(){try{await check()}catch(e){result=null;render();toast(e.message)}}
function fileData(file){return new Promise((resolve,reject)=>{const reader=new FileReader();reader.onload=()=>resolve(reader.result);reader.onerror=reject;reader.readAsDataURL(file)})}
function askFiles(files){if(busy)return;pendingFiles=[...files].filter(f=>/\.(jpe?g|png|svg)$/i.test(f.name));if(!pendingFiles.length)return toast('请选择 JPG、PNG 或 SVG 文件');$('importFilesLabel').textContent=`已选择 ${pendingFiles.length} 个文件；双片模式会自动识别每个文件的左右片，无需设置数量。`;$('importDialog').showModal()}
let fragmentFallback=null;
async function importOne(file,options){
 const data=await fileData(file);let request={filename:file.name,data,...options};let asset;
 try{asset=await api('/api/import',request)}catch(error){
  const info=error.details;if(info?.code!=='fragmented_contour')throw error;
  let choice=fragmentFallback;
  if(!choice){const suggestion=info.suggestedMinArea?`1：去噪，剔除小于${info.suggestedMinArea}像素²的区域，保留${info.keptComponents}个区域，移除前景面积约${info.removedAreaPercent.toFixed(2)}%。可能删除真实小图案。`:'1：无安全去噪建议，请使用其他方式。';choice=prompt(`${file.name}：识别到${info.components}个分离区域。\n${suggestion}\n2：保守包络，保留全部识别前景，填补凹口和间隙；可能较费料，不等于真实切割线。\n取消：跳过，可用配套SVG或矩形模式重导。\n选择将用于本批其他同类失败文件，导入后仍须逐片确认。\n请输入 1 或 2：`,'2');if(!['1','2'].includes(choice))throw Error('已跳过分离轮廓文件，请换用配套SVG或其他模式');fragmentFallback=choice;}
  if(choice==='1'){if(!info.suggestedMinArea)throw Error('没有可保留主体的去噪阈值，请使用保守包络或配套SVG');request.minArea=info.suggestedMinArea;}
  else{request.mode=(request.mode==='alpha'?'alpha':'background')+'-hull';request.minArea=0;}
  asset=await api('/api/import',request);
 }
 if(asset.needsSelection){const ids=asset.svgElements.map(e=>e.id).filter(Boolean);const id=prompt(`SVG包含多个元素，请填写切割轮廓ID：\n${ids.join('、')}`);if(!id)throw Error('已取消此SVG导入');asset=await api('/api/import',{...request,cutId:id})}return asset;
}
$('files').addEventListener('change',e=>{askFiles(e.target.files);e.target.value=''});['importBtn','importLink'].forEach(k=>$(k).onclick=()=>$('files').click());const drop=$('dropzone');drop.ondragover=e=>{e.preventDefault();drop.classList.add('over')};drop.ondragleave=()=>drop.classList.remove('over');drop.ondrop=e=>{e.preventDefault();drop.classList.remove('over');askFiles(e.dataTransfer.files)};
$('importMode').onchange=()=>{$('threshold').value=$('importMode').value==='alpha'?128:20};
$('importForm').onsubmit=guarded(async e=>{e.preventDefault();fragmentFallback=null;$('confirmImport').disabled=true;const errors=[];try{let count=0;for(const file of pendingFiles){$('confirmImport').textContent=`处理中 ${++count}/${pendingFiles.length}`;try{const asset=await importOne(file,{mode:$('importMode').value,dpi:$('importDpi').value||null,background:$('background').value,threshold:Number($('threshold').value),minArea:Number($('minArea').value)});const imported=asset.splitPieces||[asset];for(const part of imported){part.confirmed=part.dimensionConfirmed===true;project.pieces.push(part)}}catch(err){errors.push(`${file.name}：${err.message}`)}}invalidate();$('importDialog').close();if(errors.length)alert(errors.join('\n'));else toast(`已自动导入${pendingFiles.length}个文件，无需逐片确认；二维码、连接条与尺码随片保留`)}finally{$('confirmImport').disabled=false;$('confirmImport').textContent='开始导入'}});
function previewPiece(){if(!draft)return;const svg=$('assetPreview');svg.replaceChildren();const w=draft.width,h=draft.height;svg.setAttribute('viewBox',`${-w*.03} ${-h*.03} ${w*1.06} ${h*1.06}`);svg.append(el('image',{href:draft.source,width:w,height:h,preserveAspectRatio:'none'}),el('path',{d:pathOf(draft.contours),fill:'#4eaa6420',stroke:'#217b4d','stroke-width':2,'vector-effect':'non-scaling-stroke'}))}
function openPiece(id){editing=id;const p=findPiece(id);draft=structuredClone(p);$('pieceName').value=p.name;$('pieceStyle').value=p.style||'';$('pieceSize').value=p.size||'';$('pieceWidth').value=p.dimensionConfirmed?p.width.toFixed(6):'';$('pieceHeight').value=p.dimensionConfirmed?p.height.toFixed(6):'';$('pieceAllow180').checked=p.allow180;$('pieceBleed').value=p.bleed||0;$('pieceConfirmed').checked=true;$('contourSource').textContent=p.contourSource;$('dimensionNote').textContent=p.dimensionConfirmed?`${p.pixelWidth?`${p.pixelWidth} × ${p.pixelHeight} px · `:''}${p.dpi?`DPI ${p.dpi.map(n=>n.toFixed(1)).join(' × ')}`:'毫米尺寸'}${p.hasICC?' · 素材含ICC；本应用不作色彩转换':''}`:'没有可信物理尺寸：请填写实际宽、高（含图片画布），禁止把像素数当毫米。';$('pieceWidth').disabled=!!p.verticalOnly;$('pieceHeight').disabled=!!p.verticalOnly;$('sidecar').disabled=!!p.verticalOnly;previewPiece();$('pieceDialog').showModal()}
function resizeDraft(){if(draft.verticalOnly)return;const w=Number($('pieceWidth').value),h=Number($('pieceHeight').value);if(w>0&&h>0){const rx=w/draft.width,ry=h/draft.height;draft.contours=draft.contours.map(r=>r.map(([x,y])=>[x*rx,y*ry]));draft.width=w;draft.height=h;draft.dimensionConfirmed=true;previewPiece()} }
['pieceWidth','pieceHeight'].forEach(k=>$(k).oninput=()=>{resizeDraft();$('pieceConfirmed').checked=false});
$('savePiece').onclick=guarded(async()=>{resizeDraft();if(!draft.dimensionConfirmed||!Number($('pieceWidth').value)||!Number($('pieceHeight').value))throw Error('请填写实际宽、高');draft.name=$('pieceName').value.trim()||draft.filename;draft.style=$('pieceStyle').value;draft.size=$('pieceSize').value;draft.allow180=$('pieceAllow180').checked;draft.bleed=Number($('pieceBleed').value);draft.confirmed=true;draft.quantity=1;project.pieces[project.pieces.findIndex(p=>p.id===editing)]=draft;invalidate();$('pieceDialog').close();toast('编辑已保存，旧排料已清除，可直接重新排料')});
$('deletePiece').onclick=()=>{const current=findPiece(editing);project.pieces=project.pieces.filter(p=>current.verticalOnly?p.sourceGroup!==current.sourceGroup:p.id!==editing);invalidate();$('pieceDialog').close()};
$('sidecar').onclick=()=>$('sidecarFile').click();$('sidecarFile').onchange=guarded(async e=>{const file=e.target.files[0];e.target.value='';if(!file)return;resizeDraft();if(!draft.dimensionConfirmed)throw Error('请先填写JPG的实际宽、高');const asset=await importOne(file,{width:draft.width,height:draft.height});draft.contours=asset.contours;draft.contourTolerance=asset.contourTolerance;draft.contourSource='配套SVG切割轮廓：'+asset.contourSource;$('contourSource').textContent=draft.contourSource;$('pieceConfirmed').checked=false;previewPiece();toast('请确认SVG与JPG画布坐标及边缘一致')});
document.querySelectorAll('.close-dialog').forEach(b=>b.onclick=()=>b.closest('dialog').close());
settingKeys.forEach(k=>$(k).onchange=()=>{syncSettings();revision++;result=null;render();if(project.placements.length)recheck()});
$('mode').onchange=()=>{const value={quick:[3,3],standard:[15,12],fine:[60,60]}[$('mode').value];$('seconds').value=value[0];$('iterations').value=value[1];syncSettings()};
$('solve').onclick=guarded(async()=>{syncSettings();if(project.pieces.some(p=>!p.confirmed||!p.dimensionConfirmed))throw Error('部分文件缺少实际尺寸，请填写DPI或尺寸');remember();busy=true;render();try{const job=await api('/api/solve',project);jobId=job.id;renderStats();pollJob()}catch(e){busy=false;render();throw e}});
async function pollJob(){try{const job=await api('/api/jobs/'+jobId);if(job.result){result=job.result;project.placements=result.placements;render()}if(job.state==='running'){setTimeout(pollJob,400);return}busy=false;jobId=null;render();if(job.state==='error')toast(job.error);else toast(result?.stopped?'已停止，保留当前最佳可行方案':'排料完成，已进行独立复核')}catch(e){busy=false;render();toast('任务状态读取失败：'+e.message)}}
$('stop').onclick=guarded(async()=>{if(jobId)await api('/api/stop/'+jobId)});$('validateBtn').onclick=guarded(check);
$('undo').onclick=()=>{if(!past.length||busy)return;future.push(structuredClone(project.placements));project.placements=past.pop();result=null;render();recheck()};$('redo').onclick=()=>{if(!future.length||busy)return;past.push(structuredClone(project.placements));project.placements=future.pop();result=null;render();recheck()};
for(const [id,key] of [['posX','x'],['posY','y']])$(id).onchange=()=>{const p=picked();if(!p||p.locked||busy)return;const value=Number($(id).value);if(Math.abs(p[key]-value)<1e-8)return;if(familyPlacements(findPiece(p.pieceId)).some(p=>p.locked))return;remember();{const delta=value-p[key];for(const member of familyPlacements(findPiece(p.pieceId)))member[key]+=delta}recheck()};
$('rotate').onclick=()=>{const p=picked();if(!p||busy)return;const family=familyPlacements(findPiece(p.pieceId));if(family.some(p=>p.locked)||familyOf(findPiece(p.pieceId)).some(p=>!p.allow180))return;remember();const sumY=Math.min(...family.map(p=>p.y))+Math.max(...family.map(p=>p.y));for(const member of family){member.angle=member.angle===0?180:0;member.y=sumY-member.y}recheck()};$('lock').onclick=()=>{const p=picked();if(!p||busy)return;remember();p.locked=!p.locked;render()};$('editSelected').onclick=()=>{if(picked())openPiece(picked().pieceId)};
let drag=null;
function queueDragValidation(d){
 if(d.timer)return;
 d.timer=setTimeout(async()=>{d.timer=null;if(drag!==d)return;const snapshot=structuredClone(project);const generation=d.generation;try{const current=await api('/api/validate',snapshot);if(drag!==d||d.generation!==generation)return;result=current;renderStats();const bad=new Set(current.errors.flatMap(e=>e.keys));for(const group of $('layout').querySelectorAll('[data-key]')){const outline=group.lastElementChild;if(outline?.tagName==='path')outline.setAttribute('stroke',bad.has(group.getAttribute('data-key'))?'#c4664e':group.getAttribute('data-key')===selected?'#28654a':'#71977c')}}catch(e){if(drag===d)toast(e.message)}},140);
}

function svgPoint(e){return new DOMPoint(e.clientX,e.clientY).matrixTransform($('layout').getScreenCTM().inverse())}
$('layout').addEventListener('pointerdown',e=>{if(e.altKey||e.button===1){drag={pan:true,clientX:e.clientX,clientY:e.clientY,left:$('canvasScroll').scrollLeft,top:$('canvasScroll').scrollTop};$('layout').setPointerCapture(e.pointerId);e.preventDefault();return}const group=e.target.closest('[data-key]');if(!group)return;selected=group.getAttribute('data-key');const p=picked();if(!busy&&!familyPlacements(findPiece(p.pieceId)).some(p=>p.locked)){const point=svgPoint(e);drag={key:p.key,start:point,x:p.x,y:p.y,before:structuredClone(project.placements),moved:false,generation:0};$('layout').setPointerCapture(e.pointerId)}updateInspector();});
$('layout').addEventListener('pointermove',e=>{if(!drag)return;if(drag.pan){$('canvasScroll').scrollLeft=drag.left-(e.clientX-drag.clientX);$('canvasScroll').scrollTop=drag.top-(e.clientY-drag.clientY);return}const p=picked(),point=svgPoint(e);if(!p)return;const dx=point.x-drag.start.x,dy=point.y-drag.start.y;for(const member of familyPlacements(findPiece(p.pieceId))){const original=drag.before.find(q=>q.key===member.key);member.x=original.x+dx;member.y=original.y+dy;const piece=findPiece(member.pieceId),group=[...$('layout').querySelectorAll('[data-key]')].find(g=>g.getAttribute('data-key')===member.key);group?.setAttribute('transform',`translate(${member.x} ${member.y})`+(member.angle===180?` translate(${piece.width} ${piece.height}) rotate(180)`:''))}drag.moved=true;drag.generation++;queueDragValidation(drag);updateInspector();});
async function finishDrag(){if(!drag)return;const d=drag;drag=null;if(d.pan)return;if(d.moved){past.push(d.before);future=[];revision++;await recheck()}else{renderCanvas();renderList();updateInspector()}}
$('layout').addEventListener('pointerup',guarded(finishDrag));$('layout').addEventListener('pointercancel',guarded(finishDrag));
function setZoom(value){zoom=Math.max(.5,Math.min(5,value));$('zoomText').textContent=Math.round(zoom*100)+'%';renderCanvas()}
$('zoomIn').onclick=()=>setZoom(zoom+.25);$('zoomOut').onclick=()=>setZoom(zoom-.25);$('fit').onclick=()=>setZoom(1);$('showArt').onchange=renderCanvas;$('showLabels').onchange=renderCanvas;
async function loadDemo(){if(project.pieces.length&&!confirm('载入演示会替换当前项目，是否继续？'))return;project=await api('/api/example');selected=null;past=[];future=[];result=null;loadSettings();render();toast('演示数据为虚构样本；文件已确认，可直接开始排料')}
$('demo').onclick=guarded(loadDemo);$('emptyDemo').onclick=guarded(loadDemo);
function nativeResult(result){if(result?.error)throw Error(result.error);if(result?.cancelled)toast('已取消保存');else if(result?.saved)toast(`已保存：${result.filename}`);return result}
async function download(blob,name){
 const native=window.pywebview?.api;
 if(native?.save_data){const encoded=await new Promise((resolve,reject)=>{const reader=new FileReader();reader.onload=()=>resolve(reader.result.split(',')[1]);reader.onerror=()=>reject(Error('读取保存内容失败'));reader.readAsDataURL(blob)});return nativeResult(await native.save_data(encoded,name))}
 const url=URL.createObjectURL(blob),a=document.createElement('a');a.href=url;a.download=name;a.click();setTimeout(()=>URL.revokeObjectURL(url),10000);return {saved:true};
}
$('saveProject').onclick=guarded(async()=>{syncSettings();if(project.placements.length){const v=await check();if(!v.valid)throw Error('当前排料有冲突，请修正后保存；也可重新排料')}const saved=await download(new Blob([JSON.stringify(project)],{type:'application/json'}),'布序项目.nest.json');if(!saved?.cancelled)toast('项目已保存，包含原始素材；请妥善保存')});
$('openProject').onclick=()=>$('projectFile').click();$('projectFile').onchange=guarded(async e=>{const file=e.target.files[0];e.target.value='';if(!file)return;if(file.size>100*1024*1024)throw Error('项目超过100MB');const candidate=JSON.parse(await file.text());for(const p of candidate.pieces||[])if(p.verticalOnly)p.fixedPair=true;if(candidate.version!==1||candidate.unit!=='mm'||!Array.isArray(candidate.pieces)||!Array.isArray(candidate.placements)||!candidate.settings)throw Error('项目格式或版本不支持');if(candidate.pieces.some(p=>p.quantity!==1))throw Error('每个自动识别的裁片仅排一份，不支持数量合并');if(candidate.pieces.length>500)throw Error('最多500片');
 // Validate all source assets through the local importer before rendering untrusted data URLs.
 for(const p of candidate.pieces){if(!/^data:image\/(png|jpeg|svg\+xml);base64,/.test(p.source||''))throw Error('项目含不支持的素材');if(typeof p.name!=='string'||!Number.isFinite(p.width)||!Number.isFinite(p.height)||!Array.isArray(p.contours))throw Error('裁片格式错误')}
 await api('/api/project/check',candidate);
 const prepared=candidate.placements.length?await api('/api/validate',candidate):null;
 project=candidate;result=prepared;past=[];future=[];selected=null;loadSettings();render();toast('项目已打开；未排料项目可继续核对素材')});
$('export').onclick=()=>{$('exportDialog').showModal()};
async function fetchExport(path,body,save=true,name){const native=window.pywebview?.api;if(save&&native?.export_file)return nativeResult(await native.export_file(path,body,name));const response=await fetch(path,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});if(!response.ok){const data=await response.json();throw Error(data.error||'导出失败')}const blob=await response.blob();if(save)await download(blob,name);return blob}
let exporting=false,exportJob=null;
async function checkedExport(path,name){
 if(exporting)return;exporting=true;
 const buttons=[...$('exportDialog').querySelectorAll('.export-options button')];
 const status=$('exportStatus'),bar=$('exportProgress'),cancel=$('cancelExport');
 buttons.forEach(b=>b.disabled=true);status.hidden=false;bar.value=0;
 $('exportMessage').textContent='请选择保存位置，随后将在后台生成';
 try{
  syncSettings();const native=window.pywebview?.api;
  if(path==='/api/export/jpg'&&native?.choose_export){
   const choice=await native.choose_export(name);if(choice.error)throw Error(choice.error);if(choice.cancelled)return;
   exportJob=choice.job;cancel.hidden=false;
   $('exportMessage').textContent='正在提交后台任务…';
   await new Promise(resolve=>requestAnimationFrame(()=>setTimeout(resolve,0)));
   const started=await native.start_export(exportJob,path,{project});if(started.error)throw Error(started.error);
   while(true){
    const state=await native.export_status(exportJob);bar.value=state.percent||0;$('exportMessage').textContent=state.message;
    if(state.state==='error')throw Error(state.message);
    if(state.state==='done'||state.state==='cancelled'){toast(state.message);break}
    await new Promise(resolve=>setTimeout(resolve,400));
   }
  }else{
   $('exportMessage').textContent='正在后台复核并生成文件…';
   await new Promise(resolve=>setTimeout(resolve,0));
   await fetchExport(path,{project,segmentMm:Number($('segmentMm').value)},true,name);bar.value=100;$('exportMessage').textContent='文件已生成';
  }
 }catch(error){$('exportMessage').textContent=error.message;throw error}
 finally{exporting=false;exportJob=null;cancel.hidden=true;buttons.forEach(b=>b.disabled=false)}
}
$('cancelExport').onclick=guarded(async()=>{if(exportJob){await window.pywebview.api.cancel_export(exportJob);$('exportMessage').textContent='正在取消；当前编码步骤完成后停止，不覆盖原文件'}});
$('exportJpg').onclick=guarded(()=>checkedExport('/api/export/jpg','布序生产排料-110dpi.jpg'));$('exportJpgZip').onclick=guarded(()=>checkedExport('/api/export/jpg-zip','布序分段生产JPG-110dpi.zip'));
$('exportSvg').onclick=guarded(()=>checkedExport('/api/export/svg','布序排料-1比1.svg'));$('exportZip').onclick=guarded(()=>checkedExport('/api/export/zip','布序分段生产包.zip'));$('exportCsv').onclick=guarded(()=>checkedExport('/api/export/csv','裁片坐标.csv'));
$('exportPng').onclick=guarded(async()=>{const blob=await fetchExport('/api/export/svg',{project},false),url=URL.createObjectURL(blob);try{const image=new Image();await new Promise((resolve,reject)=>{image.onload=resolve;image.onerror=()=>reject(Error('预览渲染失败'));image.src=url});const s=result?.stats|| (await api('/api/validate',project)).stats;let w=1600,h=Math.ceil(w*s.length/project.settings.width);if(h>8000){w=Math.max(1,Math.floor(w*8000/h));h=8000}const canvas=document.createElement('canvas');canvas.width=w;canvas.height=h;const context=canvas.getContext('2d');context.fillStyle='#fff';context.fillRect(0,0,w,h);context.drawImage(image,0,0,w,h);context.fillStyle='#b54732';context.font=`${Math.max(9,w/70)}px sans-serif`;context.fillText('低分辨率预览 · 非生产比例',10,Math.max(20,w/50));const output=await new Promise(resolve=>canvas.toBlob(resolve,'image/png'));if(!output)throw Error('PNG生成失败');await download(output,'排料预览-非生产.png')}finally{URL.revokeObjectURL(url)}});
window.addEventListener('beforeunload',e=>{if(project.pieces.length){e.preventDefault();e.returnValue=''}});
syncSettings();render();api('/api/health').catch(()=>toast('本地服务未连接，请按README启动'));


let bindingRequests=[],bindingMatch=null,bindingBusy=false,bindingRevision=0;
function bindingApi(){const native=window.pywebview?.api;if(!native?.choose_binding_folder)throw Error('请使用新版Windows EXE，通过本机文件夹选择器拉取包边条');return native}
function bindingSources(){
 const placed=new Set(project.placements.map(p=>p.pieceId));const groups=new Map();
 for(const p of project.pieces){if(!placed.has(p.id)||p.role==='binding-strip'||p.bindingFor)continue;
  const id=p.sourceGroup||p.id;if(!groups.has(id))groups.set(id,{id,filename:p.filename||p.name});
 }
 return [...groups.values()];
}
function bindingControls(){
 const complete=!!bindingMatch&&bindingMatch.matches.length===bindingRequests.length&&!bindingMatch.missing.length&&!bindingMatch.ambiguous.length;
 $('bindingChoose').disabled=bindingBusy;$('bindingRule').disabled=bindingBusy;$('bindingRecursive').disabled=bindingBusy;
 $('bindingCopy').disabled=bindingBusy||!complete;

}
function showBindingResult(){
 const list=$('bindingResults');list.replaceChildren();if(!bindingMatch){bindingControls();return}
 const m=bindingMatch;$('bindingSummary').textContent=`${m.requested}个已排原图文件：匹配${m.matches.length}张，未找到${m.missing.length}张，重名待处理${m.ambiguous.length}张`;
 for(const match of m.matches){const row=document.createElement('p');row.textContent=`✓ ${match.filename} → ${match.file.relativePath}`;list.append(row)}
 for(const missing of m.missing){const row=document.createElement('p');row.className='error-line';row.textContent=`未找到：${missing.filename}，请检查同款号文件夹内的同款号“包边条”图片`;list.append(row)}
 for(const ambiguous of m.ambiguous){const row=document.createElement('p');row.className='error-line';row.textContent=`有多个候选：${ambiguous.filename} → ${ambiguous.candidates.map(f=>f.relativePath).join('、')}`;list.append(row)}
 bindingControls();
}
async function refreshBinding(){
 const generation=++bindingRevision;bindingMatch=null;bindingControls();
 $('bindingExample').textContent=$('bindingRule').value==='style-folder'?'示例：YQ-TJGG-44-L-1.jpg → YQ-TJGG-44 文件夹 → YQ-TJGG-44-包边条.jpg。':$('bindingRule').value==='style-prefix'?'示例：YQ-TJGG-44-L-1.jpg → YQ-TJGG-44-包边条.jpg；每个已排原图各复制一张。':$('bindingRule').value==='exact'?'示例：款号-L-1.jpg → 款号-L-1包边条.jpg；可有横线、下划线或空格分隔。':'示例：款号-L-1.jpg、款号-L-2.jpg → 款号-L包边条.jpg；每个原图各取一张。';
 if(!$('bindingFolder').dataset.selected)return;
 const reply=await bindingApi().match_binding_files(bindingRequests,$('bindingRule').value);if(generation!==bindingRevision)return;if(reply.error)throw Error(reply.error);
 bindingMatch=reply;showBindingResult();
}
$('binding').onclick=guarded(async()=>{
 if(busy||bindingBusy)return;bindingRequests=bindingSources();if(!bindingRequests.length)throw Error('请先完成原图排料，再按已排文件匹配包边条');
 bindingMatch=null;$('bindingSummary').textContent=`当前已排${bindingRequests.length}个原始图片文件`;
 $('bindingResults').replaceChildren();$('bindingDialog').showModal();bindingControls();await refreshBinding();
});
$('bindingChoose').onclick=guarded(async()=>{
 if(bindingBusy)return;bindingBusy=true;bindingControls();
 try{const reply=await bindingApi().choose_binding_folder($('bindingRecursive').checked);if(reply.error)throw Error(reply.error);if(reply.cancelled)return;
  $('bindingFolder').textContent=`${reply.folder} · 找到${reply.files.length}个“包边条”图片文件`;$('bindingFolder').dataset.selected='yes';await refreshBinding();
 }finally{bindingBusy=false;bindingControls()}
});
$('bindingRule').onchange=guarded(refreshBinding);
$('bindingRecursive').onchange=()=>{delete $('bindingFolder').dataset.selected;bindingMatch=null;$('bindingFolder').textContent='扫描范围已改变，请重新选择文件夹';$('bindingResults').replaceChildren();bindingControls()};
$('bindingCopy').onclick=guarded(async()=>{
 if(bindingBusy)return;bindingBusy=true;bindingControls();$('bindingSummary').textContent='请选择输出文件夹，随后复制对应原图…';
 try{const reply=await bindingApi().copy_binding_files(bindingRequests,$('bindingRule').value);if(reply.error)throw Error(reply.error);
  if(reply.cancelled){showBindingResult();toast('已取消复制');return}
  $('bindingSummary').textContent=`已复制${reply.count}张包边条及对应清单：${reply.folder}`;toast(`已拉取${reply.count}张包边条，当前排料未改变`);
 }finally{bindingBusy=false;bindingControls()}
});
