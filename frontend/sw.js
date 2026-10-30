/* SpendFlow offline mode: opt-in read-only snapshots on this device. */
const VERSION='sf-offline-v1';
const SHELL=VERSION+'-shell', DATA=VERSION+'-private';
const ASSETS=['/','/index.html','/app.css?v=20261030-ui2','/shell.js?v=20261030-ui2','/app.js?v=20261030-ui2','/review.js?v=20261030-ui2','/pages.js?v=20261030-ui2','/people.js?v=20261030-ui2','/brand.svg','/manifest.webmanifest'];
const SAVABLE=/^\/api\/(?:config|auth\/session|categories|accounts|transactions(?:\/\d+)?|review\/next|dashboard(?:\/.*)?|analytics(?:\/.*)?|credit-cards|statements(?:\?.*)?|tags|people(?:\/.*)?|goals|budgets|recurring|rules|groups|classification-rules|exclusions|flows)(?:\/)?$/;
let enabled=false;
async function privateCache(){return caches.open(DATA);}
async function isEnabled(){const c=await privateCache();return !!(await c.match('/__spendflow_offline_enabled'));}
self.addEventListener('install',e=>e.waitUntil((async()=>{const c=await caches.open(SHELL);await Promise.all(ASSETS.map(async u=>{try{const r=await fetch(u,{cache:'reload'});if(r.ok)await c.put(u,r);}catch{}}));await self.skipWaiting();})()));
self.addEventListener('activate',e=>e.waitUntil((async()=>{for(const name of await caches.keys())if(name.startsWith('sf-offline-')&&!name.startsWith(VERSION))await caches.delete(name);enabled=await isEnabled();await self.clients.claim();})()));
self.addEventListener('message',e=>{const d=e.data||{};if(d.type==='SPENDFLOW_OFFLINE_ON')e.waitUntil((async()=>{enabled=true;await(await privateCache()).put('/__spendflow_offline_enabled',new Response('yes'));})());if(d.type==='SPENDFLOW_OFFLINE_OFF')e.waitUntil((async()=>{enabled=false;await caches.delete(DATA);})());});
self.addEventListener('fetch',e=>{
 const req=e.request,url=new URL(req.url);
 if(url.origin!==self.location.origin)return;
 if(req.method!=='GET'){
   if(url.pathname==='/api/auth/logout'||url.pathname==='/api/auth/delete-account')e.waitUntil((async()=>{enabled=false;await caches.delete(DATA);})());
   return;
 }
 if(url.pathname.startsWith('/api/')){
   // Never cache uploaded statement PDFs, attachments, or arbitrary API responses.
   if(!SAVABLE.test(url.pathname))return;
   e.respondWith((async()=>{
     const c=await privateCache();const allow=enabled||await isEnabled();
     try {
       const r=await fetch(req);
       if(allow&&r.ok&&r.headers.get('content-type')?.includes('json'))await c.put(req,r.clone());
       return r;
     }catch(err){
       if(allow){const saved=await c.match(req);if(saved)return saved;}
       return new Response(JSON.stringify({detail:'Offline: this information was not saved on this device. Connect to the internet to load it.'}),{status:503,headers:{'content-type':'application/json'}});
     }
   })());return;
 }
 if(req.mode==='navigate'){
  e.respondWith((async()=>{try{return await fetch(req)}catch{return (await caches.open(SHELL)).match('/index.html')||Response.error();}})());return;
 }
 e.respondWith((async()=>{const c=await caches.open(SHELL);return (await c.match(req))||(await fetch(req));})());
});