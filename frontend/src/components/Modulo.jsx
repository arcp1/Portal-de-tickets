import React from 'react';
import { Link, useLocation } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { useAuth } from '../context/AuthContext';
import { modulosDe, pestanaActiva } from '../lib/navegacion';

/**
 * Las pestañas de un módulo, encima de la pantalla que se está viendo.
 *
 * **Son enlaces y no botones con estado.** Cada pestaña tiene su ruta: se
 * puede volver atrás, abrir en otra pestaña del navegador y mandar el enlace
 * a un compañero. Las pantallas de debajo no saben que viven en un módulo —
 * siguen con su título y su cabecera—, así que moverlas de módulo es cambiar
 * una línea en `lib/navegacion`.
 *
 * Con una sola pestaña no se dibuja nada: una barra con una opción no ayuda
 * a nadie (la planta, en Activos y en Documentos).
 */
export default function Modulo({ id, children }) {
  const { t } = useTranslation();
  const { user } = useAuth();
  const { pathname } = useLocation();
  const modulo = modulosDe(t, user?.rol === 'admin')[id];

  if (!modulo || modulo.pestanas.length < 2) return children;
  const activa = pestanaActiva(modulo.pestanas, pathname);

  return (
    <>
      <nav className="page-container modulo-barra" aria-label={modulo.texto}>
        <span className="modulo-nombre">{modulo.texto}</span>
        <div className="filtros-estado modulo-pestanas">
          {modulo.pestanas.map((p) => {
            const es = activa?.ruta === p.ruta;
            return (
              <Link
                viewTransition
                key={p.ruta}
                to={p.ruta}
                className={`chip-filtro chip-filtro--pestana${es ? ' chip-filtro--activo' : ''}`}
                aria-current={es ? 'page' : undefined}
              >
                {p.icono}
                {p.texto}
              </Link>
            );
          })}
        </div>
      </nav>
      {children}
    </>
  );
}
