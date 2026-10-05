import React, { useCallback, useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import api from '../api/client';
import forma from '../lib/forma';
import lista from '../lib/lista';

/**
 * Los Términos y Condiciones vigentes, tal como los sirve el backend.
 *
 * **El texto no vive en el frontend.** Lo que se acepta tiene que ser
 * exactamente lo que el servidor registra, así que se pide a `/api/terminos`
 * (público) junto con su versión y su huella, y al aceptar se devuelven las
 * dos: si el texto cambió entre medias, el servidor no registra nada.
 */
export function useTerminosVigentes() {
  const [estado, setEstado] = useState({ cargando: true, doc: null, error: false });

  const cargar = useCallback(() => {
    setEstado((previo) => ({ ...previo, cargando: true, error: false }));
    let cancelado = false;
    api.get('/terminos')
      .then((res) => {
        if (cancelado) return;
        const valido = forma(res.data, ['version', 'vigente_desde', 'titulo', 'huella', 'secciones'],
          '/terminos');
        const secciones = valido ? lista(res.data.secciones, '/terminos (secciones)') : [];
        setEstado(valido && secciones.length
          ? { cargando: false, doc: { ...res.data, secciones }, error: false }
          : { cargando: false, doc: null, error: true });
      })
      .catch(() => { if (!cancelado) setEstado({ cargando: false, doc: null, error: true }); });
    return () => { cancelado = true; };
  }, []);

  useEffect(() => cargar(), [cargar]);
  return { ...estado, recargar: cargar };
}

/**
 * "2026-10-05" → "5 de octubre de 2026", en el idioma de la pantalla.
 *
 * Una fecha sola (la vigencia) se lee a mediodía para que ningún huso la mueva
 * de día. Una fecha con hora (la aceptación, en UTC) se convierte a la hora
 * local: recortarla al día UTC pondría «6 de octubre» a quien aceptó el 5 a
 * las 19:00 en Querétaro.
 */
export function fechaLegible(iso, idioma) {
  if (!iso) return '';
  const texto = String(iso);
  const fecha = new Date(texto.length > 10 ? texto : `${texto}T12:00:00`);
  if (Number.isNaN(fecha.getTime())) return String(iso);
  return fecha.toLocaleDateString(idioma || 'es', { day: 'numeric', month: 'long', year: 'numeric' });
}

/**
 * El documento: título, versión, vigencia y cláusulas. Sin HTML de por medio:
 * cada párrafo es texto, y React lo escapa.
 */
export default function TextoTerminos({ doc }) {
  const { t, i18n } = useTranslation();
  const idioma = i18n.language || 'es';
  return (
    <article className="terminos-texto" lang="es">
      <h2 className="terminos-texto-titulo">{doc.titulo}</h2>
      <p className="terminos-texto-meta">
        {t('terminos.version', { version: doc.version })}
        {' · '}
        {t('terminos.vigentes_desde', { fecha: fechaLegible(doc.vigente_desde, idioma) })}
      </p>
      {!idioma.startsWith('es') && (
        <p className="terminos-texto-nota" lang={idioma}>{t('terminos.vinculante_es')}</p>
      )}
      {doc.secciones.map((seccion) => (
        <section key={seccion.titulo} className="terminos-clausula">
          <h3>{seccion.titulo}</h3>
          {lista(seccion.parrafos, '/terminos (párrafos)').map((parrafo, i) => (
            // El orden de los párrafos es fijo dentro de una versión.
            // eslint-disable-next-line react/no-array-index-key
            <p key={i}>{parrafo}</p>
          ))}
        </section>
      ))}
    </article>
  );
}
