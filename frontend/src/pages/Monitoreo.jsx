import React, { useCallback, useEffect, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import {
  Cpu, Thermometer, Droplets, Wind, Wifi, WifiOff, Pencil, Trash2, X, Check, Info, AlertTriangle
} from 'lucide-react';
import api from '../api/client';
import lista from '../lib/lista';
import { avisar, mensajeDeError } from '../lib/avisos';
import { useEventoPortal } from '../context/Eventos';
import { usePlantas, SelectorPlanta, EtiquetaPlanta } from '../lib/plantas';
import GraficaLinea from '../components/GraficaLinea';
import GlassCard from '../components/GlassCard';
import EstadoVacio from '../components/EstadoVacio';
import { EsqueletoLista } from '../components/Cargando';
import CapaModal from '../components/CapaModal';
import Confirmacion from '../components/Confirmacion';
import Formulario from '../components/Formulario';
import Aviso from '../components/Aviso';

/**
 * Monitoreo ESP32: temperatura, humedad y calidad del aire de los sensores
 * de planta.
 *
 * Los ESP32 publican por MQTT a Mosquitto; el receptor del portal guarda cada
 * lectura y abre alertas si algo se sale de su umbral (ver
 * backend/app/iot/ingestor.py). Esta pantalla solo lee: el último dato de
 * cada sensor, y la gráfica del que se elija. Se pone al día sola con el
 * evento `iot` del flujo en vivo.
 */
const MAGNITUDES = [
  { campo: 'temperatura', icono: Thermometer, unidad: ' °C', color: '#e3845f' },
  { campo: 'humedad', icono: Droplets, unidad: ' %', color: '#4bb0e6' },
  { campo: 'calidad_aire', icono: Wind, unidad: ' ppm', color: '#a4ae2d' },
];
const RANGOS = [1, 6, 24, 168];

export default function Monitoreo() {
  const { t, i18n } = useTranslation();
  const [consulta, setConsulta] = useSearchParams();
  const [dispositivos, setDispositivos] = useState([]);
  const [cargando, setCargando] = useState(true);
  const [aviso, setAviso] = useState('');
  const [plantas] = usePlantas();
  const [plantaId, setPlantaId] = useState(null);
  const [elegido, setElegido] = useState(() => Number(consulta.get('dispositivo')) || null);
  const [horas, setHoras] = useState(24);
  const [serie, setSerie] = useState(null);
  const [conexion, setConexion] = useState(null);
  const [verConexion, setVerConexion] = useState(false);
  const [editando, setEditando] = useState(null);
  const [porBorrar, setPorBorrar] = useState(null);

  const cargar = useCallback(async () => {
    try {
      const res = await api.get('/admin/iot/dispositivos', { params: plantaId ? { sitio_id: plantaId } : {} });
      setDispositivos(lista(res.data, 'los sensores'));
      setAviso('');
    } catch (err) {
      setAviso(mensajeDeError(err, t('iot.error_cargar')));
    } finally {
      setCargando(false);
    }
  }, [plantaId, t]);

  const cargarSerie = useCallback(async () => {
    if (!elegido) { setSerie(null); return; }
    try {
      const res = await api.get(`/admin/iot/dispositivos/${elegido}/lecturas`, { params: { horas, puntos: 120 } });
      setSerie(res.data);
    } catch {
      setSerie(null);
    }
  }, [elegido, horas]);

  useEffect(() => { cargar(); }, [cargar]);
  useEffect(() => { cargarSerie(); }, [cargarSerie]);
  useEffect(() => {
    api.get('/admin/iot/conexion').then((r) => setConexion(r.data)).catch(() => {});
  }, []);

  // Lecturas nuevas: el receptor avisa como mucho cada 5 s.
  useEventoPortal('iot', () => { cargar(); cargarSerie(); });
  useEventoPortal('alertas', () => cargar());

  const elegir = (id) => {
    setElegido(id);
    const nueva = new URLSearchParams(consulta);
    if (id) nueva.set('dispositivo', String(id)); else nueva.delete('dispositivo');
    setConsulta(nueva, { replace: true });
  };

  const hace = (fecha) => {
    if (!fecha) return t('iot.nunca');
    const s = Math.max(0, (Date.now() - new Date(fecha)) / 1000);
    const rtf = new Intl.RelativeTimeFormat(i18n.language, { numeric: 'auto' });
    if (s < 60) return rtf.format(-Math.round(s), 'second');
    if (s < 3600) return rtf.format(-Math.round(s / 60), 'minute');
    if (s < 86400) return rtf.format(-Math.round(s / 3600), 'hour');
    return rtf.format(-Math.round(s / 86400), 'day');
  };

  const actual = dispositivos.find((d) => d.id === elegido);

  const borrar = async () => {
    const d = porBorrar;
    setPorBorrar(null);
    try {
      await api.delete(`/admin/iot/dispositivos/${d.id}`);
      if (elegido === d.id) elegir(null);
      cargar();
    } catch (err) {
      avisar(mensajeDeError(err, t('iot.error_guardar')));
    }
  };

  return (
    <div className="page-container animate-fade-in">
      <div className="page-header">
        <div>
          <h1 className="page-title">{t('iot.titulo')}</h1>
          <p style={{ color: 'var(--text-secondary)', marginTop: '4px' }}>{t('iot.subtitulo')}</p>
        </div>
        <div style={{ display: 'flex', gap: '10px', flexWrap: 'wrap' }}>
          {plantas.length > 1 && (
            <SelectorPlanta todas plantas={plantas} value={plantaId} onChange={setPlantaId}
              style={{ minWidth: '220px' }} />
          )}
          <button type="button" className="btn-secondary" onClick={() => setVerConexion((v) => !v)}
            aria-expanded={verConexion}>
            <Info size={16} /> {t('iot.como_conectar')}
          </button>
        </div>
      </div>

      <Aviso texto={aviso} />

      {(verConexion || (!cargando && dispositivos.length === 0)) && conexion && (
        <GlassCard relleno="24px" style={{ marginBottom: '24px' }}>
          <h2 className="titulo-bloque"><Cpu size={19} /> {t('iot.como_conectar')}</h2>
          <ol className="iot-pasos">
            <li>{t('iot.paso_broker', { puerto: conexion.puerto })}</li>
            <li>{t('iot.paso_usuario', { usuario: conexion.usuario_dispositivos })}</li>
            <li>{t('iot.paso_tema')}<code className="iot-codigo">{conexion.tema}</code></li>
            <li>{t('iot.paso_json')}<code className="iot-codigo">{JSON.stringify(conexion.ejemplo)}</code></li>
            <li>{t('iot.paso_intervalo', { segundos: conexion.intervalo_minimo_s, minutos: conexion.sin_senal_minutos })}</li>
          </ol>
          <p className="nota-suave">{t('iot.nota_sketch')}</p>
        </GlassCard>
      )}

      {cargando ? (
        <EsqueletoLista filas={2} />
      ) : dispositivos.length === 0 ? (
        <EstadoVacio icono={<Cpu size={26} />} texto={t('iot.vacio')} detalle={t('iot.vacio_detalle')} />
      ) : (
        <div className="iot-rejilla">
          {dispositivos.map((d) => {
            const estado = !d.activo ? 'apagado' : d.en_linea ? 'vivo' : 'callado';
            return (
              <button
                type="button"
                key={d.id}
                className={`apple-card iot-tarjeta${elegido === d.id ? ' iot-tarjeta--elegida' : ''}`}
                onClick={() => elegir(elegido === d.id ? null : d.id)}
                aria-pressed={elegido === d.id}
              >
                <div className="iot-tarjeta-cabeza">
                  <span className={`iot-punto iot-punto--${estado}`} aria-hidden="true" />
                  <strong className="iot-nombre">{d.nombre || d.clave}</strong>
                  {d.alertas_abiertas > 0 && (
                    <span className="chip-dato iot-alerta" title={t('iot.alertas_abiertas')}>
                      <AlertTriangle size={12} /> {d.alertas_abiertas}
                    </span>
                  )}
                </div>
                <div className="iot-tarjeta-sub">
                  <EtiquetaPlanta planta={d.sitio} compacta />
                  {d.ubicacion && <span>{d.ubicacion}</span>}
                  <code>{d.clave}</code>
                </div>
                <div className="iot-lecturas">
                  {MAGNITUDES.map(({ campo, icono: Icono, unidad }) => {
                    const v = d.ultima?.[campo];
                    const alto = v != null && v > d.umbrales?.[campo];
                    return (
                      <div key={campo} className={`iot-lectura${alto ? ' iot-lectura--alta' : ''}`}>
                        <Icono size={15} aria-hidden="true" />
                        <span className="iot-lectura-valor">{v != null ? `${Number(v.toFixed(1))}${unidad}` : '—'}</span>
                        <span className="iot-lectura-nombre">{t(`iot.magnitud_${campo}`)}</span>
                      </div>
                    );
                  })}
                </div>
                <div className="iot-tarjeta-pie">
                  {estado === 'vivo' ? <Wifi size={13} /> : <WifiOff size={13} />}
                  {estado === 'apagado' ? t('iot.desactivado') : `${t('iot.ultimo_dato')} ${hace(d.ultimo_contacto)}`}
                </div>
              </button>
            );
          })}
        </div>
      )}

      {actual && (
        <GlassCard relleno="24px" style={{ marginTop: '24px' }}>
          <div className="iot-detalle-cabeza">
            <h2 className="titulo-bloque" style={{ margin: 0 }}>
              <Cpu size={19} /> {actual.nombre || actual.clave}
            </h2>
            <div className="filtros-estado">
              {RANGOS.map((h) => (
                <button key={h} type="button" onClick={() => setHoras(h)}
                  className={`chip-filtro${horas === h ? ' chip-filtro--activo' : ''}`} aria-pressed={horas === h}>
                  {h < 24 ? t('iot.horas', { count: h }) : t('iot.dias', { count: h / 24 })}
                </button>
              ))}
              <button type="button" className="btn-secondary" onClick={() => setEditando(actual)}
                style={{ padding: '8px 12px' }}>
                <Pencil size={15} /> {t('iot.editar')}
              </button>
              <button type="button" className="btn-secondary btn-secondary--peligro"
                onClick={() => setPorBorrar(actual)} style={{ padding: '8px 12px' }}
                aria-label={t('iot.borrar')} title={t('iot.borrar')}>
                <Trash2 size={15} />
              </button>
            </div>
          </div>
          {serie && serie.lecturas > 0 ? (
            <div className="iot-graficas">
              {MAGNITUDES.map(({ campo, unidad, color }) => (
                <GraficaLinea
                  key={campo}
                  puntos={serie.puntos}
                  campo={campo}
                  unidad={unidad}
                  color={color}
                  umbral={actual.umbrales?.[campo]}
                  etiqueta={t(`iot.magnitud_${campo}`)}
                  idioma={i18n.language}
                  pasoSegundos={serie.paso_segundos}
                />
              ))}
              <p className="nota-suave">
                {t('iot.resumen_serie', { lecturas: serie.lecturas, paso: Math.round(serie.paso_segundos / 60) || 1 })}
              </p>
            </div>
          ) : (
            <div className="grafica-vacia">{t('iot.sin_lecturas_rango')}</div>
          )}
        </GlassCard>
      )}

      {editando && (
        <EditarSensor
          dispositivo={editando}
          plantas={plantas}
          onCerrar={() => setEditando(null)}
          onGuardado={() => { setEditando(null); cargar(); }}
        />
      )}

      {porBorrar && (
        <Confirmacion
          titulo={t('iot.borrar')}
          mensaje={t('iot.borrar_confirmar', { nombre: porBorrar.nombre || porBorrar.clave })}
          textoConfirmar={t('iot.borrar')}
          tono="peligro"
          onConfirmar={borrar}
          onCancelar={() => setPorBorrar(null)}
        />
      )}
    </div>
  );
}

function EditarSensor({ dispositivo, plantas, onCerrar, onGuardado }) {
  const { t } = useTranslation();
  const propios = dispositivo.umbrales_propios || {};
  const [nombre, setNombre] = useState(dispositivo.nombre || '');
  const [ubicacion, setUbicacion] = useState(dispositivo.ubicacion || '');
  const [plantaId, setPlantaId] = useState(dispositivo.sitio?.id ?? null);
  const [activo, setActivo] = useState(dispositivo.activo);
  const [umbrales, setUmbrales] = useState({
    temperatura: propios.temperatura ?? '', humedad: propios.humedad ?? '', calidad_aire: propios.calidad_aire ?? '',
  });
  const [aviso, setAviso] = useState('');
  const [enviando, setEnviando] = useState(false);

  const guardar = async (e) => {
    e.preventDefault();
    setEnviando(true);
    setAviso('');
    try {
      const cuerpo = {
        nombre: nombre.trim() || dispositivo.clave,
        ubicacion: ubicacion.trim() || null,
        activo,
        // Vacío = vuelve al umbral general.
        umbrales: Object.fromEntries(Object.entries(umbrales)
          .map(([k, v]) => [k, v === '' || v == null ? null : Number(v)])),
      };
      if (plantaId) cuerpo.sitio_id = plantaId;
      await api.patch(`/admin/iot/dispositivos/${dispositivo.id}`, cuerpo);
      onGuardado();
    } catch (err) {
      setAviso(mensajeDeError(err, t('iot.error_guardar')));
      setEnviando(false);
    }
  };

  return (
    <CapaModal onCerrar={onCerrar} etiqueta={t('iot.editar')}>
      <Formulario onSubmit={guardar} className="apple-card animate-scale-in"
        onClick={(e) => e.stopPropagation()}
        style={{ width: '100%', maxWidth: '520px', padding: '28px', maxHeight: '90vh', overflowY: 'auto' }}>
        <h2 style={{ fontSize: '1.25rem', fontWeight: 700, marginBottom: '4px', color: 'var(--text-primary)' }}>
          {t('iot.editar')}
        </h2>
        <p className="nota-suave" style={{ marginBottom: '18px' }}><code>{dispositivo.clave}</code></p>

        <div className="form-group">
          <label htmlFor="sensor-nombre">{t('iot.nombre')}</label>
          <input id="sensor-nombre" className="form-input" maxLength={100} value={nombre}
            onChange={(e) => setNombre(e.target.value)} placeholder={t('iot.nombre_ejemplo')} />
        </div>
        <div className="form-group">
          <label htmlFor="sensor-ubicacion">{t('iot.ubicacion')}</label>
          <input id="sensor-ubicacion" className="form-input" maxLength={100} value={ubicacion}
            onChange={(e) => setUbicacion(e.target.value)} />
        </div>
        {plantas.length > 1 && (
          <div className="form-group">
            <label htmlFor="sensor-planta">{t('plantas.planta')}</label>
            <SelectorPlanta id="sensor-planta" plantas={plantas} value={plantaId} onChange={setPlantaId} />
          </div>
        )}

        <fieldset className="iot-umbrales">
          <legend>{t('iot.umbrales')}</legend>
          {MAGNITUDES.map(({ campo, unidad }) => (
            <div key={campo} className="form-group">
              <label htmlFor={`umbral-${campo}`}>{t(`iot.magnitud_${campo}`)} ({unidad.trim()})</label>
              <input id={`umbral-${campo}`} className="form-input" type="number" step="0.1"
                value={umbrales[campo]}
                placeholder={String(dispositivo.umbrales?.[campo] ?? '')}
                onChange={(e) => setUmbrales({ ...umbrales, [campo]: e.target.value })} />
            </div>
          ))}
          <p className="nota-suave">{t('iot.umbrales_ayuda')}</p>
        </fieldset>

        <label className="interruptor" style={{ marginTop: '10px' }}>
          <input type="checkbox" checked={activo} onChange={(e) => setActivo(e.target.checked)} />
          {t('iot.activo')}
        </label>
        <p className="nota-suave">{t('iot.activo_ayuda')}</p>

        <Aviso texto={aviso} />
        <div style={{ display: 'flex', gap: '10px', justifyContent: 'flex-end', marginTop: '18px' }}>
          <button type="button" onClick={onCerrar} className="btn-secondary"><X size={15} /> {t('temas.cancelar')}</button>
          <button type="submit" className="btn-primary" disabled={enviando}>
            <Check size={15} /> {enviando ? t('temas.guardando') : t('temas.guardar')}
          </button>
        </div>
      </Formulario>
    </CapaModal>
  );
}
