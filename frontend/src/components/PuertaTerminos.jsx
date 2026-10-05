import React, { useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { ScrollText } from 'lucide-react';
import { useAuth } from '../context/AuthContext';
import Cargando from './Cargando';
import TextoTerminos, { useTerminosVigentes } from './TextoTerminos';

/**
 * La puerta de los Términos y Condiciones: aparece en lugar del portal
 * mientras la persona no acepte la versión vigente.
 *
 * **No es una ventana encima del portal: es lo único que hay.** App no pinta ni
 * la barra ni las rutas mientras falte la aceptación, así que no hay a dónde
 * navegar, nada que cerrar y ninguna tecla que la quite. La única otra salida
 * es cerrar la sesión. Y el servidor responde 403 a todo lo demás
 * (`terminos_pendientes`), por si alguien llama a la API directamente.
 *
 * **Hay que llegar al final del texto para poder aceptar.** Un centinela al pie
 * del documento avisa, con un IntersectionObserver sobre la caja que se
 * desplaza, cuando de verdad se vio el final: funciona igual con la rueda, el
 * dedo o el teclado. Si el texto cabe entero sin desplazarse, ya está visto.
 */
export default function PuertaTerminos() {
  const { t } = useTranslation();
  const { user, aceptarTerminos, logout } = useAuth();
  const { cargando, doc, error, recargar } = useTerminosVigentes();
  const [leido, setLeido] = useState(false);
  const [marcado, setMarcado] = useState(false);
  const [enviando, setEnviando] = useState(false);
  const [aviso, setAviso] = useState('');
  const cajaRef = useRef(null);
  const finalRef = useRef(null);

  // Cada documento nuevo —también el que llega tras un 409— se lee desde el
  // principio: lo leído de otra versión no cuenta.
  useEffect(() => {
    setLeido(false);
    setMarcado(false);
    if (!doc || !cajaRef.current || !finalRef.current) return undefined;
    cajaRef.current.scrollTop = 0;
    const observador = new IntersectionObserver(
      ([entrada]) => { if (entrada.isIntersecting) setLeido(true); },
      { root: cajaRef.current, threshold: 1 }
    );
    observador.observe(finalRef.current);
    return () => observador.disconnect();
  }, [doc]);

  // El foco, en el texto: así se puede desplazar con el teclado desde el
  // primer momento y un lector de pantalla empieza por lo que hay que leer.
  useEffect(() => { if (doc) cajaRef.current?.focus(); }, [doc]);

  const aceptar = async () => {
    if (!doc || !marcado) return;
    setEnviando(true);
    setAviso('');
    try {
      await aceptarTerminos(doc.version, doc.huella);
      // La sesión ya los trae vigentes: App deja de pintar esta puerta.
    } catch (err) {
      const estado = err.response?.status;
      const detalle = err.response?.data?.detail;
      if (estado === 409) {
        // El texto cambió mientras se leía: se trae el nuevo y se empieza de nuevo.
        setAviso(t('terminos.cambiaron'));
        recargar();
      } else {
        setAviso(typeof detalle === 'string' && detalle ? detalle : t('terminos.error_aceptar'));
      }
      setEnviando(false);
    }
  };

  return (
    <div className="terminos-puerta">
      <section
        className="terminos-panel apple-card animate-scale-in"
        role="dialog"
        aria-modal="true"
        aria-labelledby="terminos-puerta-titulo"
        aria-describedby="terminos-puerta-intro"
      >
        <header className="terminos-cabecera">
          <ScrollText size={22} aria-hidden="true" />
          <div>
            <h1 id="terminos-puerta-titulo">{t('terminos.puerta_titulo')}</h1>
            <p id="terminos-puerta-intro">
              {t('terminos.puerta_intro', { nombre: user?.nombre || '' })}
            </p>
          </div>
        </header>

        <div
          ref={cajaRef}
          className="terminos-caja"
          tabIndex={0}
          aria-label={t('terminos.caja')}
        >
          {cargando && <Cargando />}
          {!cargando && error && (
            <div className="terminos-error" role="alert">
              <p>{t('terminos.error_cargar')}</p>
              <button type="button" className="btn-secondary" onClick={recargar}>
                {t('terminos.reintentar')}
              </button>
            </div>
          )}
          {!cargando && doc && <TextoTerminos doc={doc} />}
          <div ref={finalRef} className="terminos-final" aria-hidden="true" />
        </div>

        <footer className="terminos-acciones">
          <p className="terminos-pista" aria-live="polite">
            {doc && !leido ? t('terminos.desplace') : ' '}
          </p>
          <label className={`terminos-casilla${leido && doc ? '' : ' terminos-casilla--inactiva'}`}>
            <input
              type="checkbox"
              checked={marcado}
              disabled={!leido || !doc || enviando}
              onChange={(e) => setMarcado(e.target.checked)}
            />
            <span>{t('terminos.casilla', { version: doc?.version || '' })}</span>
          </label>
          {aviso && <div className="terminos-aviso" role="alert">{aviso}</div>}
          <div className="terminos-botones">
            <button type="button" className="btn-secondary" onClick={logout} disabled={enviando}>
              {t('nav.logout')}
            </button>
            <button
              type="button"
              className="btn-primary"
              onClick={aceptar}
              disabled={!marcado || !leido || !doc || enviando}
            >
              {enviando ? t('terminos.aceptando') : t('terminos.aceptar')}
            </button>
          </div>
        </footer>
      </section>
    </div>
  );
}
