import test from 'node:test';
import assert from 'node:assert/strict';
import {productLink,metric,publicProduct,mergeSnapshot,accessBarrier} from './core.mjs';
const target={id:'shop',platform:'Temu',url:'https://www.temu.com/mall.html?mall_id=123',site:'US',name:'参考店铺'};
const date='2026-10-15',now='2026-10-15T01:00:00Z';
function product(id='123',sales=5){return publicProduct({href:`https://www.temu.com/print-shirt-g-${id}.html?refer_page_name=mall`,title:'印花上衣',image:'https://img.example.com/1.jpg',text:`${sales} sold 8 reviews`},target,date)}
test('platform IDs are canonical and external tracking links are rejected',()=>{
 assert.equal(productLink('https://www.temu.com/item-g-123.html?x=1',target).productId,'123');
 assert.equal(productLink('https://evil.example/item-g-123.html',target),null);
 assert.equal(productLink('javascript:alert(1)',target),null);
 for(const [platform,url] of [['SHEIN','https://us.shein.com/Print-Top-p-12345.html?src=abc'],['LightInTheBox','https://www.lightinthebox.com/en/p/top_p12345.html?x=1'],['Pinterest','https://www.pinterest.com/pin/12345/']])assert.equal(productLink(url,{platform,url}).productId,'12345');
});
test('unknown and approximate counts never become precise sales or likes',()=>{
 assert.deepEqual(metric('4.9 stars 120 reviews','sales'),{value:null,text:''});
 assert.equal(metric('1.2K sold','sales').value,null);
 assert.equal(metric('1,000+ sold','sales').value,null);
 assert.equal(metric('1,234 sold','sales').value,1234);
 assert.equal(metric('500 saves','saves').value,500);
 assert.equal(metric('120 reviews','likes').value,null);
});
test('first successful collection creates baseline; failure preserves historical products',()=>{
 const p=product();const first=mergeSnapshot({},[{target,status:'ok',products:[p]}],date,now);
 assert.equal(first.products[0].baseline,true);assert.equal(first.products[0].sales,5);
 const failed=mergeSnapshot(first,[{target,status:'verification_required',message:'需要验证'}],'2026-10-16','2026-10-16T01:00:00Z');
 assert.deepEqual(failed.products,first.products);assert.equal(failed.targets[0].lastSuccess,now);
});
test('later discoveries are new and histories are upserted per day',()=>{
 const first=mergeSnapshot({},[{target,status:'ok',products:[product()]}],date,now);
 const next=mergeSnapshot(first,[{target,status:'ok',products:[{...product('123',8),firstSeen:'2026-10-16'},{...product('456',null),firstSeen:'2026-10-16'}]}],'2026-10-16','2026-10-16T01:00:00Z');
 assert.equal(next.products[0].firstSeen,date);assert.equal(next.products[0].history.length,2);
 assert.equal(next.products[1].baseline,false);assert.equal(next.products[1].firstSeen,'2026-10-16');
 const retry=mergeSnapshot(next,[{target,status:'ok',products:[product('123',9)]}],'2026-10-16','2026-10-16T02:00:00Z');
 assert.equal(retry.products[0].history.length,2);assert.equal(retry.products[0].history[1].sales,9);
});
test('Pinterest sales remain unknown and save and like metrics are independent',()=>{
 const pin=publicProduct({href:'https://www.pinterest.com/pin/123/',title:'wallpaper',image:'https://i.pinimg.com/image.jpg',text:'520 saves 20 likes 999 sold'},{...target,platform:'Pinterest',url:'https://www.pinterest.com/search/pins/?q=wallpaper'},date);
 assert.equal(pin.sales,null);assert.equal(pin.salesText,'');assert.equal(pin.saves,520);assert.equal(pin.likes,20);assert.equal(pin.seamless,'未核验');
});

test('SHEIN challenge routes are recognized without trying to interact with verification',()=>{
 assert.equal(accessBarrier('https://us.shein.com/risk/challenge?x=1','shop'), 'verification_required');
 assert.equal(accessBarrier('https://www.temu.com/login.html'), 'auth_required');
 assert.equal(accessBarrier('https://www.temu.com/mall.html','shirts'),null);
});
