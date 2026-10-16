import {prepareArchive} from './zip.js';
const urls=new Map();let busy=false;
chrome.runtime.onMessage.addListener((message,sender,respond)=>{
 if(sender.id!==chrome.runtime.id||message.target!=='zip-offscreen')return;
 if(message.type==='release'){const url=urls.get(message.jobId);if(url)URL.revokeObjectURL(url);urls.delete(message.jobId);respond({ok:true});return}
 if(message.type!=='buildZip')return;
 if(busy){respond({ok:false,message:'已有图片包正在生成'});return}busy=true;
 (async()=>{try{const result=await prepareArchive(message.products,{onProgress:progress=>chrome.runtime.sendMessage({target:'zip-background',type:'zipProgress',progress}).catch(()=>{})});await chrome.runtime.sendMessage({target:'zip-background',type:'zipReport',report:result.report});if(!result.bytes){respond({ok:false,message:'所有图片下载失败：'+(result.report.failures[0]?.error||'请检查图片访问权限')});return}const url=URL.createObjectURL(new Blob([result.bytes],{type:'application/zip'}));urls.set(message.jobId,url);respond({ok:true,url,count:result.report.saved,failed:result.report.failed})}catch(error){respond({ok:false,message:error.message})}finally{busy=false}})();return true;
});
