import React, { useEffect } from 'react';
import { createPortal } from 'react-dom';

/**
 * El velo y el centrado de cualquier ventana emergente del portal.
 *
 * **El problema que resuelve.** Un `position: fixed` no siempre se mide
 * contra la ventana: si algún ancestro tiene `transform`, `filter` o
 * `backdrop-filter`, ese ancestro pasa a ser el marco de referencia y el
 * `inset: 0` deja de significar "toda la pantalla". En este portal se daban
 * las dos condiciones a la vez: las páginas entran con `.animate-fade-in`,
 * que termina en `transform: translateY(0)` y se queda ahí por el
 * `forwards`, y las tarjetas llevan `backdrop-filter`. Resultado: el velo
 * cubría solo un trozo y la ventana aparecía centrada en el alto del
 * documento —no de la pantalla—, así que estando abajo se veía cortada por
 * arriba. Se reprodujo con el código de activación: el código quedaba fuera
 * de la vista, que es justo lo único que había que leer.
 *
 * `createPortal` la saca a `document.body`, donde no hay ancestro que la
 * atrape. Con esto deja de importar dónde se monte la ventana.
 *
 * De paso unifica el velo. Antes había tres: 0.4 con desenfoque, 0.45 sin
 * él, y dos alturas de `z-index` distintas.
 */
export default function CapaModal({ children, onCerrar, etiqueta }) {
  // Escape cierra. Es lo que espera cualquiera, y en una terminal de planta
  // con ratón malo a veces es la única salida cómoda.
  useEffect(() => {
    if (!onCerrar) return;
    const alPulsar = (e) => { if (e.key === 'Escape') onCerrar(); };
    window.addEventListener('keydown', alPulsar);
    return () => window.removeEventListener('keydown', alPulsar);
  }, [onCerrar]);

  // El fondo no se desplaza mientras hay una ventana abierta.
  useEffect(() => {
    const previo = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    return () => { document.body.style.overflow = previo; };
  }, []);

  return createPortal(
    <div
      role="dialog"
      aria-modal="true"
      aria-label={etiqueta}
      onClick={onCerrar}
      style={{
        position: 'fixed', inset: 0,
        // Sobre un fondo ya oscuro, un velo negro al 45% casi no se nota.
        // Lo que separa aquí es el desenfoque: la página de detrás se va,
        // y la ventana se lee como la única cosa enfocada de la pantalla.
        background: 'rgba(2, 4, 10, 0.62)',
        backdropFilter: 'blur(6px)',
        WebkitBackdropFilter: 'blur(6px)',
        display: 'flex', alignItems: 'center', justifyContent: 'center',
        padding: '20px', zIndex: 1000,
        overflowY: 'auto'
      }}>
      {children}
    </div>,
    document.body
  );
}
