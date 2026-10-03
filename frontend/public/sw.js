/*
 * Service Worker del portal: lo justo para instalarlo y para que abra sin red.
 *
 * Reglas, en orden de importancia:
 *
 *  1. **Nunca /api.** Son datos con sesión —tickets, personas, el token— y
 *     no tienen nada que hacer en una caché que sobrevive al cierre de sesión
 *     y que comparte quien use la misma terminal después.
 *  2. **La página, de la red primero.** Tras un despliegue, `index.html`
 *     apunta a los JS nuevos; servirlo de caché dejaría a la gente con la
 *     versión vieja. Solo si no hay red se usa la copia guardada, para que el
 *     portal abra y diga "sin conexión" en vez del dinosaurio del navegador.
 *  3. **/assets, de la caché.** Llevan el hash en el nombre: un archivo con
 *     ese nombre no cambia nunca.
 *
 * Cambiar VERSION borra las cachés anteriores al activarse.
 */
const VERSION = 'portal-2026-10-02';
const BASICOS = ['/', '/index.html', '/manifest.webmanifest', '/pwa/icono-192.png', '/marca/cgr.png'];

self.addEventListener('install', (evento) => {
  evento.waitUntil(
    caches.open(VERSION)
      .then((cache) => cache.addAll(BASICOS))
      .catch(() => undefined)
      .then(() => self.skipWaiting())
  );
});

self.addEventListener('activate', (evento) => {
  evento.waitUntil(
    caches.keys()
      .then((claves) => Promise.all(claves.filter((c) => c !== VERSION).map((c) => caches.delete(c))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener('fetch', (evento) => {
  const peticion = evento.request;
  if (peticion.method !== 'GET') return;
  const url = new URL(peticion.url);
  if (url.origin !== self.location.origin) return;
  if (url.pathname.startsWith('/api/') || url.pathname === '/api') return;

  if (peticion.mode === 'navigate') {
    evento.respondWith(
      fetch(peticion)
        .then((respuesta) => {
          if (respuesta.ok) {
            const copia = respuesta.clone();
            caches.open(VERSION).then((cache) => cache.put('/index.html', copia));
          }
          return respuesta;
        })
        .catch(() => caches.match('/index.html').then((r) => r || Response.error()))
    );
    return;
  }

  if (url.pathname.startsWith('/assets/')) {
    evento.respondWith(
      caches.match(peticion).then((guardada) => guardada || fetch(peticion).then((respuesta) => {
        if (respuesta.ok) {
          const copia = respuesta.clone();
          caches.open(VERSION).then((cache) => cache.put(peticion, copia));
        }
        return respuesta;
      }))
    );
    return;
  }

  // Fuentes, marca, iconos y fondos: de la caché si está, y se refresca detrás.
  if (/^\/(fuentes|marca|pwa|fondo)\//.test(url.pathname)) {
    evento.respondWith(
      caches.open(VERSION).then((cache) => cache.match(peticion).then((guardada) => {
        const deRed = fetch(peticion).then((respuesta) => {
          if (respuesta.ok) cache.put(peticion, respuesta.clone());
          return respuesta;
        }).catch(() => guardada);
        return guardada || deRed;
      }))
    );
  }
});
