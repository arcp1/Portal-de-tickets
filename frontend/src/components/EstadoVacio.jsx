import React from 'react';
import { Inbox } from 'lucide-react';

/**
 * Lo que se enseña cuando una lista no tiene nada.
 *
 * Había cinco versiones de esto en el portal, una por pantalla: dos tarjetas
 * de 48 px con una línea de texto, una tarjeta de 60 con icono y titular, otra
 * de 48 con dos niveles de texto y, en el expediente, un párrafo suelto sin
 * caja. La misma situación contada de cinco formas.
 *
 * **Y con borde discontinuo, no con relleno.** Una tarjeta llena dice "aquí
 * hay algo"; el hueco que deja una lista vacía es justo lo contrario. El
 * trazo cortado se lee como un sitio reservado que todavía no se ha ocupado,
 * que es exactamente lo que es.
 */
export default function EstadoVacio({ icono, texto, detalle, accion }) {
  return (
    <div className="estado-vacio animate-appear">
      <span className="estado-vacio-icono" aria-hidden="true">
        {icono || <Inbox size={26} />}
      </span>
      <p className="estado-vacio-texto">{texto}</p>
      {detalle && <p className="estado-vacio-detalle">{detalle}</p>}
      {accion && <div className="estado-vacio-accion">{accion}</div>}
    </div>
  );
}
