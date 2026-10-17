/* Personal star favorites, not platform public save counts. No server upload. */
'use strict';
let favoriteDownloadPending=null,favoriteBridgeReady=false;
function favoriteDownloadRows(){return state.products.filter(p=>p.favorite===true&&!p.demo&&(!selected.size||selected.has(p.id)))}
function finishFavoriteDownload(message){clearTimeout(favoriteDownloadPending?.timer);favoriteDownloadPending=null;$('#downloadFavoritesBtn').disabled=false;toast(message)}
window.addEventListener('message',event=>{
 if(event.source!==window||event.origin!==location.origin)return;
 if(event.data?.type==='FEIFAN_FAVORITES_BRIDGE_READY'){favoriteBridgeReady=true;$('#favoriteDownloadStatus').textContent='采集扩展已连接 · 默认下载全部个人收藏；勾选记录时只下载其中的已收藏原图';return}
 if(event.data?.type!=='FEIFAN_FAVORITES_DOWNLOAD_RESULT'||!favoriteDownloadPending||event.data.requestId!==favoriteDownloadPending.id)return;
 finishFavoriteDownload(event.data.message||'扩展未返回下载结果，请查看Chrome下载记录');
});
$('#downloadFavoritesBtn').onclick=()=>{
 const rows=favoriteDownloadRows();if(!rows.length)return toast(selected.size?'所选记录中没有已收藏的原图；请先点击★收藏':'请先在商品图片上点击★收藏；示例插画不提供原图下载');
 const downloadable=rows.filter(p=>/^https:\/\//.test(p.image||''));if(!downloadable.length)return toast('这些收藏没有有效的HTTPS原图链接，请重新采集');
 if(downloadable.length>1000)return toast('单次最多1000张，请勾选部分已收藏图片分批下载');
 if(!favoriteBridgeReady)return toast('请使用Chrome，下载/更新采集扩展1.5.0后刷新本页；安装入口在下方说明中');
 const id=crypto.randomUUID();$('#downloadFavoritesBtn').disabled=true;
 favoriteDownloadPending={id,timer:setTimeout(()=>finishFavoriteDownload('未连接到扩展或下载仍在排队。请安装/更新采集扩展1.5.0并刷新本页；已安装时可在扩展中点击“下载已收藏图片”，或查看Chrome下载记录'),60000)};
 window.postMessage({type:'FEIFAN_DOWNLOAD_FAVORITES',requestId:id,products:rows.map(p=>({platform:p.platform,productId:p.productId,image:p.image,favorite:true,demo:false}))},location.origin);
 toast(`正在请求下载${downloadable.length}条收藏原图；完成情况请查看Chrome下载记录`);
};

window.postMessage({type:'FEIFAN_FAVORITES_BRIDGE_PING'},location.origin);
