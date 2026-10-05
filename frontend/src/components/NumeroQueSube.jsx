import React, { useEffect, useRef, useState } from 'react';

/**
 * Un número que cuenta desde cero hasta su valor al aparecer.
 *
 * **Por qué.** Una cifra que ya está ahí cuando llegas no dice nada; una que
 * sube te obliga a mirarla, y en una pantalla de métricas eso es justo lo que
 * se busca. Es de los pocos adornos que además informan: el recorrido deja
 * ver la magnitud antes de leer el dígito.
 *
 * **Frenando al final**, no a velocidad constante. Una cuenta lineal parece
 * un contador de gasolinera; una que desacelera parece que la cifra se posa.
 *
 * Tres cosas que no se ven pero importan:
 *
 *   - **Se respeta `prefers-reduced-motion`**: quien pidió menos movimiento ve
 *     el número final desde el primer fotograma, no una versión rápida.
 *   - **`null` no es cero.** Si no hay dato, la pantalla muestra "—". Animar
 *     hacia cero convertiría "no lo sabemos" en "es cero", que es una
 *     afirmación distinta y lleva a decisiones equivocadas.
 *   - **Se cancela al desmontar.** Sin eso, salir de la pantalla a media
 *     cuenta deja un `requestAnimationFrame` vivo escribiendo en un
 *     componente que ya no existe.
 */
export default function NumeroQueSube({ valor, sufijo = '', duracion = 900, formatear }) {
  const sinDato = valor === null || valor === undefined;
  const [mostrado, setMostrado] = useState(sinDato ? null : 0);
  const cuadro = useRef(null);

  useEffect(() => {
    if (sinDato) { setMostrado(null); return undefined; }

    const quieto = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    // **Un cero falso es peor que no animar.**
    // `requestAnimationFrame` no se dispara en una pestaña que no está a la
    // vista. La primera versión arrancaba la cuenta igualmente, así que quien
    // abriera Métricas en una pestaña de fondo veía 0% y 0 tickets — no un
    // número a medio subir: un dato equivocado, y de los que llevan a
    // conclusiones equivocadas. Si la pantalla no está visible, se pinta el
    // valor final y ya está.
    if (quieto || document.visibilityState !== 'visible') {
      setMostrado(valor);
      return undefined;
    }

    // Los decimales se respetan: una tasa de 12.5% no puede contar de uno en
    // uno. Se mira el valor original para saber cuántos hacen falta.
    const decimales = (String(valor).split('.')[1] || '').length;
    const inicio = performance.now();

    const paso = (ahora) => {
      const t = Math.min((ahora - inicio) / duracion, 1);
      // Salida cúbica: arranca rápido y se posa.
      const suave = 1 - Math.pow(1 - t, 3);
      setMostrado(Number((valor * suave).toFixed(decimales)));
      if (t < 1) cuadro.current = requestAnimationFrame(paso);
    };
    cuadro.current = requestAnimationFrame(paso);

    // Red de seguridad: si los fotogramas se paran a mitad —la pestaña se va
    // al fondo, el sistema entra en ahorro de energía—, el número se planta en
    // el valor real en vez de quedarse congelado en una cifra intermedia.
    const rescate = setTimeout(() => setMostrado(valor), duracion + 400);

    return () => {
      cancelAnimationFrame(cuadro.current);
      clearTimeout(rescate);
    };
  }, [valor, sinDato, duracion]);

  if (mostrado === null) return '—';
  // Con `formatear`, cada fotograma se escribe como la cifra final —con la
  // coma del idioma y la unidad en pequeño—, no como un número suelto.
  if (formatear) return formatear(mostrado);
  return `${mostrado}${sufijo}`;
}
