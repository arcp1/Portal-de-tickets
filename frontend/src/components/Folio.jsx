import React, { useCallback, useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Copy, Check } from 'lucide-react';
import { copiarTexto } from '../lib/portapapeles';

/**
 * Un folio que se copia al pulsarlo.
 *
 * **Por qué.** Un folio es un identificador que sale del portal: se pega en
 * un correo al proveedor, en un mensaje al jefe de línea, en el parte de
 * turno. Hasta ahora había que seleccionarlo con el ratón —dieciocho
 * caracteres con guiones, sin pasarse de largo— y eso se hace decenas de
 * veces al día. Un clic lo resuelve.
 *
 * **El aviso solo aparece si copió de verdad.** `copiarTexto`
 * devuelve si lo consiguió, y aquí se distingue: enseñar "Copiado" cuando el
 * portapapeles quedó vacío es peor que no ofrecer el botón, porque la persona
 * se va convencida y se entera al pegar.
 */

/** Gestiona el "copiado / no se pudo" y su vuelta al estado normal. */
function useCopiar(texto) {
  const [estado, setEstado] = useState(null);   // null | 'ok' | 'error'
  const reloj = useRef(null);

  // Si el componente se va mientras el aviso está puesto —al navegar a otra
  // pantalla, por ejemplo— el temporizador intentaría escribir en algo que ya
  // no existe.
  useEffect(() => () => clearTimeout(reloj.current), []);

  const copiar = useCallback(async () => {
    const bien = await copiarTexto(texto);
    setEstado(bien ? 'ok' : 'error');
    clearTimeout(reloj.current);
    reloj.current = setTimeout(() => setEstado(null), bien ? 1500 : 2600);
  }, [texto]);

  return [estado, copiar];
}

/** El botón suelto, para ponerlo al lado de un título que ya lleva el folio. */
export function BotonCopiar({ texto, etiqueta }) {
  const { t } = useTranslation();
  const [estado, copiar] = useCopiar(texto);
  return (
    <button
      type="button"
      className={`boton-copiar${estado ? ' boton-copiar--' + estado : ''}`}
      onClick={copiar}
      title={etiqueta || t('comun.copiar')}
      aria-label={etiqueta || t('comun.copiar')}
    >
      {estado === 'ok' ? <Check size={15} /> : <Copy size={15} />}
      {/* El aviso va en un `aria-live` y no solo en el icono: un cambio de
          icono no lo anuncia nadie. Se pinta fuera de pantalla porque a la
          vista ya lo dice la marca de verificación. */}
      <span className="solo-lectores" aria-live="polite">
        {estado === 'ok' ? t('comun.copiado') : estado === 'error' ? t('comun.no_se_pudo_copiar') : ''}
      </span>
    </button>
  );
}

/** La pastilla con el folio dentro, que es ella misma el botón. */
export default function Folio({ codigo, className = '', style }) {
  const { t } = useTranslation();
  const [estado, copiar] = useCopiar(codigo);
  if (!codigo) return null;

  return (
    <button
      type="button"
      className={`folio${estado ? ' folio--' + estado : ''} ${className}`.trim()}
      style={style}
      onClick={(e) => {
        // Los folios viven dentro de tarjetas que navegan al pulsarlas. Sin
        // esto, copiar el folio te sacaba de la lista a la ficha del ticket.
        e.stopPropagation();
        e.preventDefault();
        copiar();
      }}
      title={t('comun.copiar_folio', { folio: codigo })}
    >
      <span className="folio-codigo">{codigo}</span>
      {estado === 'ok'
        ? <Check size={13} className="folio-icono" aria-hidden="true" />
        : <Copy size={13} className="folio-icono" aria-hidden="true" />}
      <span className="solo-lectores" aria-live="polite">
        {estado === 'ok' ? t('comun.copiado') : estado === 'error' ? t('comun.no_se_pudo_copiar') : ''}
      </span>
    </button>
  );
}
