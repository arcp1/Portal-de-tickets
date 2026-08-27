import React from 'react';
import { useTranslation } from 'react-i18next';

/**
 * Estados de carga.
 *
 * Se prefiere el esqueleto sobre el spinner: ocupa el mismo lugar que el
 * contenido real, así la página no salta cuando llegan los datos.
 */

export const Esqueleto = ({ alto = '20px', ancho = '100%', style = {} }) => (
  <div className="esqueleto" style={{ height: alto, width: ancho, ...style }} />
);

/** Esqueleto con forma de tarjeta de ticket. */
export const EsqueletoTarjeta = () => (
  <div
    className="apple-card"
    style={{ padding: '20px', display: 'flex', flexDirection: 'column', gap: '12px' }}
  >
    <div style={{ display: 'flex', justifyContent: 'space-between', gap: '16px' }}>
      <Esqueleto alto="18px" ancho="140px" />
      <Esqueleto alto="22px" ancho="90px" style={{ borderRadius: '9999px' }} />
    </div>
    <Esqueleto alto="14px" ancho="85%" />
    <Esqueleto alto="14px" ancho="60%" />
  </div>
);

/** Varias tarjetas, para listas. */
export const EsqueletoLista = ({ filas = 4 }) => (
  <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
    {Array.from({ length: filas }).map((_, i) => (
      <EsqueletoTarjeta key={i} />
    ))}
  </div>
);

/** Pantalla completa. Se usa mientras se resuelve la sesión. */
const Cargando = ({ mensaje }) => {
  const { t } = useTranslation();

  return (
    <div
      className="animate-appear"
      style={{
        minHeight: '60vh',
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        justifyContent: 'center',
        gap: '18px',
        color: 'var(--text-muted)'
      }}
    >
      <div style={{ width: '160px' }}>
        <div className="progreso-indeterminado" />
      </div>
      <div style={{ fontSize: '0.95rem' }}>{mensaje || t('comun.cargando')}</div>
    </div>
  );
};

export default Cargando;
