import React from 'react';

/**
 * Tarjeta de cristal con borde eléctrico.
 *
 * Es el diseño visual de `glass-cards` extraído a un componente reutilizable.
 * De la plantilla se conservó el borde de gradiente cónico, que es lo que la
 * distingue, y se quitó todo lo que era comportamiento de página: GSAP,
 * ScrollTrigger, el `height: 100vh`, el `position: sticky` y el `top`
 * calculado según el índice.
 *
 * **El cristal ya no es suyo.** Los tres reflejos y la textura esmerilada que
 * traía la plantilla se quitaron y el cuerpo comparte regla con `.apple-card`:
 * si no, Métricas y Estado del Sistema se leían de otro material que el resto
 * del portal. Lo que queda propio es el borde.
 *
 * Con eso fuera **la tarjeta fluye como cualquier bloque**: se puede meter en
 * un grid, en un flex o suelta, y crece con su contenido. Y como GSAP servía
 * solo para el apilado al hacer scroll, no hay ninguna dependencia que
 * instalar.
 *
 * Los efectos viven en CSS y no en `style` en línea, que es como está el resto
 * del portal: así se pueden ajustar en un sitio y no en cada uso.
 *
 * @param {React.ReactNode} children  Lo que va dentro. Cualquier cosa.
 * @param {string} className          Se suma a las del componente.
 * @param {string} tono               'azul' | 'rosa' | 'neutro'. El color del
 *                                    borde; por defecto el azul de CGR.
 * @param {boolean} girando           El borde da vueltas despacio. Apagado por
 *                                    defecto: en una pantalla de trabajo, un
 *                                    borde que se mueve compite con el texto.
 * @param {string} relleno            El espacio interior. Va por variable de
 *                                    CSS y no por `style`, porque el `style`
 *                                    del componente cae en la raíz y el
 *                                    relleno tiene que aplicarse al contenido,
 *                                    por dentro de los reflejos.
 */
export default function GlassCard({
  children,
  className = '',
  tono = 'azul',
  girando = false,
  relleno,
  style,
  ...resto
}) {
  const clases = [
    'tarjeta-cristal',
    `tarjeta-cristal--${tono}`,
    girando ? 'tarjeta-cristal--girando' : '',
    className,
  ].filter(Boolean).join(' ');

  return (
    <div
      className={clases}
      style={relleno ? { ...style, '--relleno-tarjeta': relleno } : style}
      {...resto}
    >
      {/* El borde eléctrico. Va detrás del contenido y recortado a un anillo:
          ver el comentario del CSS para por qué no es un rectángulo entero. */}
      <span className="tarjeta-cristal-borde" aria-hidden="true" />

      <div className="tarjeta-cristal-cuerpo">
        <div className="tarjeta-cristal-contenido">{children}</div>
      </div>
    </div>
  );
}
