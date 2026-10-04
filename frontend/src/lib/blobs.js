import api from '../api/client';

/**
 * Las imágenes que viven detrás del token, descargadas una sola vez.
 *
 * **Por qué.** `ImagenApi` descargaba la imagen cada vez que se montaba, y un
 * ticket se vuelve a montar a menudo: el aviso en vivo cuando TI lo mueve, el
 * cierre, abrir el visor. Medido en la prueba de QA del 2026-10-03: la foto de
 * 6,8 MB de un ticket se bajó tres veces y la captura de la solución, dos, para
 * ver una sola pantalla. En el Wi-Fi de planta eso son segundos y megas que
 * nadie pidió.
 *
 * **Seguro por persona.** La clave lleva la cuenta, y `olvidarTodo()` —que
 * llama el cierre de sesión— vacía el caché: quien entre después en la misma
 * pestaña no puede recibir de aquí una imagen que el servidor le negaría.
 *
 * **Con límites.** Las rutas de imagen no cambian de contenido (una imagen
 * nueva es un id nuevo), pero aun así cada entrada caduca a los 15 minutos, y
 * el total se queda en 80 MB: al pasarse se suelta lo que lleva más tiempo sin
 * usarse. Las URL `blob:` son del caché: quien las usa no las revoca.
 */
const MAX_BYTES = 80 * 1024 * 1024;
const VIDA_MS = 15 * 60 * 1000;

// clave → { promesa, url, bytes, creada, usada }
const entradas = new Map();
let total = 0;

function cuentaActual() {
  try {
    return JSON.parse(localStorage.getItem('portal_tickets_user') || 'null')?.id ?? 'anonimo';
  } catch {
    return 'anonimo';
  }
}

function soltar(clave) {
  const e = entradas.get(clave);
  if (!e) return;
  entradas.delete(clave);
  if (e.url) URL.revokeObjectURL(e.url);
  total -= e.bytes || 0;
}

function hacerSitio() {
  if (total <= MAX_BYTES) return;
  const porUso = [...entradas.entries()].filter(([, e]) => e.url).sort((a, b) => a[1].usada - b[1].usada);
  for (const [clave] of porUso) {
    if (total <= MAX_BYTES) break;
    soltar(clave);
  }
}

/** La URL `blob:` de una ruta protegida de la API. Una descarga por imagen. */
export function urlDe(ruta) {
  const clave = `${cuentaActual()}|${ruta}`;
  const ahora = Date.now();
  const previa = entradas.get(clave);
  if (previa && ahora - previa.creada < VIDA_MS) {
    previa.usada = ahora;
    return previa.promesa;
  }
  if (previa) soltar(clave);

  const entrada = { url: null, bytes: 0, creada: ahora, usada: ahora };
  entrada.promesa = api.get(ruta, { responseType: 'blob' })
    .then((res) => {
      // Si mientras tanto se cerró sesión, no se guarda nada.
      if (entradas.get(clave) !== entrada) return URL.createObjectURL(res.data);
      entrada.url = URL.createObjectURL(res.data);
      entrada.bytes = res.data.size || 0;
      total += entrada.bytes;
      hacerSitio();
      return entrada.url;
    })
    .catch((err) => {
      // Un fallo no se recuerda: el siguiente intento vuelve a pedir.
      if (entradas.get(clave) === entrada) entradas.delete(clave);
      throw err;
    });
  entradas.set(clave, entrada);
  return entrada.promesa;
}

/** Al cerrar sesión: nada de lo descargado sobrevive a la cuenta que lo pidió. */
export function olvidarTodo() {
  [...entradas.keys()].forEach(soltar);
  total = 0;
}
