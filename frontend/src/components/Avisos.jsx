import React, { useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { AlertTriangle, CheckCircle2, X } from 'lucide-react';
import { avisar, escucharAvisos, mensajeDeError } from '../lib/avisos';

// Lo que tarda en irse cada uno. El de peligro se queda más: suele traer una
// referencia que alguien va a querer copiar para dársela a TI.
const DURACION = { peligro: 9000, atencion: 7000, exito: 4000 };
const MAXIMO = 3;

/**
 * La pila de avisos flotantes del portal. Ver `lib/avisos.js`.
 *
 * Va una sola vez, fuera de las rutas, para que un aviso sobreviva al cambio
 * de pantalla que muchas veces lo provoca.
 */
export default function Avisos() {
  const { t } = useTranslation();
  const [avisos, setAvisos] = useState([]);
  const relojes = useRef(new Map());

  const quitar = (id) => {
    clearTimeout(relojes.current.get(id));
    relojes.current.delete(id);
    setAvisos((lista) => lista.filter((a) => a.id !== id));
  };

  useEffect(() => {
    const dejar = escucharAvisos((nuevo) => {
      setAvisos((lista) => {
        const programar = (id, aviso) => {
          clearTimeout(relojes.current.get(id));
          if (aviso.fija) relojes.current.delete(id);
          else relojes.current.set(id, setTimeout(() => quitar(id), DURACION[aviso.tono] || DURACION.peligro));
        };
        // Uno con la misma clave ya a la vista: se actualiza, no se repite.
        // Texto y tono incluidos: así "volvió la conexión" sustituye a "sin
        // conexión" en vez de quedarse los dos.
        const repetido = lista.find((a) => a.clave === nuevo.clave);
        if (repetido) {
          programar(repetido.id, nuevo);
          return lista.map((a) => (a.id === repetido.id
            ? { ...a, texto: nuevo.texto, tono: nuevo.tono, fija: nuevo.fija } : a));
        }
        programar(nuevo.id, nuevo);
        return [...lista, nuevo].slice(-MAXIMO);
      });
    });

    /* **Lo que nadie atrapó.** Una promesa rechazada sin `catch` —una
       petición que falló en un sitio que no lo esperaba— antes solo dejaba
       una línea roja en la consola y la pantalla como si nada. Ahora se dice.
       No se toca lo que sí tiene su `catch`: eso nunca llega aquí. */
    const sinAtrapar = (evento) => {
      const razon = evento.reason;
      if (razon?.code === 'ERR_CANCELED') return;
      // Los cortes de red ya los avisa el cliente de la API, con su clave.
      if (razon?.isAxiosError && !razon.response) return;
      avisar(mensajeDeError(razon, t('comun.error_inesperado')), { clave: 'sin-atrapar' });
    };
    window.addEventListener('unhandledrejection', sinAtrapar);

    /* **El corte se dice cuando pasa, no cuando falla algo.** Antes la
       persona se enteraba al pulsar "Guardar" y ver el error; ahora el aviso
       sale en cuanto el equipo pierde la red, se queda mientras dure, y lo
       sustituye el de "volvió" —misma clave que el que pone el cliente de la
       API al fallar una petición—. */
    const sinRed = () => avisar(t('comun.sin_red'), { tono: 'atencion', clave: 'sin-conexion', fija: true });
    const conRed = () => avisar(t('comun.red_recuperada'), { tono: 'exito', clave: 'sin-conexion' });
    window.addEventListener('offline', sinRed);
    window.addEventListener('online', conRed);

    const vigentes = relojes.current;
    return () => {
      dejar();
      window.removeEventListener('unhandledrejection', sinAtrapar);
      window.removeEventListener('offline', sinRed);
      window.removeEventListener('online', conRed);
      vigentes.forEach(clearTimeout);
    };
  }, [t]);

  return (
    // Siempre montada, aunque esté vacía: un lector de pantalla solo anuncia
    // lo que aparece dentro de una región viva que ya existía.
    <div className="avisos-pila" role="status" aria-live="polite">
      {avisos.map((aviso) => (
        <div key={aviso.id} className={`aviso-flotante aviso-barra--${aviso.tono}`}>
          {aviso.tono === 'exito'
            ? <CheckCircle2 size={18} aria-hidden="true" />
            : <AlertTriangle size={18} aria-hidden="true" />}
          <span>{aviso.texto}</span>
          <button type="button" onClick={() => quitar(aviso.id)}
            className="aviso-flotante-cerrar" aria-label={t('comun.cerrar_aviso')}>
            <X size={16} />
          </button>
        </div>
      ))}
    </div>
  );
}
