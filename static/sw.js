// Deliberately no caching and no interception. Sentinel is a live-telemetry
// app - stale data would be actively misleading - and this worker exists
// only to satisfy PWA installability checks that look for a registered
// fetch listener, not to actually proxy anything. Not calling
// event.respondWith() means every request, including page navigation,
// falls straight through to the browser's own normal networking,
// completely untouched by this worker.
//
// Two separate outages already came from this worker intercepting
// navigation: an uncaught fetch() rejection surfacing as a hard "Load
// failed" page, and (with that first bug patched) a self-signed cert on
// :8443 apparently not carrying its "trust this certificate" exception
// into a fetch() made from inside a service worker's context, rendering
// this worker's own error fallback instead of the real page. Both go away
// the same way: stop touching navigation at all rather than trying to
// handle every failure mode of proxying it.
self.addEventListener('install', () => self.skipWaiting());
self.addEventListener('activate', (event) => event.waitUntil(self.clients.claim()));
self.addEventListener('fetch', () => {});
