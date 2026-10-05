import React from 'react';
import { Link } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { ArrowLeft, CheckCircle2 } from 'lucide-react';
import { useAuth } from '../context/AuthContext';
import Cargando from '../components/Cargando';
import TextoTerminos, { fechaLegible, useTerminosVigentes } from '../components/TextoTerminos';

/**
 * Los Términos y Condiciones para leerlos en cualquier momento, con o sin
 * sesión: se enlazan desde la pantalla de entrada, la activación y el menú del
 * perfil. Solo lectura; aceptarlos se hace en la puerta (PuertaTerminos).
 */
export default function Terminos() {
  const { t, i18n } = useTranslation();
  const { user } = useAuth();
  const { cargando, doc, error, recargar } = useTerminosVigentes();
  const aceptoEstos = Boolean(user && doc && user.terminos_vigentes
    && user.terminos_version === doc.version);

  return (
    <div className="terminos-pagina page-container page-container--estrecho animate-fade-in">
      <Link to={user ? '/' : '/login'} className="terminos-volver">
        <ArrowLeft size={15} aria-hidden="true" /> {t(user ? 'terminos.volver_portal' : 'terminos.volver_entrada')}
      </Link>
      <div className="apple-card terminos-pagina-tarjeta">
        {aceptoEstos && (
          <p className="terminos-aceptados">
            <CheckCircle2 size={16} aria-hidden="true" />
            {t('terminos.aceptados_el', {
              version: user.terminos_version,
              fecha: fechaLegible(user.terminos_aceptados_en, i18n.language),
            })}
          </p>
        )}
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
      </div>
    </div>
  );
}
