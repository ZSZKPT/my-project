import test from 'node:test';
import assert from 'node:assert/strict';
import {execFileSync} from 'node:child_process';
import {mkdtempSync,writeFileSync,rmSync} from 'node:fs';
import {tmpdir} from 'node:os';
import path from 'node:path';
import {buildZip,crc32,prepareArchive} from '../browser-collector/zip.js';
const png=new Uint8Array([137,80,78,71,13,10,26,10,0,1,2,3]);
test('standard ZIP is readable by Python zipfile including UTF-8 filenames and CRC',()=>{
 assert.equal(crc32(new TextEncoder().encode('123456789')),0xcbf43926);
 const dir=mkdtempSync(path.join(tmpdir(),'feifan-zip-'));try{const file=path.join(dir,'test.zip');writeFileSync(file,buildZip([{name:'images/test.png',data:png},{name:'图片清单.json',data:'{"saved":1}'}]));
 const output=execFileSync('python3',['-c','import sys,zipfile,json; z=zipfile.ZipFile(sys.argv[1]); assert z.testzip() is None; assert z.read("images/test.png")[:8]==bytes([137,80,78,71,13,10,26,10]); assert json.loads(z.read("图片清单.json"))["saved"]==1; print("OK")',file],{encoding:'utf8'});assert.match(output,/OK/)}finally{rmSync(dir,{recursive:true,force:true})}
});
test('partial failures are explained, duplicate URLs deduplicated and returned bytes use verified image type',async()=>{
 const p={platform:'Pinterest',productId:'123',title:'home pin',image:'https://i.pinimg.com/good',url:'https://www.pinterest.com/pin/123/'};
 const result=await prepareArchive([p,p,{...p,productId:'456',image:'https://i.pinimg.com/denied'}],{fetchImpl:async url=>url.endsWith('denied')?new Response('',{status:403}):new Response(png,{headers:{'Content-Type':'image/png'}})});
 assert.equal(result.report.requested,2);assert.equal(result.report.saved,1);assert.equal(result.report.failed,1);assert.match(result.report.images[0].file,/\.png$/);assert.match(result.report.failures[0].error,/403/);assert.ok(result.bytes.length>png.length);
});
test('HTML access denial is not included as a fake image; all failed requests do not produce an empty success ZIP',async()=>{
 const result=await prepareArchive([{image:'https://example.com/image'}],{fetchImpl:async()=>new Response('<html>Sign in</html>',{headers:{'Content-Type':'text/html'}})});
 assert.equal(result.bytes,null);assert.equal(result.report.saved,0);assert.match(result.report.failures[0].error,/登录页/);
});
test('package limits and unsafe paths are rejected before writing',async()=>{
 assert.throws(()=>buildZip([{name:'../unsafe',data:png}]),/文件名/);
 await assert.rejects(()=>prepareArchive(Array.from({length:201},(_,i)=>({image:'https://example.com/'+i}))),/200/);
});
