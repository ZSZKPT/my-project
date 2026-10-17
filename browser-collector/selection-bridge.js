/* Local page-to-extension download bridge, restricted to the selection site. */
'use strict';
const bridgeOrigin='https://zszkpt.github.io';
if(location.origin===bridgeOrigin&&location.pathname.startsWith('/my-project/')){
 window.addEventListener('message',async event=>{
  const data=event.data;
  if(event.source!==window||event.origin!==bridgeOrigin)return;
  if(data?.type==='FEIFAN_FAVORITES_BRIDGE_PING'){window.postMessage({type:'FEIFAN_FAVORITES_BRIDGE_READY'},bridgeOrigin);return}
  if(data?.type!=='FEIFAN_DOWNLOAD_FAVORITES_ZIP'||typeof data.requestId!=='string')return;
  let response;
  try{response=await chrome.runtime.sendMessage({type:'downloadFavorites',products:data.products})}
  catch(error){response={ok:false,message:'扩展连接已失效，请刷新在线表格后重试：'+error.message}}
  window.postMessage({type:'FEIFAN_FAVORITES_DOWNLOAD_RESULT',requestId:data.requestId,...response},bridgeOrigin);
 });
 window.postMessage({type:'FEIFAN_FAVORITES_BRIDGE_READY'},bridgeOrigin);
}
