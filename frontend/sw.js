const VERSION='spendflow-pwa-20261030-1';
const SHELL=VERSION+'-shell';
const PUBLIC=['/','/index.html','/app.css?v=20261030-ui2','/app.js?v=20261030-ui2','/shell.js?v=20261030-ui2','/pages.js?v=20261030-ui2','/review.js?v=20261030-ui2','/people.js?v=20261030-ui2','/brand.svg','/manifest.webmanifest','/pwa.js?v=1'];
self.addEventListener('install',event=>event.waitUntil((async()=>{const cache=await caches.open(SHELL);await Promise.all(PUBLIC.map(async url=>{try{const response=await fetch(url,{cache:'reload'});if(response.ok)await cache.put(url,response);}catch{}}));await self.skipWaiting();})()));
self.addEventListener('activate',event=>event.waitUntil((async()=>{await Promise.all((await caches.keys()).filter(k=>k.startsWith('spendflow-pwa-')&&k!==SHELL).map(k=>caches.delete(k)));await self.clients.claim();})()));
self.addEventListener('fetch',event=>{
  const req=event.request;
  const url=new URL(req.url);
  if(url.origin!==self.location.origin||req.method!=='GET'||url.pathname.startsWith('/api/'))return;
  if(req.mode==='navigate'){
    event.respondWith((async()=>{try{return await fetch(req)}catch{return await (await caches.open(SHELL)).match('/index.html')||Response.error();}})());
    return;
  }
  event.respondWith((async()=>{const cached=await caches.match(req);if(cached)return cached;return fetch(req);})());
});
