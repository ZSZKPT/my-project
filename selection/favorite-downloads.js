/* Personal star favorites, not platform public save counts. No server upload. */
'use strict';
let favoriteDownloadPending=null,favoriteBridgeReady=false;
function favoriteDownloadRows(){return state.products.filter(p=>p.favorite===true&&!p.demo&&(!selected.size||selected.has(p.id)))}
function finishFavoriteDownload(message){clearTimeout(favoriteDownloadPending?.timer);favoriteDownloadPending=null;$('#downloadFavoritesBtn').disabled=false;toast(message)}
window.addEventListener('message',event=>{
 if(event.source!==window||event.origin!==location.origin)return;
 if(event.data?.type==='FEIFAN_FAVORITES_BRIDGE_READY'){favoriteBridgeReady=true;$('#favoriteDownloadStatus').textContent='采集扩展已连接 · 默认将全部个人收藏打成一个ZIP；勾选时仅打包所选收藏';return}
 if(event.data?.type!=='FEIFAN_FAVORITES_DOWNLOAD_RESULT'||!favoriteDownloadPending||event.data.requestId!==favoriteDownloadPending.id)return;
 finishFavoriteDownload(event.data.message||'扩展未返回下载结果，请查看Chrome下载记录');
});
$('#downloadFavoritesBtn').onclick=()=>{
 const rows=favoriteDownloadRows();if(!rows.length)return toast(selected.size?'所选记录中没有已收藏的原图；请先点击★收藏':'请先在商品图片上点击★收藏；示例插画不提供原图下载');
 const downloadable=rows.filter(p=>/^https:\/\//.test(p.image||''));if(!downloadable.length)return toast('这些收藏没有有效的HTTPS原图链接，请重新采集');
 if(new Set(downloadable.map(p=>p.image)).size>200)return toast('每包最多200张，请勾选部分已收藏图片分批下载');
 if(!favoriteBridgeReady)return toast('请使用Chrome，下载/更新采集扩展1.6.0后刷新本页；安装入口在下方说明中');
 const id=crypto.randomUUID();$('#downloadFavoritesBtn').disabled=true;
 favoriteDownloadPending={id,timer:setTimeout(()=>finishFavoriteDownload('未连接到扩展或下载仍在排队。请安装/更新采集扩展1.6.0并刷新本页；已安装时可在扩展中点击“收藏图片打包 ZIP”，或查看Chrome下载记录'),60000)};
 window.postMessage({type:'FEIFAN_DOWNLOAD_FAVORITES_ZIP',requestId:id,products:rows.map(p=>({platform:p.platform,productId:p.productId,image:p.image,favorite:true,demo:false}))},location.origin);
 toast(`正在请求打包${downloadable.length}条收藏原图为一个ZIP；完成情况请查看Chrome下载记录`);
};

window.postMessage({type:'FEIFAN_FAVORITES_BRIDGE_PING'},location.origin);
