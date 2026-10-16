// Serialized into the current tab; requires no external variables.
export function advanceDocument(platform,mode='auto'){
 if(mode!=='scroll'&&platform!=='Pinterest'){
  const selectors='a[rel="next"],button[rel="next"],[aria-label="Next page" i],[aria-label="Next" i],[aria-label="下一页"],[title="下一页"],[data-testid="pagination-next"],[class*="pagination"] a,[class*="pagination"] button,[class*="Pagination"] a,[class*="Pagination"] button,nav[aria-label*="pagination" i] a,nav[aria-label*="pagination" i] button';
  const next=[...document.querySelectorAll(selectors)].find(el=>{if(!el.getClientRects().length||el.disabled||el.getAttribute('aria-disabled')==='true'||el.closest('.disabled,[aria-disabled="true"],[disabled],.is-disabled'))return false;const label=(el.getAttribute('aria-label')||el.getAttribute('title')||el.innerText||'').trim();if(el.getAttribute('rel')!=='next'&&el.getAttribute('data-testid')!=='pagination-next'&&!/^(next(?: page)?|下一页|下页|›|»|>)$/i.test(label))return false;if(el.tagName==='A'){try{if(new URL(el.href,location.href).origin!==location.origin)return false}catch{return false}}return true});
  if(next){setTimeout(()=>next.click(),100);return 'next'}
 }
 if(mode==='next')return 'no_next';window.scrollBy(0,Math.max(700,window.innerHeight*.85));return 'scroll';
}
