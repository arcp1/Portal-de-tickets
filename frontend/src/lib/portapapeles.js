/**
 * Copiar al portapapeles, también sin TLS.
 *
 * **El detalle que rompe la versión ingenua.** `navigator.clipboard` solo
 * existe en un *contexto seguro*: HTTPS, o `localhost`. Este portal se sirve
 * por HTTP dentro de la red de la planta —lo dice su propia pantalla de
 * Estado del sistema—, así que en los equipos de planta ese objeto es
 * `undefined` y un `navigator.clipboard.writeText(...)` a secas lanza sin que
 * nadie lo vea: el botón parpadea, no copia nada, y quien lo usó se entera al
 * pegar.
 *
 * Por eso hay dos caminos. Se intenta el moderno cuando existe —no depende de
 * que haya selección ni de que el documento tenga foco— y si no está, o si
 * falla, se cae al antiguo: un `<textarea>` fuera de pantalla, seleccionarlo
 * y `document.execCommand('copy')`. Está marcado como obsoleto pero sigue
 * funcionando en todos los navegadores actuales, y es el único que funciona
 * sin contexto seguro.
 *
 * Devuelve `true` solo si copió de verdad, para que quien llama pueda no
 * enseñar un "copiado" que sería mentira.
 */
export async function copiarTexto(texto) {
  if (!texto) return false;

  if (navigator.clipboard?.writeText) {
    try {
      await navigator.clipboard.writeText(texto);
      return true;
    } catch {
      // Sin contexto seguro, o permiso denegado: se sigue por abajo.
    }
  }

  const area = document.createElement('textarea');
  area.value = texto;
  // `readonly` evita que en los móviles salte el teclado durante el instante
  // que el campo existe; `aria-hidden` lo saca del árbol de accesibilidad,
  // para que un lector de pantalla no anuncie un campo de texto fantasma.
  area.setAttribute('readonly', '');
  area.setAttribute('aria-hidden', 'true');
  // Fuera de la vista pero **no** `display:none` ni `visibility:hidden`: un
  // campo oculto de esas dos formas no se puede seleccionar, y sin selección
  // `execCommand('copy')` no copia nada.
  area.style.cssText = 'position:fixed;top:0;left:-9999px;opacity:0;';
  document.body.appendChild(area);

  // **De dónde venía el foco.** Seleccionar el campo temporal se lo quita a
  // quien lo tuviera, y al retirarlo se quedaría en el `body`: quien copió
  // con el teclado perdería el sitio en la página.
  const focoPrevio = document.activeElement;
  try {
    area.select();
    area.setSelectionRange(0, texto.length);
    return document.execCommand('copy');
  } catch {
    return false;
  } finally {
    document.body.removeChild(area);
    if (focoPrevio instanceof HTMLElement) focoPrevio.focus();
  }
}

/**
 * Deja seleccionado el contenido de un elemento.
 *
 * Es la salida cuando ni el camino antiguo funciona —hay navegadores y
 * políticas que bloquean `execCommand`—. Con el texto ya seleccionado a la
 * persona le queda un `Ctrl+C`, que es mucho mejor que un botón que no hace
 * nada.
 */
export function seleccionarContenido(elemento) {
  if (!elemento) return;
  const rango = document.createRange();
  rango.selectNodeContents(elemento);
  const seleccion = window.getSelection();
  seleccion.removeAllRanges();
  seleccion.addRange(rango);
}
