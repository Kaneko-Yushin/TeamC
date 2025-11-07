const CACHE = "dcn-family-v1";
const OFFLINE_URLS = [
  "/", "/family", "/family_login",
  "/static/manifest.json",
  "https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/css/bootstrap.min.css"
];

self.addEventListener("install", (e) => {
  e.waitUntil(caches.open(CACHE).then(c => c.addAll(OFFLINE_URLS)));
});
self.addEventListener("activate", (e) => {
  e.waitUntil(self.clients.claim());
});
self.addEventListener("fetch", (e) => {
  const req = e.request;
  e.respondWith(
    caches.match(req).then(res => res || fetch(req).then(r=>{
      if (req.method === "GET" && r.ok && req.url.startsWith(self.location.origin)) {
        const clone = r.clone();
        caches.open(CACHE).then(c => c.put(req, clone));
      }
      return r;
    }).catch(()=> caches.match("/family")))
  );
});
