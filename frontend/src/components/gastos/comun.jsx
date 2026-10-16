import React from 'react';
import { useTranslation } from 'react-i18next';
import { Check, Clock, CircleDollarSign } from 'lucide-react';
import api, { ESPERA_SUBIDA } from '../../api/client';
import { localeDe } from '../../lib/cifras';

/**
 * Lo que comparten las tres vistas de Gastos.
 *
 * **Los colores de las categorías** son los ocho de la paleta categórica de
 * modo oscuro, validada contra la superficie de las tarjetas del portal
 * (#151822): banda de luminosidad, croma, separación para daltonismo entre
 * vecinas (peor caso ΔE 8,4) y contraste de 3:1 en las ocho. **El color sigue
 * a la categoría, no a su lugar en el ranking**: se asigna por el orden de
 * alta (id) y no por lo que gastó, así que filtrar o cambiar de año no
 * repinta nada. De la novena en adelante van juntas en gris, «Otras»: un
 * color inventado para la novena ya no se distinguiría de los demás.
 */
export const COLORES = ['#3987e5', '#d95926', '#199e70', '#c98500', '#d55181', '#008300', '#9085e9', '#e66767'];
export const GRIS_OTRAS = '#7d8590';

export function coloresDeCategorias(categorias) {
  const ids = [...(categorias || [])].map((c) => c.id).sort((a, b) => a - b);
  const mapa = new Map();
  ids.forEach((id, i) => mapa.set(id, i < COLORES.length ? COLORES[i] : GRIS_OTRAS));
  return (id) => mapa.get(id) || GRIS_OTRAS;
}

export const TIPOS_COMPROBANTE = ['cotizacion', 'orden_compra', 'factura', 'albaran', 'pago', 'pedido'];
export const ETAPAS = {
  proveedor: ['cotizacion', 'orden_compra', 'factura', 'albaran'],
  linea: ['pedido', 'factura', 'albaran'],
};

/** «2026-03-10» como fecha local: con `new Date('2026-03-10')` sería
 *  medianoche UTC, y en Querétaro eso es el día 9 a las 18:00. */
export function fechaDe(iso) {
  if (!iso) return null;
  const [a, m, d] = String(iso).slice(0, 10).split('-').map(Number);
  return new Date(a, (m || 1) - 1, d || 1);
}

export function fechaCorta(iso, idioma) {
  const f = fechaDe(iso);
  return f ? f.toLocaleDateString(localeDe(idioma), { day: '2-digit', month: 'short', year: 'numeric' }) : '—';
}

export function momento(iso, idioma) {
  if (!iso) return '—';
  return new Date(iso).toLocaleString(localeDe(idioma), {
    day: '2-digit', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit',
  });
}

export function nombreMes(mes, idioma, forma = 'long') {
  const texto = new Date(2026, mes - 1, 1).toLocaleDateString(localeDe(idioma), { month: forma });
  return texto.charAt(0).toUpperCase() + texto.slice(1).replace('.', '');
}

export function hoyIso() {
  const h = new Date();
  return `${h.getFullYear()}-${String(h.getMonth() + 1).padStart(2, '0')}-${String(h.getDate()).padStart(2, '0')}`;
}

export function tamanoLegible(n, idioma) {
  const f = (v, d) => v.toLocaleString(localeDe(idioma), { maximumFractionDigits: d });
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${f(n / 1024, 0)} KB`;
  return `${f(n / (1024 * 1024), 1)} MB`;
}

/** Pide un archivo con la sesión y lo abre o lo guarda. Los enlaces normales
 *  no llevan el token: por eso no hay `<a href>` directos a la API. */
export async function traer(ruta, nombre, { ver = false, params = {} } = {}) {
  const res = await api.get(ruta, {
    responseType: 'blob', timeout: ESPERA_SUBIDA,
    params: ver ? params : { ...params, descargar: true },
  });
  const url = URL.createObjectURL(res.data);
  if (ver) {
    window.open(url, '_blank', 'noopener,noreferrer');
  } else {
    const a = document.createElement('a');
    a.href = url;
    a.download = nombre;
    document.body.appendChild(a);
    a.click();
    a.remove();
  }
  setTimeout(() => URL.revokeObjectURL(url), 60000);
}

/** Pagado o pendiente: con icono y palabra, nunca solo con color. */
export function ChipEstado({ estado, fechaPago, idioma }) {
  const { t } = useTranslation();
  const pagado = estado === 'pagado';
  return (
    <span className={`chip-dato gasto-estado gasto-estado--${pagado ? 'pagado' : 'pendiente'}`}
      title={pagado && fechaPago ? t('gastos.pagado_el', { fecha: fechaCorta(fechaPago, idioma) }) : undefined}>
      {pagado ? <Check size={12} aria-hidden="true" /> : <Clock size={12} aria-hidden="true" />}
      {t(pagado ? 'gastos.estado_pagado' : 'gastos.estado_pendiente')}
    </span>
  );
}

/**
 * Las etapas del expediente como casillas: llena la que tiene documento,
 * vacía la que falta, y el nombre de cada una al pasar el ratón y para el
 * lector de pantalla. Con `$` si hay comprobante de pago.
 */
export function EtapasExpediente({ expediente, tipoCompra, compacta = false }) {
  const { t } = useTranslation();
  const etapas = ETAPAS[tipoCompra] || ETAPAS.proveedor;
  const faltan = new Set(expediente?.faltan || etapas);
  const etiqueta = t('gastos.expediente_resumen', { hechas: expediente?.hechas ?? 0, total: etapas.length });
  return (
    <span className={`gasto-etapas${compacta ? ' gasto-etapas--compacta' : ''}`} role="img" aria-label={etiqueta}
      title={etapas.map((e) => `${faltan.has(e) ? '○' : '●'} ${t(`gastos.tipo_${e}`)}`).join('\n')}>
      {etapas.map((e) => (
        <span key={e} className={`gasto-etapa${faltan.has(e) ? '' : ' gasto-etapa--hecha'}`} />
      ))}
      {expediente?.pago && <CircleDollarSign size={13} className="gasto-etapa-pago" aria-hidden="true" />}
    </span>
  );
}
