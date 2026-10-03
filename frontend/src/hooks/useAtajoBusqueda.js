import { useEffect } from 'react';

/**
 * `/` lleva el foco a la búsqueda.
 *
 * En una cola de tickets, buscar es lo que más se repite en el día, y hasta
 * ahora costaba soltar el teclado y apuntar con el ratón. Es el atajo que usan
 * casi todas las herramientas donde se vive dentro de una lista.
 *
 * **No se roba la tecla si ya se está escribiendo.** Si el foco está en un
 * campo, un área de texto o algo editable, la barra es una barra: quien esté
 * redactando la solución de un ticket no quiere que se le vaya el cursor.
 */
export default function useAtajoBusqueda() {
  useEffect(() => {
    const alPulsar = (e) => {
      if (e.key !== '/' || e.ctrlKey || e.metaKey || e.altKey) return;
      const a = document.activeElement;
      const escribiendo = a && (
        a.tagName === 'INPUT' || a.tagName === 'TEXTAREA' || a.isContentEditable
      );
      if (escribiendo) return;
      const campo = document.querySelector('.barra-herramientas input[type="text"]');
      if (!campo) return;
      e.preventDefault();
      campo.focus();
      campo.select();
    };
    document.addEventListener('keydown', alPulsar);
    return () => document.removeEventListener('keydown', alPulsar);
  }, []);
}
