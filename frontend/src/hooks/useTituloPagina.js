import { useEffect } from 'react';
import { useLocation } from 'react-router-dom';
import { useTranslation } from 'react-i18next';

/**
 * El título de la pestaña, por sección.
 *
 * Las quince pantallas del portal decían lo mismo: "Portal de Tickets TI — CGR
 * de México". Con dos pestañas abiertas —lo normal cuando se atiende un ticket
 * con el inventario al lado— no había forma de distinguirlas, y el historial
 * del navegador quedaba como una lista de entradas idénticas.
 *
 * **Va en un solo sitio y no en cada página.** Repartirlo serían quince
 * `useEffect` que hay que acordarse de añadir en la dieciseisava; aquí es una
 * tabla junto al enrutador, que es donde ya vive el mapa de rutas.
 *
 * Depende del idioma, así que se recalcula al cambiarlo: si no, quien pasa a
 * inglés se queda con la pestaña en castellano hasta recargar.
 */
const TITULOS = {
  '/': 'nav.dashboard',
  '/new-ticket': 'nav.new_ticket',
  '/inventory': 'nav.inventory',
  '/expediente': 'nav.expediente',
  '/resguardos': 'nav.resguardos',
  '/usuarios': 'nav.usuarios',
  '/importar': 'nav.importar',
  '/estado': 'nav.estado',
  '/soluciones': 'nav.soluciones',
  '/documentacion': 'nav.documentacion',
  '/rules': 'nav.rules',
  '/temas': 'nav.temas',
  '/metricas': 'nav.metricas',
  '/monitoreo': 'nav.monitoreo',
  '/plantas': 'nav.plantas',
  '/login': 'auth.title',
  '/activar': 'activar.titulo_pestana',
};

const BASE = 'Portal de Tickets TI';

export default function useTituloPagina() {
  const { pathname } = useLocation();
  const { t, i18n } = useTranslation();

  useEffect(() => {
    // El detalle de un ticket lleva su número, que es lo que de verdad
    // distingue una pestaña de otra cuando hay tres abiertas.
    const detalle = pathname.match(/^\/tickets\/(\d+)$/);
    const clave = TITULOS[pathname];
    const seccion = detalle
      ? `#${detalle[1]}`
      : clave
        ? t(clave, { defaultValue: '' })
        : '';
    // La puerta se llama igual que el portal, así que sin esto la pestaña
    // decía "Portal de Tickets TI · Portal de Tickets TI".
    document.title = seccion && seccion !== BASE ? `${seccion} · ${BASE}` : BASE;
  }, [pathname, t, i18n.language]);
}
