import React, { useCallback, useEffect, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import {
  Bell, Clock, AlarmClockOff, Star, Thermometer, WifiOff, Check, CheckCheck, ArrowRight
} from 'lucide-react';
import api from '../api/client';
import lista from '../lib/lista';
import { avisar } from '../lib/avisos';
import { useEventoPortal } from '../context/Eventos';
import { EtiquetaPlanta } from '../lib/plantas';

/**
 * La campana de TI: lo que el portal detectó solo y hay que mirar ya.
 *
 * Las alertas las abre el backend sin que nadie mire —el vigilante del SLA en
 * el worker, el receptor de sensores, una calificación baja— y avisan por el
 * flujo en vivo (evento `alertas`). Aquí se cuenta lo pendiente, se lista y
 * se atiende. Solo TI la ve: el backend no le manda ese evento a nadie más.
 *
 * Una sola fuente para la campana de la barra y la franja del tablero: un
 * almacén pequeño con suscriptores, para que dos piezas en pantalla no hagan
 * dos peticiones por cada aviso.
 */
const almacen = { resumen: { pendientes: 0, por_tipo: {} }, oyentes: new Set(), pidiendo: null };

function publicar(resumen) {
  almacen.resumen = resumen;
  almacen.oyentes.forEach((fn) => fn(resumen));
}

export function pedirResumen() {
  if (almacen.pidiendo) return almacen.pidiendo;
  almacen.pidiendo = api.get('/admin/alertas/resumen')
    .then((res) => {
      const datos = res.data && typeof res.data.pendientes === 'number'
        ? res.data : { pendientes: 0, por_tipo: {} };
      publicar(datos);
      return datos;
    })
    .catch(() => almacen.resumen)
    .finally(() => { almacen.pidiendo = null; });
  return almacen.pidiendo;
}

function useResumenAlertas(activo) {
  const [resumen, setResumen] = useState(almacen.resumen);
  useEffect(() => {
    if (!activo) return undefined;
    almacen.oyentes.add(setResumen);
    pedirResumen();
    return () => { almacen.oyentes.delete(setResumen); };
  }, [activo]);
  return resumen;
}

export const ICONOS_ALERTA = {
  sla_por_vencer: Clock,
  sla_vencido: AlarmClockOff,
  satisfaccion_baja: Star,
  iot_umbral: Thermometer,
  iot_sin_senal: WifiOff,
};
export const GRAVES = ['sla_vencido', 'iot_umbral'];

/** El texto de una alerta en el idioma de quien la lee, con los minutos al día. */
export function textoAlerta(alerta, t) {
  const d = alerta.datos || {};
  switch (alerta.tipo) {
    case 'sla_por_vencer':
    case 'sla_vencido': {
      if (d.vence_en) {
        const minutos = Math.round((new Date(d.vence_en) - Date.now()) / 60000);
        return minutos > 0
          ? t('alertas.sla_por_vencer', { folio: d.folio, minutos })
          : t('alertas.sla_vencido', { folio: d.folio, minutos: Math.abs(minutos) });
      }
      return alerta.titulo;
    }
    case 'satisfaccion_baja':
      return t('alertas.satisfaccion_baja', { folio: d.folio, estrellas: d.estrellas });
    case 'iot_umbral':
      return t('alertas.iot_umbral', {
        dispositivo: d.dispositivo,
        magnitud: t(`iot.magnitud_${d.magnitud}`, { defaultValue: d.magnitud }),
        valor: d.valor, umbral: d.umbral,
      });
    case 'iot_sin_senal':
      return t('alertas.iot_sin_senal', { dispositivo: d.dispositivo, minutos: d.minutos });
    default:
      return alerta.titulo;
  }
}

export function hace(fecha, i18n) {
  const segundos = Math.max(0, (Date.now() - new Date(fecha)) / 1000);
  const rtf = new Intl.RelativeTimeFormat(i18n.language, { numeric: 'auto' });
  if (segundos < 3600) return rtf.format(-Math.round(segundos / 60), 'minute');
  if (segundos < 86400) return rtf.format(-Math.round(segundos / 3600), 'hour');
  return rtf.format(-Math.round(segundos / 86400), 'day');
}

export default function CampanaAlertas() {
  const { t, i18n } = useTranslation();
  const navigate = useNavigate();
  const resumen = useResumenAlertas(true);
  const [abierta, setAbierta] = useState(false);
  const [alertas, setAlertas] = useState([]);
  const [cargando, setCargando] = useState(false);
  const caja = useRef(null);
  const previas = useRef(resumen.pendientes);

  const cargarLista = useCallback(async () => {
    setCargando(true);
    try {
      const res = await api.get('/admin/alertas', { params: { limite: 30 } });
      setAlertas(lista(res.data, 'las alertas'));
    } catch { /* la campana sigue con lo que tenía */ } finally {
      setCargando(false);
    }
  }, []);

  // Un aviso del flujo: se vuelve a contar y, si hay más que antes, se dice.
  useEventoPortal('alertas', async () => {
    const nuevo = await pedirResumen();
    if (nuevo.pendientes > previas.current) {
      avisar(t('alertas.nuevas', { count: nuevo.pendientes - previas.current }),
        { tono: 'atencion', clave: 'alertas-nuevas' });
    }
    previas.current = nuevo.pendientes;
    if (abierta) cargarLista();
  });

  useEffect(() => { previas.current = resumen.pendientes; }, [resumen.pendientes]);

  useEffect(() => {
    if (!abierta) return undefined;
    cargarLista();
    const fuera = (e) => { if (caja.current && !caja.current.contains(e.target)) setAbierta(false); };
    const escape = (e) => { if (e.key === 'Escape') setAbierta(false); };
    document.addEventListener('mousedown', fuera);
    document.addEventListener('keydown', escape);
    return () => {
      document.removeEventListener('mousedown', fuera);
      document.removeEventListener('keydown', escape);
    };
  }, [abierta, cargarLista]);

  const atender = async (alerta) => {
    setAlertas((a) => a.filter((x) => x.id !== alerta.id));
    try {
      await api.post(`/admin/alertas/${alerta.id}/atender`);
    } catch { cargarLista(); }
    pedirResumen();
  };

  const atenderTodas = async () => {
    try {
      await api.post('/admin/alertas/atender-todas');
      setAlertas([]);
    } catch { /* se reintenta al reabrir */ }
    pedirResumen();
  };

  const ir = (alerta) => {
    setAbierta(false);
    if (alerta.ticket_id) navigate(`/tickets/${alerta.ticket_id}`);
    else if (alerta.dispositivo_id) navigate(`/operacion/monitoreo?dispositivo=${alerta.dispositivo_id}`);
  };

  const graves = GRAVES.reduce((s, tipo) => s + (resumen.por_tipo?.[tipo] || 0), 0);
  const n = resumen.pendientes;

  return (
    <div className="campana" ref={caja}>
      <button
        type="button"
        className={`campana-boton${n ? ' campana-boton--activa' : ''}${graves ? ' campana-boton--grave' : ''}`}
        onClick={() => setAbierta((v) => !v)}
        aria-expanded={abierta}
        aria-haspopup="true"
        title={n ? t('alertas.pendientes', { count: n }) : t('alertas.ninguna')}
        aria-label={n ? t('alertas.pendientes', { count: n }) : t('alertas.ninguna')}
      >
        <Bell size={18} aria-hidden="true" />
        {n > 0 && <span className="campana-cifra" aria-hidden="true">{n > 99 ? '99+' : n}</span>}
      </button>

      {abierta && (
        <div className="campana-panel animate-scale-in" role="dialog" aria-label={t('alertas.titulo')}>
          <div className="campana-cabecera">
            <strong>{t('alertas.titulo')}</strong>
            {alertas.length > 1 && (
              <button type="button" className="boton-texto" onClick={atenderTodas}>
                <CheckCheck size={14} /> {t('alertas.atender_todas')}
              </button>
            )}
          </div>
          {cargando && alertas.length === 0 ? (
            <div className="campana-vacia">{t('alertas.cargando')}</div>
          ) : alertas.length === 0 ? (
            <div className="campana-vacia">{t('alertas.ninguna')}</div>
          ) : (
            <ul className="campana-lista">
              {alertas.map((a) => {
                const Icono = ICONOS_ALERTA[a.tipo] || Bell;
                return (
                  <li key={a.id} className={`campana-item campana-item--${a.tipo}`}>
                    <Icono size={17} className="campana-item-icono" aria-hidden="true" />
                    <div className="campana-item-cuerpo">
                      <div className="campana-item-texto">{textoAlerta(a, t)}</div>
                      <div className="campana-item-meta">
                        <EtiquetaPlanta planta={a.sitio} compacta />
                        <span>{hace(a.creado_en, i18n)}</span>
                      </div>
                      {a.detalle && <div className="campana-item-detalle">{a.detalle}</div>}
                    </div>
                    <div className="campana-item-acciones">
                      {(a.ticket_id || a.dispositivo_id) && (
                        <button type="button" className="boton-mini" onClick={() => ir(a)}
                          title={t('alertas.ver')} aria-label={t('alertas.ver')}>
                          <ArrowRight size={13} />
                        </button>
                      )}
                      <button type="button" className="boton-mini" onClick={() => atender(a)}
                        title={t('alertas.atender')} aria-label={t('alertas.atender')}>
                        <Check size={13} />
                      </button>
                    </div>
                  </li>
                );
              })}
            </ul>
          )}
        </div>
      )}
    </div>
  );
}

/** La franja del tablero de TI: cuántas hay y de qué, sin abrir la campana. */
export function FranjaAlertas() {
  const { t } = useTranslation();
  const resumen = useResumenAlertas(true);
  useEventoPortal('alertas', () => pedirResumen());
  if (!resumen.pendientes) return null;
  const partes = Object.entries(resumen.por_tipo || {})
    .filter(([, n]) => n > 0)
    .map(([tipo, n]) => t(`alertas.resumen_${tipo}`, { count: n, defaultValue: `${tipo}: ${n}` }));
  const grave = GRAVES.some((tipo) => resumen.por_tipo?.[tipo]);
  return (
    <div className={`aviso-barra ${grave ? 'aviso-barra--peligro' : 'aviso-barra--atencion'} franja-alertas`} role="status">
      <Bell size={18} aria-hidden="true" />
      <span><strong>{t('alertas.pendientes', { count: resumen.pendientes })}</strong> · {partes.join(' · ')}</span>
    </div>
  );
}
