/**
 * Avisos flotantes: lo que hay que decirle a la persona aunque la pantalla no
 * tenga dónde.
 *
 * **Por qué un emisor de módulo y no solo un contexto de React.** Quien más
 * necesita avisar es el cliente de la API (`api/client.js`) —se cayó la red,
 * caducó la sesión— y ese no es un componente: no puede usar hooks. Con esto
 * cualquiera llama a `avisar()` y el componente `<Avisos />` los pinta.
 *
 * **No sustituye al aviso de cada pantalla.** El `<Aviso>` en la página sigue
 * siendo lo que dice qué falló *ahí* ("no se pudieron cargar los tickets").
 * Esto es para lo que no tiene sitio: una acción cuyo fallo antes solo iba a
 * la consola, o algo que afecta a todo el portal a la vez.
 */

const oyentes = new Set();
let siguiente = 1;

/**
 * @param {string} texto  Lo que se le dice a la persona. Ya traducido.
 * @param {object} [opciones]
 * @param {'peligro'|'atencion'|'exito'} [opciones.tono='peligro']
 * @param {string} [opciones.clave]  Avisos con la misma clave no se apilan:
 *        un corte de red que tumba seis peticiones es un solo aviso, no seis.
 */
export function avisar(texto, { tono = 'peligro', clave, fija = false } = {}) {
  if (!texto) return;
  // `fija`: no se va sola. Para lo que sigue siendo verdad hasta que algo
  // cambie —estar sin red—; ese cambio la reemplaza mandando la misma clave.
  const aviso = { id: siguiente++, texto, tono, clave: clave || texto, fija };
  oyentes.forEach((oyente) => oyente(aviso));
}

/** Para `<Avisos />`. Devuelve la función que deja de escuchar. */
export function escucharAvisos(oyente) {
  oyentes.add(oyente);
  return () => oyentes.delete(oyente);
}

/**
 * El texto de error que trae una respuesta del API, o el de reserva.
 *
 * El backend responde siempre `{ detail, codigo }` con `detail` en texto (ver
 * `backend/app/core/errores.py`), y `api/client.js` descarta cualquier otra
 * forma. Aquí solo queda elegir entre lo que dijo el servidor y la frase de la
 * pantalla, que es lo que hacía a mano cada `catch` del portal.
 */
export function mensajeDeError(err, reserva) {
  const detalle = err?.response?.data?.detail;
  return typeof detalle === 'string' && detalle ? detalle : reserva;
}
